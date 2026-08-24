from __future__ import annotations

from functools import lru_cache

from rag.service import (
    RAGAnswer,
    RAGService,
    create_rag_service,
)


@lru_cache(maxsize=1)
def get_rag_service() -> RAGService:
    """
    Create one reusable RAG service instance
    for the current backend process.
    """

    return create_rag_service()


async def answer_provider_knowledge(
    *,
    tenant_id: str,
    query: str,
    language: str,
) -> RAGAnswer:
    """
    Answer provider knowledge questions using
    tenant-isolated RAG retrieval.

    This function does NOT handle:
    - appointment booking
    - availability
    - cancellation
    - rescheduling
    - patient-specific information

    Those remain handled by MedMind workflows
    and MCP/backend APIs.
    """

    if not tenant_id.strip():
        raise ValueError(
            "tenant_id is required."
        )

    if not query.strip():
        raise ValueError(
            "query is required."
        )

    return await get_rag_service().answer(
        tenant_id=tenant_id,
        query=query,
        language=language,
    )