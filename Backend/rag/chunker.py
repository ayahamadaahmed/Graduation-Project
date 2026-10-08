from __future__ import annotations

from rag.models import (
    KnowledgeChunk,
    KnowledgeDocument,
)


def _chunk_paragraphs(
    content: str,
    *,
    max_chars: int,
) -> list[str]:

    paragraphs = [
        paragraph.strip()
        for paragraph in content.split("\n\n")
        if paragraph.strip()
    ]

    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    for paragraph in paragraphs:

        paragraph_length = len(
            paragraph
        )

        if (
            current
            and
            current_length
            + paragraph_length
            + 2
            > max_chars
        ):
            chunks.append(
                "\n\n".join(
                    current
                )
            )

            current = []
            current_length = 0

        current.append(
            paragraph
        )

        current_length += (
            paragraph_length
            + 2
        )

    if current:

        chunks.append(
            "\n\n".join(
                current
            )
        )

    return chunks


def _split_markdown_sections(
    content: str,
) -> list[str]:

    """
    Split a Markdown catalog on H2 headings.

    Each `## ...` section remains together so fields such
    as doctor, service, duration, and price are not separated
    across unrelated chunks.
    """

    sections: list[str] = []
    current: list[str] = []

    for line in content.splitlines():

        if (
            line.startswith("## ")
            and current
        ):
            section = (
                "\n".join(
                    current
                )
                .strip()
            )

            if section:
                sections.append(
                    section
                )

            current = [
                line
            ]

        else:
            current.append(
                line
            )

    if current:

        section = (
            "\n".join(
                current
            )
            .strip()
        )

        if section:
            sections.append(
                section
            )

    return sections


def _chunk_catalog(
    content: str,
    *,
    max_chars: int,
) -> list[str]:

    sections = (
        _split_markdown_sections(
            content
        )
    )

    chunks: list[str] = []

    for section in sections:

        # Keep a complete catalog section atomic whenever
        # it fits inside the configured chunk size.
        if len(section) <= max_chars:

            chunks.append(
                section
            )

            continue

        # Defensive fallback for unexpectedly large sections.
        chunks.extend(
            _chunk_paragraphs(
                section,
                max_chars=max_chars,
            )
        )

    return chunks


def chunk_document(
    document: KnowledgeDocument,
    *,
    max_chars: int = 800,
) -> list[KnowledgeChunk]:

    if document.category == "catalog":

        chunks = (
            _chunk_catalog(
                document.content,
                max_chars=max_chars,
            )
        )

    else:

        # Preserve the existing behavior for policies,
        # hospital_info, services, etc.
        chunks = (
            _chunk_paragraphs(
                document.content,
                max_chars=max_chars,
            )
        )

    results: list[
        KnowledgeChunk
    ] = []

    for index, content in enumerate(
        chunks
    ):

        results.append(
            KnowledgeChunk(
                chunk_id=(
                    f"{document.document_id}:"
                    f"chunk-{index}"
                ),

                document_id=
                    document.document_id,

                tenant_id=
                    document.tenant_id,

                title=
                    document.title,

                category=
                    document.category,

                language=
                    document.language,

                source=
                    document.source,

                source_url=
                    document.source_url,

                source_type=
                    document.source_type,

                retrieved_at=
                    document.retrieved_at,

                chunk_index=
                    index,

                content=
                    content,

                tags=
                    list(
                        document.tags
                    ),
            )
        )

    return results