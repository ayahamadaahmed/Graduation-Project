from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import math
import os
import re


class MedicalEducationStatus(str, Enum):
    ANSWERED = "answered"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class MedicalEducationSource:
    source_file: str
    score: float


@dataclass(frozen=True, slots=True)
class MedicalEducationResult:
    status: MedicalEducationStatus
    reply: str
    sources: list[MedicalEducationSource]
    context_used: list[str]


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    source_file: str
    title: str
    text: str
    tokens: frozenset[str]


class MedicalEducationAgent:
    """
    Educational medical information agent based on a curated local
    knowledge base.

    This agent does not diagnose, prescribe, or modify diagnostic
    model results. It only explains general medical concepts using
    trusted markdown files.
    """

    _ALIASES: dict[str, str] = {
        "cbc":
            "cbc complete blood count صورة الدم الكاملة تحليل صورة الدم "
            "hemoglobin الهيموجلوبين anemia انيميا فقر الدم wbc white blood cell "
            "كرات الدم البيضاء neutrophils العدلات lymphocytes الليمفاوية "
            "monocytes eosinophils basophils platelets الصفائح",

        "complete blood count":
            "cbc complete blood count صورة الدم الكاملة تحليل صورة الدم",

        "hemoglobin":
            "hemoglobin hb الهيموجلوبين فقر الدم anemia انيميا",

        "vitamin d":
            "vitamin d فيتامين د 25-oh 25(oh)d 25-hydroxy",

        "فيتامين د":
            "vitamin d 25-oh 25-hydroxy vitamin D test",

        "ferritin":
            "ferritin الفيريتين iron stores مخزون الحديد anemia فقر الدم",

        "الفيريتين":
            "ferritin مخزون الحديد iron stores anemia فقر الدم",

        "iron":
            "iron serum iron الحديد ferritin الفيريتين tibc anemia فقر الدم",

        "الحديد":
            "iron serum iron ferritin الفيريتين tibc مخزون الحديد anemia فقر الدم",

        "vitamin b12":
            "vitamin b12 b12 cobalamin فيتامين ب12 anemia فقر الدم",

        "فيتامين ب12":
            "vitamin b12 cobalamin anemia فقر الدم",

        "folate":
            "folate folic acid حمض الفوليك الفولات anemia فقر الدم",

        "حمض الفوليك":
            "folate folic acid الفولات anemia فقر الدم",

        "anemia":
            "anemia anaemia انيميا فقر الدم hemoglobin hb ferritin iron "
            "vitamin b12 folate b12 cbc reticulocyte",

        "فقر الدم":
            "anemia anaemia hemoglobin ferritin iron vitamin b12 folate cbc reticulocyte",

        "neutrophil":
            "neutrophils العدلات white blood cell differential CBC صورة الدم",

        "neutrophils":
            "neutrophil العدلات white blood cell differential CBC صورة الدم",

        "العدلات":
            "neutrophils neutrophil white blood cell differential CBC صورة الدم",

        "lymphocyte":
            "lymphocytes الخلايا الليمفاوية white blood cell differential CBC صورة الدم",

        "lymphocytes":
            "lymphocyte الخلايا الليمفاوية white blood cell differential CBC صورة الدم",

        "الليمفاوية":
            "lymphocytes lymphocyte white blood cell differential CBC صورة الدم",

        "monocytes":
            "الخلايا الوحيدة monocytes white blood cell differential CBC صورة الدم",

        "eosinophils":
            "الخلايا الحمضية eosinophils white blood cell differential CBC صورة الدم",

        "basophils":
            "الخلايا القاعدية basophils white blood cell differential CBC صورة الدم",

        "white blood cells":
            "WBC كرات الدم البيضاء neutrophils lymphocytes monocytes eosinophils basophils CBC",

        "كرات الدم البيضاء":
            "WBC white blood cells neutrophils lymphocytes monocytes eosinophils basophils CBC",

        "diabetes":
            "diabetes السكري السكر hba1c a1c fasting glucose "
            "prediabetes ما قبل السكري",

        "hba1c":
            "hba1c a1c السكر التراكمي diabetes السكري",

        "prediabetes":
            "prediabetes ما قبل السكري diabetes السكر السكري",

        "hypertension":
            "hypertension high blood pressure ضغط الدم الضغط",

        "blood pressure":
            "blood pressure hypertension ضغط الدم الضغط",

        "heart attack":
            "heart attack ازمة قلبية أزمة قلبية الم الصدر chest pain",

        "headache":
            "headache migraine صداع الصداع الشقيقة",

        "pneumonia":
            "pneumonia التهاب رئوي chest xray chest x-ray اشعة الصدر",
    }

    def __init__(
        self,
        *,
        knowledge_base_dir: str | Path | None = None,
        min_score: float = 0.10,
        top_k: int = 2,
        max_context_chars: int = 900,
    ) -> None:

        self.knowledge_base_dir = (
            self._resolve_knowledge_base_dir(
                knowledge_base_dir
            )
        )

        self.min_score = float(
            min_score
        )

        self.top_k = int(
            top_k
        )

        self.max_context_chars = int(
            max_context_chars
        )

        self.chunks = (
            self._load_chunks()
        )

    def answer(
        self,
        *,
        query: str,
        language: str,
    ) -> MedicalEducationResult:

        ranked = (
            self.retrieve(
                query=query,
                top_k=self.top_k,
            )
        )

        relevant = [
            item
            for item in ranked
            if item[1] >= self.min_score
        ]

        if not relevant:
            return MedicalEducationResult(
                status=(
                    MedicalEducationStatus
                    .UNSUPPORTED
                ),
                reply=(
                    self._unsupported_reply(
                        language=language,
                    )
                ),
                sources=[],
                context_used=[],
            )

        selected_contexts = [
            self._clean_context(
                chunk.text
            )
            for chunk, _score in relevant
        ]

        source_scores: dict[str, float] = {}

        for chunk, score in relevant:

            current_score = (
                source_scores
                .get(
                    chunk.source_file,
                    0.0,
                )
            )

            source_scores[
                chunk.source_file
            ] = max(
                current_score,
                float(score),
            )

        sources = [
            MedicalEducationSource(
                source_file=source_file,
                score=round(
                    score,
                    4,
                ),
            )
            for source_file, score
            in source_scores.items()
        ]

        reply = (
            self._build_reply(
                contexts=selected_contexts,
                sources=sources,
                language=language,
            )
        )

        return MedicalEducationResult(
            status=MedicalEducationStatus.ANSWERED,
            reply=reply,
            sources=sources,
            context_used=selected_contexts,
        )

    def retrieve(
        self,
        *,
        query: str,
        top_k: int,
    ) -> list[tuple[KnowledgeChunk, float]]:

        if not self.chunks:
            return []

        query_text = (
            self._expand_query(
                query
            )
        )

        query_tokens = (
            self._tokenize(
                query_text
            )
        )

        if not query_tokens:
            return []

        scored: list[
            tuple[KnowledgeChunk, float]
        ] = []

        for chunk in self.chunks:

            overlap = (
                query_tokens
                & chunk.tokens
            )

            if not overlap:
                score = 0.0
            else:
                score = (
                    len(overlap)
                    / math.sqrt(
                        len(query_tokens)
                        * len(chunk.tokens)
                    )
                )

            scored.append(
                (
                    chunk,
                    float(score),
                )
            )

        scored.sort(
            key=lambda item: item[1],
            reverse=True,
        )

        return scored[
            : max(
                1,
                int(top_k),
            )
        ]

    def _load_chunks(
        self,
    ) -> list[KnowledgeChunk]:

        kb_dir = (
            self.knowledge_base_dir
        )

        if (
            kb_dir is None
            or not kb_dir.exists()
        ):
            return []

        chunks: list[
            KnowledgeChunk
        ] = []

        for md_file in sorted(
            kb_dir.glob("*.md")
        ):

            text = md_file.read_text(
                encoding="utf-8"
            )

            sections = re.split(
                r"\n(?=## )",
                text,
            )

            for section in sections:

                cleaned = (
                    section.strip()
                )

                if len(cleaned) < 40:
                    continue

                title = (
                    self._extract_title(
                        cleaned
                    )
                )

                chunks.append(
                    KnowledgeChunk(
                        source_file=(
                            md_file.stem
                        ),
                        title=title,
                        text=cleaned,
                        tokens=(
                            self._tokenize(
                                cleaned
                            )
                        ),
                    )
                )

        return chunks

    @classmethod
    def _resolve_knowledge_base_dir(
        cls,
        knowledge_base_dir: str | Path | None,
    ) -> Path | None:

        if knowledge_base_dir is not None:
            return Path(
                knowledge_base_dir
            )

        env_dir = (
            os.getenv(
                "MEDMIND_MEDICAL_KB_DIR"
            )
        )

        if env_dir:
            return Path(
                env_dir
            )

        backend_root = (
            Path(__file__)
            .resolve()
            .parents[2]
        )

        candidates = [
            backend_root
            / "knowledge_base"
            / "lab-001"
            / "medical_education",

            backend_root
            / "data"
            / "knowledge_base",

            backend_root
            / "Diagnostic Agent"
            / "data"
            / "knowledge_base",
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        return candidates[0]

    @classmethod
    def _expand_query(
        cls,
        query: str,
    ) -> str:

        text = str(
            query or ""
        )

        normalized = (
            cls._normalize(
                text
            )
        )

        expansions: list[str] = []

        for key, value in cls._ALIASES.items():

            if (
                cls._normalize(key)
                in normalized
            ):
                expansions.append(
                    value
                )

        if not expansions:
            return text

        return (
            text
            + " "
            + " ".join(
                dict.fromkeys(
                    expansions
                )
            )
        )

    @staticmethod
    def _extract_title(
        text: str,
    ) -> str:

        for line in text.splitlines():

            clean = (
                line.strip()
                .lstrip("#")
                .strip()
            )

            if clean:
                return clean

        return "Medical education"

    @classmethod
    def _tokenize(
        cls,
        text: str,
    ) -> frozenset[str]:

        normalized = (
            cls._normalize(
                text
            )
        )

        tokens = re.findall(
            r"[\w\u0600-\u06FF]+",
            normalized,
            flags=re.UNICODE,
        )

        useful = [
            token
            for token in tokens
            if len(token) >= 2
        ]

        return frozenset(
            useful
        )

    @staticmethod
    def _normalize(
        text: str,
    ) -> str:

        normalized = (
            str(text or "")
            .lower()
            .strip()
        )

        normalized = (
            normalized
            .replace("إ", "ا")
            .replace("أ", "ا")
            .replace("آ", "ا")
            .replace("ى", "ي")
            .replace("ة", "ه")
            .replace("ـ", "")
        )

        normalized = re.sub(
            r"\s+",
            " ",
            normalized,
        )

        return normalized

    def _clean_context(
        self,
        text: str,
    ) -> str:

        cleaned = re.sub(
            r"\n?---\n?.*$",
            "",
            text.strip(),
            flags=re.DOTALL,
        ).strip()

        if (
            len(cleaned)
            <= self.max_context_chars
        ):
            return cleaned

        return (
            cleaned[
                : self.max_context_chars
            ].rstrip()
            + "..."
        )

    @staticmethod
    def _unsupported_reply(
        *,
        language: str,
    ) -> str:

        if language == "ar":
            return (
                "معنديش معلومات كفاية في المكتبة الطبية "
                "الموثوقة عندنا عن السؤال ده. "
                "الأفضل تسأل دكتور أو صيدلي لو الموضوع متعلق "
                "بقرار طبي."
            )

        return (
            "I do not have enough information in the trusted "
            "medical knowledge base to answer this safely. "
            "Please ask a clinician or pharmacist if this is "
            "related to a medical decision."
        )

    @staticmethod
    def _build_reply(
        *,
        contexts: list[str],
        sources: list[MedicalEducationSource],
        language: str,
    ) -> str:

        context_text = (
            "\n\n".join(
                contexts
            )
        )

        source_names = (
            ", ".join(
                dict.fromkeys(
                    source.source_file
                    for source in sources
                )
            )
        )

        if language == "ar":
            return (
                "دي معلومات تعليمية من المكتبة الطبية عندنا، "
                "مش تشخيص نهائي ولا بديل عن كشف الدكتور.\n\n"
                f"{context_text}\n\n"
                f"المصادر الداخلية: {source_names}"
            )

        return (
            "This is educational information from the trusted "
            "medical knowledge base. It is not a diagnosis and "
            "does not replace a clinician's assessment.\n\n"
            f"{context_text}\n\n"
            f"Internal sources: {source_names}"
        )
