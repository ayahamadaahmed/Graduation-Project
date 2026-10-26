from __future__ import annotations

from types import SimpleNamespace

import rag.vector_store as vector_store_module

from rag.models import (
    KnowledgeChunk,
)

from rag.vector_store import (
    _point_id,
    sync_tenant_chunks,
)


class FakeQdrantClient:

    def __init__(
        self,
        *,
        existing_ids: list[str],
    ) -> None:

        self.existing_ids = (
            existing_ids
        )

        self.deleted_selector = None
        self.scroll_filter = None

    def scroll(
        self,
        **kwargs,
    ):

        self.scroll_filter = (
            kwargs["scroll_filter"]
        )

        points = [
            # Real Qdrant records carry a payload when
            # with_payload=True; these old points have no
            # content_hash, so their chunks are re-upserted.
            SimpleNamespace(
                id=point_id,
                payload={},
            )
            for point_id
            in self.existing_ids
        ]

        return (
            points,
            None,
        )

    def delete(
        self,
        **kwargs,
    ) -> None:

        self.deleted_selector = (
            kwargs["points_selector"]
        )


def test_sync_tenant_chunks_deletes_only_stale_points(
    monkeypatch,
) -> None:

    current_chunk = KnowledgeChunk(
        chunk_id=(
            "clinic-001:"
            "services:"
            "dermatology_services:"
            "chunk-0"
        ),

        document_id=(
            "clinic-001:"
            "services:"
            "dermatology_services"
        ),

        tenant_id=
            "clinic-001",

        title=
            "Dermatology Services",

        category=
            "services",

        language=
            "en",

        source=(
            "clinic-001/services/"
            "dermatology_services.md"
        ),

        chunk_index=0,

        content=(
            "Dr. Maher provides "
            "dermatology services."
        ),

        tags=[],
    )

    current_point_id = (
        _point_id(
            current_chunk.chunk_id
        )
    )

    stale_point_id = (
        _point_id(
            "clinic-001:"
            "old_document:"
            "chunk-0"
        )
    )

    fake_client = (
        FakeQdrantClient(
            existing_ids=[
                current_point_id,
                stale_point_id,
            ]
        )
    )

    monkeypatch.setattr(
        vector_store_module,
        "get_qdrant_client",
        lambda: fake_client,
    )

    monkeypatch.setattr(
        vector_store_module,
        "upsert_chunks",
        lambda chunks: len(
            chunks
        ),
    )

    upserted, deleted = (
        sync_tenant_chunks(
            tenant_id=
                "clinic-001",

            chunks=[
                current_chunk
            ],
        )
    )

    assert upserted == 1
    assert deleted == 1

    assert (
        fake_client.deleted_selector
        is not None
    )

    deleted_ids = (
        fake_client
        .deleted_selector
        .points
    )

    assert deleted_ids == [
        stale_point_id
    ]

    filter_data = (
        fake_client
        .scroll_filter
        .model_dump()
    )

    assert (
        filter_data["must"][0]["key"]
        == "tenant_id"
    )

    assert (
        filter_data["must"][0]
        ["match"]["value"]
        == "clinic-001"
    )