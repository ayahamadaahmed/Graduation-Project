from __future__ import annotations

import re

from pathlib import Path

from rag.models import (
    KnowledgeDocument,
)
from datetime import date

ARABIC_PATTERN = re.compile(
    r"[\u0600-\u06FF]"
)

ENGLISH_PATTERN = re.compile(
    r"[A-Za-z]"
)


def _detect_language(
    text: str,
) -> str:

    has_arabic = bool(
        ARABIC_PATTERN.search(
            text
        )
    )

    has_english = bool(
        ENGLISH_PATTERN.search(
            text
        )
    )

    if (
        has_arabic
        and
        has_english
    ):
        return "mixed"

    if has_arabic:
        return "ar"

    return "en"


def _extract_title(
    content: str,
    fallback: str,
) -> str:

    for line in content.splitlines():

        normalized = (
            line.strip()
        )

        if normalized.startswith(
            "# "
        ):

            title = (
                normalized[2:]
                .strip()
            )

            if title:
                return title

    return fallback

def _extract_metadata(
    content: str,
) -> dict[str, str]:

    metadata: dict[
        str,
        str,
    ] = {}

    for line in content.splitlines():

        normalized = (
            line.strip()
        )

        if normalized.startswith(
            "Source type:"
        ):
            metadata[
                "source_type"
            ] = (
                normalized
                .split(
                    ":",
                    1,
                )[1]
                .strip()
            )

        elif normalized.startswith(
            "Source URL:"
        ):
            metadata[
                "source_url"
            ] = (
                normalized
                .split(
                    ":",
                    1,
                )[1]
                .strip()
            )

        elif normalized.startswith(
            "Retrieved:"
        ):
            metadata[
                "retrieved_at"
            ] = (
                normalized
                .split(
                    ":",
                    1,
                )[1]
                .strip()
            )

    return metadata

def load_markdown_document(
    *,
    knowledge_root: Path,
    path: Path,
) -> KnowledgeDocument:

    relative_path = (
        path.relative_to(
            knowledge_root
        )
    )

    parts = (
        relative_path.parts
    )

    if len(parts) < 3:

        raise ValueError(
            "Knowledge document path must "
            "contain tenant/category/file."
        )

    tenant_id = (
        parts[0]
    )

    category = (
        parts[1]
    )

    content = (
        path.read_text(
            encoding="utf-8"
        )
        .strip()
    )

    if not content:

        raise ValueError(
            f"Knowledge document is empty: "
            f"{relative_path}"
        )

    document_id = (
        f"{tenant_id}:"
        f"{category}:"
        f"{path.stem}"
    )

    title = (
        _extract_title(
            content,
            fallback=path.stem,
        )
    )

    language = (
        _detect_language(
            content
        )
    )

    metadata = (
        _extract_metadata(
            content
        )
    )
    clean_content = (
        _strip_metadata_lines(
            content
        )
    )
    retrieved_at = None

    retrieved_text = (
        metadata.get(
            "retrieved_at"
        )
    )

    if retrieved_text:

        retrieved_at = (
            date.fromisoformat(
                retrieved_text
            )
        )

    return KnowledgeDocument(
        document_id=
            document_id,

        tenant_id=
            tenant_id,

        title=
            title,

        category=
            category,

        language=
            language,

        source=
            relative_path
            .as_posix(),

        content=
            clean_content,
        source_url=
            metadata.get(
                "source_url"
            ),

        source_type=
            metadata.get(
                "source_type"
            ),

        retrieved_at=
            retrieved_at,

        tags=[],
    )


def load_tenant_documents(
    *,
    knowledge_root: Path,
    tenant_id: str,
) -> list[
    KnowledgeDocument
]:

    tenant_root = (
        knowledge_root
        /
        tenant_id
    )

    if not tenant_root.exists():

        raise ValueError(
            f"Unknown knowledge tenant: "
            f"{tenant_id}"
        )

    documents = []

    for path in sorted(
        tenant_root.rglob(
            "*.md"
        )
    ):

        documents.append(
            load_markdown_document(
                knowledge_root=
                    knowledge_root,

                path=
                    path,
            )
        )

    return documents

def _strip_metadata_lines(
    content: str,
) -> str:

    prefixes = (
        "Source type:",
        "Source URL:",
        "Retrieved:",
    )

    cleaned_lines = []

    for line in content.splitlines():

        normalized = (
            line.strip()
        )

        if normalized.startswith(
            prefixes
        ):
            continue

        cleaned_lines.append(
            line
        )

    return (
        "\n".join(
            cleaned_lines
        )
        .strip()
    )
