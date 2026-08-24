from __future__ import annotations

from types import SimpleNamespace

import pytest

import rag.retriever as retriever_module

from rag.retriever import (
    retrieve_chunks,
)


class FakeVector:

    def tolist(
        self,
    ) -> list[float]:

        return [
            0.1,
            0.2,
            0.3,
        ]


class FakeQdrantClient:

    def __init__(
        self,
    ) -> None:

        self.query_filter = None

    def query_points(
        self,
        **kwargs,
    ):

        self.query_filter = (
            kwargs["query_filter"]
        )

        # Simulate a bad / compromised retrieval result:
        # caller requested clinic-001 but Qdrant returns
        # a hospital-001 chunk.
        return SimpleNamespace(
            points=[
                SimpleNamespace(
                    score=0.95,

                    payload={
                        "chunk_id":
                            "hospital-chunk-001",

                        "tenant_id":
                            "hospital-001",

                        "title":
                            "Hospital Information",

                        "category":
                            "hospital_info",

                        "content":
                            "Hospital-only content.",

                        "source_url":
                            "https://example.com",
                    },
                )
            ]
        )


def test_rag_retrieval_is_fail_closed_across_tenants(
    monkeypatch,
) -> None:

    fake_client = (
        FakeQdrantClient()
    )

    monkeypatch.setattr(
        retriever_module,
        "embed_text",
        lambda query: FakeVector(),
    )

    monkeypatch.setattr(
        retriever_module,
        "get_qdrant_client",
        lambda: fake_client,
    )

    with pytest.raises(
        RuntimeError,
        match="Cross-tenant retrieval detected",
    ):

        retrieve_chunks(
            tenant_id=
                "clinic-001",

            query=
                "Tell me about the clinic.",
        )

    # Verify that Qdrant itself was also asked
    # to filter by the requested tenant.
    filter_data = (
        fake_client
        .query_filter
        .model_dump()
    )

    must_conditions = (
        filter_data["must"]
    )

    assert (
        must_conditions[0]["key"]
        == "tenant_id"
    )

    assert (
        must_conditions[0]["match"]["value"]
        == "clinic-001"
    )