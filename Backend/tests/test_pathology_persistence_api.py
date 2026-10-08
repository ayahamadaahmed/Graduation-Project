from types import SimpleNamespace
from uuid import uuid4

import pytest

from fastapi.testclient import (
    TestClient,
)

from app.main import app

from app.api.dependencies import (
    get_current_provider,
    get_pathology_persistence_adapter,
)

from app.services.diagnostic_attachment_service import (
    DiagnosticAttachmentNotFoundError,
)

from app.services.lab_persistence_service import (
    LabPersistenceError,
)

from app.services.pathology_persistence_adapter import (
    DuplicatePathologyPersistenceError,
)


# ============================================================
# TEST HELPERS
# ============================================================


@pytest.fixture(
    autouse=True,
)
def clear_dependency_overrides():

    app.dependency_overrides.clear()

    yield

    app.dependency_overrides.clear()


def make_payload():

    return {
        "schema_version": "1.0",
        "attachment_id": (
            "a" * 32
        ),
        "document_type": "cbc",
        "unreadable_fields": [],
        "results": [
            {
                "result_index": 0,
                "panel": "cbc",
                "raw_name": "HGB",
                "canonical_name": (
                    "hemoglobin"
                ),
                "value": "10.0",
                "unit": "g/dL",
                "reference_min": "12",
                "reference_max": "16",
                "reference_text": (
                    "12 - 16"
                ),
                "flag": "low",
                "mapping_status": (
                    "mapped"
                ),
            }
        ],
    }


class FakePathologyAdapter:

    def __init__(
        self,
        *,
        error=None,
    ) -> None:

        self.error = error

        self.calls = []

        self.report_id = uuid4()

    def persist(
        self,
        *,
        provider_id,
        request,
    ):

        self.calls.append(
            {
                "provider_id": (
                    provider_id
                ),
                "request": request,
            }
        )

        if self.error is not None:
            raise self.error

        return SimpleNamespace(
            id=self.report_id,
            status="processed",
        )


def make_client(
    adapter,
):

    provider = SimpleNamespace(
        id=uuid4(),
        tenant_key="lab-001",
    )

    app.dependency_overrides[
        get_current_provider
    ] = lambda: provider

    app.dependency_overrides[
        get_pathology_persistence_adapter
    ] = lambda: adapter

    return (
        TestClient(app),
        provider,
    )


# ============================================================
# 201
# ============================================================


def test_pathology_results_returns_201():

    adapter = FakePathologyAdapter()

    client, provider = make_client(
        adapter
    )

    response = client.post(
        "/api/v1/diagnostics/pathology-results",
        json=make_payload(),
    )

    assert (
        response.status_code
        == 201
    )

    body = response.json()

    assert (
        body["attachment_id"]
        == "a" * 32
    )

    assert (
        body["lab_report_id"]
        == str(
            adapter.report_id
        )
    )

    assert (
        body["status"]
        == "processed"
    )

    assert (
        body["result_count"]
        == 1
    )

    assert len(
        adapter.calls
    ) == 1

    assert (
        adapter.calls[0][
            "provider_id"
        ]
        == provider.id
    )


# ============================================================
# 404
# ============================================================


def test_pathology_results_returns_404_when_attachment_missing():

    adapter = FakePathologyAdapter(
        error=(
            DiagnosticAttachmentNotFoundError(
                "not found"
            )
        )
    )

    client, _ = make_client(
        adapter
    )

    response = client.post(
        "/api/v1/diagnostics/pathology-results",
        json=make_payload(),
    )

    assert (
        response.status_code
        == 404
    )

    assert (
        response.json()[
            "detail"
        ]["code"]
        == (
            "DIAGNOSTIC_ATTACHMENT_NOT_FOUND"
        )
    )


# ============================================================
# 409
# ============================================================


def test_pathology_results_returns_409_for_duplicate():

    adapter = FakePathologyAdapter(
        error=(
            DuplicatePathologyPersistenceError(
                "duplicate"
            )
        )
    )

    client, _ = make_client(
        adapter
    )

    response = client.post(
        "/api/v1/diagnostics/pathology-results",
        json=make_payload(),
    )

    assert (
        response.status_code
        == 409
    )

    assert (
        response.json()[
            "detail"
        ]["code"]
        == (
            "PATHOLOGY_REPORT_ALREADY_EXISTS"
        )
    )


# ============================================================
# 503
# ============================================================


def test_pathology_results_returns_503_on_persistence_failure():

    adapter = FakePathologyAdapter(
        error=(
            LabPersistenceError(
                "database failure"
            )
        )
    )

    client, _ = make_client(
        adapter
    )

    response = client.post(
        "/api/v1/diagnostics/pathology-results",
        json=make_payload(),
    )

    assert (
        response.status_code
        == 503
    )

    assert (
        response.json()[
            "detail"
        ]["code"]
        == (
            "PATHOLOGY_PERSISTENCE_FAILED"
        )
    )