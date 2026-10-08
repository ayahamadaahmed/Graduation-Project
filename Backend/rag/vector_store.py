from __future__ import annotations
import os
from functools import lru_cache
from uuid import (
    NAMESPACE_URL,
    uuid5,
)
from hashlib import (
    sha256,
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


QDRANT_URL = os.getenv(
    "QDRANT_URL",
    "http://127.0.0.1:6333",
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

def _content_hash(
    content: str,
) -> str:

    return sha256(
        content.encode(
            "utf-8"
        )
    ).hexdigest()

def _build_payload(
    chunk: KnowledgeChunk,
) -> dict:

    return {
        "chunk_id":
            chunk.chunk_id,

        "content_hash":
            _content_hash(
                chunk.content
            ),

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
    Incrementally synchronize one tenant's
    Qdrant knowledge snapshot.

    Behavior:
    - unchanged chunk -> skip
    - new chunk       -> embed + upsert
    - changed chunk   -> embed + upsert
    - deleted chunk   -> delete

    Returns:
        (
            upserted_count,
            stale_deleted_count,
        )
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
    # Existing tenant snapshot
    # --------------------------------------------------------

    existing_hashes: dict[
        str,
        str | None,
    ] = {}

    offset = None

    while True:

        points, next_offset = (
            client.scroll(
                collection_name=
                    COLLECTION_NAME,

                scroll_filter=Filter(
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

                limit=256,

                offset=
                    offset,

                with_payload=True,

                with_vectors=False,
            )
        )

        for point in points:

            point_id = str(
                point.id
            )

            payload = (
                point.payload
                or {}
            )

            existing_hashes[
                point_id
            ] = payload.get(
                "content_hash"
            )

        if next_offset is None:
            break

        offset = (
            next_offset
        )

    existing_point_ids = set(
        existing_hashes
    )

    # --------------------------------------------------------
    # Current filesystem snapshot
    # --------------------------------------------------------

    current_point_ids: set[
        str
    ] = set()

    chunks_to_upsert: list[
        KnowledgeChunk
    ] = []

    for chunk in chunks:

        point_id = _point_id(
            chunk.chunk_id
        )

        current_point_ids.add(
            point_id
        )

        current_hash = (
            _content_hash(
                chunk.content
            )
        )

        existing_hash = (
            existing_hashes.get(
                point_id
            )
        )

        # New point, changed content,
        # or old point without content_hash.
        if (
            existing_hash
            != current_hash
        ):

            chunks_to_upsert.append(
                chunk
            )

    # --------------------------------------------------------
    # Upsert only new / changed chunks FIRST
    # --------------------------------------------------------

    upserted_count = (
        upsert_chunks(
            chunks_to_upsert
        )
    )

    # --------------------------------------------------------
    # Delete stale points
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

            points_selector=
                PointIdsList(
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