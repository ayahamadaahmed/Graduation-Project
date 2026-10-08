from types import SimpleNamespace
from uuid import uuid4

import pytest

from fastapi.testclient import (
    TestClient,
)

from app.main import app

from app.api.dependencies import (
    get_current_provider,
    get_radiology_persistence_adapter,
)

from app.services.diagnostic_attachment_service import (
    DiagnosticAttachmentNotFoundError,
)

from app.services.radiology_persistence_service import (
    RadiologyPersistenceError,
)

from app.services.radiology_persistence_adapter import (
    DuplicateRadiologyPersistenceError,
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

        "modality": (
            "chest_xray"
        ),

        "classification": (
            "normal"
        ),

        "probabilities": {
            "normal": "0.7836",
            "pneumonia": "0.2164",
        },

        "confidence": (
            "0.7836"
        ),

        "inference_latency_ms": (
            "271.400"
        ),

        "model_name": (
            "medmind_chest_xray"
        ),

        "model_version": (
            "1.0"
        ),

        "limitations": [
            (
                "Decision-support "
                "classification only."
            ),
        ],
    }


class FakeRadiologyAdapter:

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
                "provider_id":
                    provider_id,

                "request":
                    request,
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
        get_radiology_persistence_adapter
    ] = lambda: adapter

    return (
        TestClient(app),
        provider,
    )


# ============================================================
# 201
# ============================================================


def test_radiology_results_returns_201():

    adapter = (
        FakeRadiologyAdapter()
    )

    client, provider = (
        make_client(
            adapter
        )
    )

    response = client.post(
        (
            "/api/v1/diagnostics/"
            "radiology-results"
        ),
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
        body["radiology_report_id"]
        == str(
            adapter.report_id
        )
    )

    assert (
        body["status"]
        == "processed"
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

    request = (
        adapter.calls[0][
            "request"
        ]
    )

    assert (
        request.modality
        == "chest_xray"
    )

    assert (
        request.classification
        == "normal"
    )


# ============================================================
# 404
# ============================================================


def test_radiology_results_returns_404_when_attachment_missing():

    adapter = FakeRadiologyAdapter(
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
        (
            "/api/v1/diagnostics/"
            "radiology-results"
        ),
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


def test_radiology_results_returns_409_for_duplicate():

    adapter = FakeRadiologyAdapter(
        error=(
            DuplicateRadiologyPersistenceError(
                "duplicate"
            )
        )
    )

    client, _ = make_client(
        adapter
    )

    response = client.post(
        (
            "/api/v1/diagnostics/"
            "radiology-results"
        ),
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
            "RADIOLOGY_REPORT_ALREADY_EXISTS"
        )
    )


# ============================================================
# 503
# ============================================================


def test_radiology_results_returns_503_on_persistence_failure():

    adapter = FakeRadiologyAdapter(
        error=(
            RadiologyPersistenceError(
                "database failure"
            )
        )
    )

    client, _ = make_client(
        adapter
    )

    response = client.post(
        (
            "/api/v1/diagnostics/"
            "radiology-results"
        ),
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
            "RADIOLOGY_PERSISTENCE_FAILED"
        )
    )