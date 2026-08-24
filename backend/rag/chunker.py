from __future__ import annotations

from rag.models import (
    KnowledgeChunk,
    KnowledgeDocument,
)


def chunk_document(
    document: KnowledgeDocument,
    *,
    max_chars: int = 800,
) -> list[KnowledgeChunk]:

    paragraphs = [
        paragraph.strip()
        for paragraph in document.content.split("\n\n")
        if paragraph.strip()
    ]

    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    for paragraph in paragraphs:

        paragraph_length = len(paragraph)

        if (
            current
            and
            current_length
            + paragraph_length
            + 2
            > max_chars
        ):
            chunks.append(
                "\n\n".join(current)
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
            "\n\n".join(current)
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