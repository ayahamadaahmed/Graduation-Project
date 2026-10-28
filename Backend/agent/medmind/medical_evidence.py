from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
import os
import re
import time
import xml.etree.ElementTree as ET

import httpx


@dataclass(frozen=True, slots=True)
class ExternalMedicalSource:
    title: str
    url: str
    publisher: str
    summary: str
    published: str | None = None
    source_type: str = "medical reference"


class MedicalEvidenceRetriever:
    """Fetch de-identified, topic-level medical evidence on demand.

    This is a retrieval layer, not a diagnostic engine. Only an allowlisted
    medical topic is sent to public search APIs; the user's message, report,
    identifiers, and conversation history are never sent.
    """

    MEDLINEPLUS_URL = "https://wsearch.nlm.nih.gov/ws/query"
    NCBI_EUTILS_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    TOPIC_ALIASES: dict[str, str] = {
        "cbc": "complete blood count",
        "vitamin d": "vitamin D blood test",
        "فيتامين د": "vitamin D blood test",
        "25-oh": "25-hydroxy vitamin D test",
        "25(oh)d": "25-hydroxy vitamin D test",
        "ferritin": "ferritin blood test",
        "الفيريتين": "ferritin blood test",
        "serum iron": "iron blood tests",
        "iron studies": "iron blood tests",
        "tibc": "iron blood tests",
        "transferrin saturation": "iron blood tests",
        "iron": "iron blood tests",
        "vitamin b12": "vitamin B12 blood test",
        "فيتامين ب12": "vitamin B12 blood test",
        "b12": "vitamin B12 blood test",
        "folate": "folate blood test",
        "الفولات": "folate blood test",
        "حمض الفوليك": "folate blood test",
        "reticulocyte": "reticulocyte count test",
        "الخلايا الشبكية": "reticulocyte count test",
        "صورة الدم الكاملة": "complete blood count",
        "كرات الدم البيضاء": "white blood cell count",
        "white blood cells": "white blood cell count",
        "wbc": "white blood cell count",
        "العدلات": "neutrophils blood differential",
        "neutrophils": "neutrophils blood differential",
        "neutropenia": "neutropenia",
        "انخفاض العدلات": "neutropenia",
        "anemia": "anemia",
        "فقر الدم": "anemia",
        "الهيموجلوبين": "hemoglobin blood test",
        "diabetes": "diabetes",
        "السكري": "diabetes",
        "hba1c": "hemoglobin A1c test",
        "السكر التراكمي": "hemoglobin A1c test",
        "hypertension": "high blood pressure",
        "ضغط الدم": "high blood pressure",
        "headache": "headache",
        "صداع": "headache",
        "pneumonia": "pneumonia",
        "التهاب رئوي": "pneumonia",
        "common cold": "common cold",
        "نزلة برد": "common cold",
        "fever": "fever",
        "حمى": "fever",
        "حرارة": "fever",
        "cough": "cough",
        "كحة": "cough",
        "سعال": "cough",
        "sore throat": "sore throat",
        "التهاب الحلق": "sore throat",
        "chest pain": "chest pain",
        "ألم الصدر": "chest pain",
        "ضيق التنفس": "shortness of breath",
        "shortness of breath": "shortness of breath",
    }

    FRESHNESS_CUES = (
        "latest", "current guideline", "newest", "recent research",
        "latest evidence", "أحدث", "احدث", "آخر توصية", "اخر توصية",
        "أحدث الأبحاث", "احدث الابحاث", "آخر الأبحاث", "اخر الابحاث",
        "دلوقتي", "حاليًا", "حاليا",
    )
    GUIDELINE_CUES = (
        "guideline", "guidelines", "recommendation", "recommendations",
        "توصية", "توصيات", "إرشادات", "ارشادات", "دليل علاجي",
    )

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        timeout_seconds: float = 4.0,
        cache_ttl_seconds: int = 12 * 60 * 60,
    ) -> None:
        if enabled is None:
            enabled = os.getenv(
                "MEDMIND_EXTERNAL_MEDICAL_SEARCH_ENABLED", "1"
            ).strip().lower() not in {"0", "false", "no", "off"}
        self.enabled = enabled
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[
            tuple[str, bool, bool], tuple[float, list[ExternalMedicalSource]]
        ] = {}

    @staticmethod
    def _normalize(text: str) -> str:
        value = str(text or "").lower().strip()
        return re.sub(r"\s+", " ", value)

    @classmethod
    def topic_for(cls, text: str) -> str | None:
        normalized = cls._normalize(text)
        aliases = sorted(
            cls.TOPIC_ALIASES.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        )
        for alias, topic in aliases:
            if cls._normalize(alias) in normalized:
                return topic
        return None

    @classmethod
    def requests_recent_evidence(cls, text: str) -> bool:
        normalized = cls._normalize(text)
        return (
            any(cue in normalized for cue in cls.FRESHNESS_CUES)
            or cls.requests_guideline(text)
        )

    @classmethod
    def requests_guideline(cls, text: str) -> bool:
        normalized = cls._normalize(text)
        return any(cue in normalized for cue in cls.GUIDELINE_CUES)

    async def search(
        self,
        *,
        topic: str,
        include_literature: bool = False,
        guidelines_only: bool = False,
    ) -> list[ExternalMedicalSource]:
        if not self.enabled or not topic.strip():
            return []

        cache_key = (topic, include_literature, guidelines_only)
        cached = self._cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] < self.cache_ttl_seconds:
            return list(cached[1])

        timeout = httpx.Timeout(self.timeout_seconds, connect=2.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            tasks = [self._search_medlineplus(client, topic)]
            if include_literature:
                tasks.append(
                    self._search_pubmed(
                        client,
                        topic,
                        guidelines_only=guidelines_only,
                    )
                )
            results = await asyncio.gather(*tasks, return_exceptions=True)

        sources: list[ExternalMedicalSource] = []
        for result in results:
            if isinstance(result, list):
                sources.extend(result)

        self._cache[cache_key] = (time.monotonic(), sources)
        return sources

    async def _search_medlineplus(
        self,
        client: httpx.AsyncClient,
        topic: str,
    ) -> list[ExternalMedicalSource]:
        try:
            response = await client.get(
                self.MEDLINEPLUS_URL,
                params={
                    "db": "healthTopics",
                    "term": topic,
                    "retmax": "3",
                    "rettype": "brief",
                    "tool": "medmind",
                },
            )
            response.raise_for_status()
            root = ET.fromstring(response.text)
        except (httpx.HTTPError, ET.ParseError):
            return []

        sources: list[ExternalMedicalSource] = []
        for document in root.findall(".//document")[:3]:
            url = document.get("url", "").strip()
            title = ""
            summary = ""
            for content in document.findall("content"):
                text = self._plain_text("".join(content.itertext()))
                name = content.get("name", "").lower()
                if name == "title" and not title:
                    title = text
                elif name in {"fullsummary", "snippet"} and len(text) > len(summary):
                    summary = text
            if url.startswith("https://medlineplus.gov/") and title and summary:
                sources.append(
                    ExternalMedicalSource(
                        title=title,
                        url=url,
                        publisher="MedlinePlus / U.S. National Library of Medicine",
                        summary=summary[:1800],
                        source_type="patient education",
                    )
                )
        return sources

    async def _search_pubmed(
        self,
        client: httpx.AsyncClient,
        topic: str,
        *,
        guidelines_only: bool,
    ) -> list[ExternalMedicalSource]:
        publication_filter = (
            ' AND ("Practice Guideline"[Publication Type] '
            'OR "Guideline"[Publication Type])'
            if guidelines_only
            else ""
        )
        try:
            search = await client.get(
                f"{self.NCBI_EUTILS_URL}/esearch.fcgi",
                params={
                    "db": "pubmed",
                    "term": (
                        f'({topic}) AND ("last 5 years"[Date - Publication])'
                        + publication_filter
                    ),
                    "sort": "date",
                    "retmax": "3",
                    "retmode": "json",
                    "tool": "medmind",
                    **self._ncbi_identification_params(),
                },
            )
            search.raise_for_status()
            ids = search.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                return []

            fetch = await client.get(
                f"{self.NCBI_EUTILS_URL}/efetch.fcgi",
                params={
                    "db": "pubmed",
                    "id": ",".join(ids[:3]),
                    "retmode": "xml",
                    "tool": "medmind",
                    **self._ncbi_identification_params(),
                },
            )
            fetch.raise_for_status()
            root = ET.fromstring(fetch.text)
        except (httpx.HTTPError, ValueError, ET.ParseError):
            return []

        sources: list[ExternalMedicalSource] = []
        for article in root.findall(".//PubmedArticle"):
            pmid = (article.findtext(".//PMID") or "").strip()
            title_node = article.find(".//ArticleTitle")
            title = self._plain_text(
                "".join(title_node.itertext()) if title_node is not None else ""
            )
            abstract = " ".join(
                self._plain_text("".join(item.itertext()))
                for item in article.findall(".//Abstract/AbstractText")
                if item is not None
            )
            published = self._publication_date(article)
            if pmid and title and abstract:
                sources.append(
                    ExternalMedicalSource(
                        title=title,
                        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        publisher="PubMed / U.S. National Library of Medicine",
                        summary=abstract[:1800],
                        published=published,
                        source_type=(
                            "PubMed-indexed guideline"
                            if guidelines_only
                            else "research article abstract"
                        ),
                    )
                )
        return sources

    @staticmethod
    def _publication_date(article: ET.Element) -> str | None:
        date_node = article.find(".//PubDate")
        if date_node is None:
            return None
        parts = [
            (date_node.findtext(name) or "").strip()
            for name in ("Year", "Month", "Day")
        ]
        value = " ".join(part for part in parts if part)
        return value or None

    @staticmethod
    def _plain_text(value: str) -> str:
        cleaned = re.sub(r"<[^>]+>", " ", value)
        return re.sub(r"\s+", " ", unescape(cleaned)).strip()

    @staticmethod
    def _ncbi_identification_params() -> dict[str, str]:
        params: dict[str, str] = {}
        email = os.getenv("NCBI_EMAIL", "").strip()
        api_key = os.getenv("NCBI_API_KEY", "").strip()
        if email:
            params["email"] = email
        if api_key:
            params["api_key"] = api_key
        return params

    @staticmethod
    def retrieved_date() -> str:
        return datetime.now(timezone.utc).date().isoformat()
