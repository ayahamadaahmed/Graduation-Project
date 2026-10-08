from __future__ import annotations

import logging
import time

from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
)

from rag.embeddings import (
    embed_text,
)

from rag.vector_store import (
    COLLECTION_NAME,
    get_qdrant_client,
)


logger = logging.getLogger("uvicorn.error")


def retrieve_chunks(
    *,
    tenant_id: str,
    query: str,
    limit: int = 3,
) -> list[dict]:

    total_started = time.perf_counter()

    if not tenant_id.strip():
        raise ValueError(
            "tenant_id is required."
        )

    if not query.strip():
        raise ValueError(
            "query is required."
        )

    embedding_started = time.perf_counter()

    query_vector = embed_text(
        query
    )

    embedding_ms = (
        time.perf_counter()
        - embedding_started
    ) * 1000

    client_started = time.perf_counter()

    client = get_qdrant_client()

    client_ms = (
        time.perf_counter()
        - client_started
    ) * 1000

    qdrant_started = time.perf_counter()

    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector.tolist(),
        query_filter=Filter(
            must=[
                FieldCondition(
                    key="tenant_id",
                    match=MatchValue(
                        value=tenant_id,
                    ),
                )
            ]
        ),
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )

    qdrant_ms = (
        time.perf_counter()
        - qdrant_started
    ) * 1000

    parse_started = time.perf_counter()

    results: list[dict] = []

    for point in response.points:

        payload = (
            point.payload
            or {}
        )

        if payload.get("tenant_id") != tenant_id:
            raise RuntimeError(
                "Cross-tenant retrieval detected."
            )

        results.append(
            {
                "score": float(point.score),
                "chunk_id": payload.get("chunk_id"),
                "tenant_id": payload.get("tenant_id"),
                "title": payload.get("title"),
                "category": payload.get("category"),
                "content": payload.get("content"),
                "source_url": payload.get("source_url"),
            }
        )

    parse_ms = (
        time.perf_counter()
        - parse_started
    ) * 1000

    total_ms = (
        time.perf_counter()
        - total_started
    ) * 1000

    logger.info(
        "rag_retriever_timing "
        "tenant_id=%s "
        "limit=%d "
        "embedding_ms=%.2f "
        "client_ms=%.2f "
        "qdrant_ms=%.2f "
        "parse_ms=%.2f "
        "total_ms=%.2f "
        "result_count=%d",
        tenant_id,
        limit,
        embedding_ms,
        client_ms,
        qdrant_ms,
        parse_ms,
        total_ms,
        len(results),
    )

    return results