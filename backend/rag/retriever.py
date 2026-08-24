from __future__ import annotations

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


def retrieve_chunks(
    *,
    tenant_id: str,
    query: str,
    limit: int = 3,
) -> list[dict]:

    if not tenant_id.strip():
        raise ValueError(
            "tenant_id is required."
        )

    if not query.strip():
        raise ValueError(
            "query is required."
        )

    query_vector = (
        embed_text(
            query
        )
    )

    client = (
        get_qdrant_client()
    )

    response = (
        client.query_points(
            collection_name=
                COLLECTION_NAME,

            query=
                query_vector.tolist(),

            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="tenant_id",

                        match=MatchValue(
                            value=
                                tenant_id,
                        ),
                    )
                ]
            ),

            limit=
                limit,

            with_payload=True,

            with_vectors=False,
        )
    )

    results: list[dict] = []

    for point in response.points:

        payload = (
            point.payload
            or {}
        )

        # Fail closed:
        # never accept another tenant.
        if (
            payload.get(
                "tenant_id"
            )
            !=
            tenant_id
        ):
            raise RuntimeError(
                "Cross-tenant retrieval detected."
            )

        results.append(
            {
                "score":
                    float(
                        point.score
                    ),

                "chunk_id":
                    payload.get(
                        "chunk_id"
                    ),

                "tenant_id":
                    payload.get(
                        "tenant_id"
                    ),

                "title":
                    payload.get(
                        "title"
                    ),

                "category":
                    payload.get(
                        "category"
                    ),

                "content":
                    payload.get(
                        "content"
                    ),

                "source_url":
                    payload.get(
                        "source_url"
                    ),
            }
        )

    return results