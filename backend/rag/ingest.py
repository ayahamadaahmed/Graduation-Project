from __future__ import annotations

from pathlib import Path

from rag.chunker import (
    chunk_document,
)

from rag.loader import (
    load_tenant_documents,
)

from rag.vector_store import (
    COLLECTION_NAME,
    get_qdrant_client,
    sync_tenant_chunks,
)


KNOWLEDGE_ROOT = Path(
    "knowledge_base"
)

TENANTS = [
    "clinic-001",
    "hospital-001",
    "lab-001",
]


def main() -> None:

    total_upserted = 0
    total_deleted = 0

    for tenant_id in TENANTS:

        documents = (
            load_tenant_documents(
                knowledge_root=
                    KNOWLEDGE_ROOT,

                tenant_id=
                    tenant_id,
            )
        )

        tenant_chunks = []

        for document in documents:

            chunks = (
                chunk_document(
                    document,
                    max_chars=500,
                )
            )

            tenant_chunks.extend(
                chunks
            )

        upserted, deleted = (
            sync_tenant_chunks(
                tenant_id=
                    tenant_id,

                chunks=
                    tenant_chunks,
            )
        )

        total_upserted += (
            upserted
        )

        total_deleted += (
            deleted
        )

        print(
            tenant_id,
            "documents=",
            len(documents),
            "chunks=",
            len(tenant_chunks),
            "upserted=",
            upserted,
            "stale_deleted=",
            deleted,
        )

    client = (
        get_qdrant_client()
    )

    info = (
        client.get_collection(
            COLLECTION_NAME
        )
    )

    print()

    print(
        "TOTAL UPSERTED:",
        total_upserted,
    )

    print(
        "TOTAL STALE DELETED:",
        total_deleted,
    )

    print(
        "POINTS COUNT:",
        info.points_count,
    )


if __name__ == "__main__":
    main()