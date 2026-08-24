from __future__ import annotations

from functools import lru_cache
from uuid import (
    NAMESPACE_URL,
    uuid5,
)

from qdrant_client import (
    QdrantClient,
)

from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
    PointIdsList,
    PointStruct,
)

from rag.embeddings import (
    embed_texts,
)

from rag.models import (
    KnowledgeChunk,
)


QDRANT_URL = (
    "http://127.0.0.1:6333"
)

COLLECTION_NAME = (
    "medmind_knowledge"
)


@lru_cache(
    maxsize=1
)
def get_qdrant_client() -> QdrantClient:

    return QdrantClient(
        url=QDRANT_URL
    )


def _point_id(
    chunk_id: str,
) -> str:

    return str(
        uuid5(
            NAMESPACE_URL,
            chunk_id,
        )
    )


def _build_payload(
    chunk: KnowledgeChunk,
) -> dict:

    return {
        "chunk_id":
            chunk.chunk_id,

        "document_id":
            chunk.document_id,

        "tenant_id":
            chunk.tenant_id,

        "title":
            chunk.title,

        "category":
            chunk.category,

        "language":
            chunk.language,

        "source":
            chunk.source,

        "source_url":
            chunk.source_url,

        "source_type":
            chunk.source_type,

        "retrieved_at": (
            chunk.retrieved_at.isoformat()
            if chunk.retrieved_at
            else None
        ),

        "chunk_index":
            chunk.chunk_index,

        "content":
            chunk.content,

        "tags":
            list(
                chunk.tags
            ),
    }


def upsert_chunks(
    chunks: list[
        KnowledgeChunk
    ],
) -> int:

    if not chunks:
        return 0

    texts = [
        chunk.content
        for chunk in chunks
    ]

    vectors = (
        embed_texts(
            texts
        )
    )

    points = []

    for chunk, vector in zip(
        chunks,
        vectors,
        strict=True,
    ):

        points.append(
            PointStruct(
                id=_point_id(
                    chunk.chunk_id
                ),

                vector=(
                    vector.tolist()
                ),

                payload=(
                    _build_payload(
                        chunk
                    )
                ),
            )
        )

    client = (
        get_qdrant_client()
    )

    client.upsert(
        collection_name=
            COLLECTION_NAME,

        points=
            points,

        wait=True,
    )

    return len(
        points
    )


def sync_tenant_chunks(
    *,
    tenant_id: str,
    chunks: list[
        KnowledgeChunk
    ],
) -> tuple[int, int]:
    """
    Synchronize one tenant's Qdrant snapshot.

    Returns:
        (
            upserted_count,
            stale_deleted_count,
        )

    Current chunks are upserted first.

    Only after a successful upsert are stale
    points removed. This avoids deleting the
    tenant knowledge before the new snapshot
    has been stored.
    """

    if not tenant_id.strip():

        raise ValueError(
            "tenant_id is required."
        )

    for chunk in chunks:

        if (
            chunk.tenant_id
            != tenant_id
        ):

            raise ValueError(
                "Chunk tenant_id does not "
                "match sync tenant_id."
            )

    client = (
        get_qdrant_client()
    )

    # --------------------------------------------------------
    # Existing tenant point IDs
    # --------------------------------------------------------

    existing_point_ids: set[
        str
    ] = set()

    offset = None

    while True:

        points, next_offset = (
            client.scroll(
                collection_name=
                    COLLECTION_NAME,

                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key=
                                "tenant_id",

                            match=MatchValue(
                                value=
                                    tenant_id,
                            ),
                        )
                    ]
                ),

                limit=256,

                offset=
                    offset,

                with_payload=False,

                with_vectors=False,
            )
        )

        for point in points:

            existing_point_ids.add(
                str(
                    point.id
                )
            )

        if next_offset is None:
            break

        offset = (
            next_offset
        )

    # --------------------------------------------------------
    # IDs expected from the current filesystem snapshot
    # --------------------------------------------------------

    current_point_ids = {
        _point_id(
            chunk.chunk_id
        )
        for chunk in chunks
    }

    # --------------------------------------------------------
    # Upsert current snapshot FIRST
    # --------------------------------------------------------

    upserted_count = (
        upsert_chunks(
            chunks
        )
    )

    # --------------------------------------------------------
    # Remove stale points
    # --------------------------------------------------------

    stale_point_ids = sorted(
        existing_point_ids
        -
        current_point_ids
    )

    if stale_point_ids:

        client.delete(
            collection_name=
                COLLECTION_NAME,

            points_selector=PointIdsList(
                points=
                    stale_point_ids,
            ),

            wait=True,
        )

    return (
        upserted_count,
        len(
            stale_point_ids
        ),
    )