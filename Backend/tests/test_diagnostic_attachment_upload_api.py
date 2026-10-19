from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security.service_auth import (
    ServiceContext,
    require_trusted_service,
)

from app.api.dependencies import (
    get_current_provider,
    get_diagnostic_attachment_service,
    get_diagnostic_attachment_binding_service,
)

from app.services.diagnostic_attachment_binding_service import (
    DiagnosticEncounterNotFoundError,
    DiagnosticEncounterRequiresPatientError,
    DiagnosticPatientNotFoundError,
    DiagnosticPatientProviderMismatchError,
)


# ============================================================
# TEST STATE
# ============================================================


@pytest.fixture(autouse=True)
def clear_dependency_overrides():

    app.dependency_overrides.clear()

    old_sessions = getattr(app.state, "ai_chat_session_registry", None)

    yield

    app.dependency_overrides.clear()

    if old_sessions is None:
        if hasattr(app.state, "ai_chat_session_registry"):
            delattr(app.state, "ai_chat_session_registry")
    else:
        app.state.ai_chat_session_registry = old_sessions


class OwnedSessionRegistry:
    """These tests are about binding: "session-1" is a live session owned by
    the test gateway. Real ownership checks are in
    tests/test_diagnostic_attachment_session_ownership.py."""

    def resolve(self, *, session_id, provider_id, service_name, channel):
        return object() if session_id == "session-1" else None


# ============================================================
# FAKES
# ============================================================


class FakeAttachmentService:

    max_upload_bytes = 1024 * 1024

    def __init__(self):
        self.calls = []

    def store(
        self,
        *,
        provider_id,
        session_id,
        original_filename,
        content_type,
        data,
        patient_id=None,
        encounter_id=None,
    ):

        self.calls.append(
            {
                "provider_id":
                    provider_id,
                "session_id":
                    session_id,
                "original_filename":
                    original_filename,
                "content_type":
                    content_type,
                "data":
                    data,
                "patient_id":
                    patient_id,
                "encounter_id":
                    encounter_id,
            }
        )

        return SimpleNamespace(
            attachment_id="a" * 32,
            content_type=content_type,
            size_bytes=len(data),
        )


class FakeBindingService:

    def __init__(
        self,
        *,
        error=None,
    ):
        self.error = error
        self.calls = []

    def resolve(
        self,
        *,
        provider_id,
        patient_id=None,
        national_id=None,
        encounter_id=None,
    ):

        self.calls.append(
            {
                "provider_id":
                    provider_id,
                "patient_id":
                    patient_id,
                "encounter_id":
                    encounter_id,
            }
        )

        if self.error is not None:
            raise self.error

        return SimpleNamespace(
            patient_id=patient_id,
            encounter_id=encounter_id,
        )


# ============================================================
# HELPERS
# ============================================================


def make_client(
    *,
    binding_service=None,
):

    provider = SimpleNamespace(
        id=uuid4(),
        tenant_key="clinic-001",
    )

    attachment_service = (
        FakeAttachmentService()
    )

    if binding_service is None:
        binding_service = (
            FakeBindingService()
        )

    app.dependency_overrides[
        get_current_provider
    ] = lambda: provider

    # Uploads require a trusted gateway allowed for this tenant + an owned session.
    app.dependency_overrides[
        require_trusted_service
    ] = lambda: ServiceContext(
        name="test_gateway",
        allowed_tenants=frozenset({"clinic-001"}),
    )

    app.state.ai_chat_session_registry = OwnedSessionRegistry()

    app.dependency_overrides[
        get_diagnostic_attachment_service
    ] = lambda: attachment_service

    app.dependency_overrides[
        get_diagnostic_attachment_binding_service
    ] = lambda: binding_service

    return (
        TestClient(app),
        provider,
        attachment_service,
        binding_service,
    )


def upload(
    client,
    *,
    patient_id=None,
    encounter_id=None,
):

    data = {
        "session_id":
            "session-1",
    }

    if patient_id is not None:
        data["patient_id"] = str(
            patient_id
        )

    if encounter_id is not None:
        data["encounter_id"] = str(
            encounter_id
        )

    return client.post(
        "/api/v1/diagnostics/attachments",
        headers={
            "X-Tenant-ID":
                "clinic-001",
        },
        data=data,
        files={
            "file": (
                "xray.jpg",
                b"fake-image-data",
                "image/jpeg",
            )
        },
    )


# ============================================================
# EXISTING UNBOUND BEHAVIOR
# ============================================================


def test_unbound_upload_still_works():

    (
        client,
        _,
        attachment_service,
        _,
    ) = make_client()

    response = upload(
        client
    )

    assert (
        response.status_code
        == 201
    )

    assert (
        response.json()
        ["attachment_id"]
        == "a" * 32
    )

    call = (
        attachment_service.calls[0]
    )

    assert (
        call["patient_id"]
        is None
    )

    assert (
        call["encounter_id"]
        is None
    )


# ============================================================
# PATIENT BINDING
# ============================================================


def test_valid_patient_binding_is_stored():

    (
        client,
        provider,
        attachment_service,
        binding_service,
    ) = make_client()

    patient_id = uuid4()

    response = upload(
        client,
        patient_id=patient_id,
    )

    assert (
        response.status_code
        == 201
    )

    assert (
        binding_service.calls
        == [
            {
                "provider_id":
                    provider.id,
                "patient_id":
                    patient_id,
                "encounter_id":
                    None,
            }
        ]
    )

    call = (
        attachment_service.calls[0]
    )

    assert (
        call["patient_id"]
        == patient_id
    )

    assert (
        call["encounter_id"]
        is None
    )


# ============================================================
# PATIENT + ENCOUNTER
# ============================================================


def test_valid_patient_and_encounter_are_stored():

    (
        client,
        _,
        attachment_service,
        _,
    ) = make_client()

    patient_id = uuid4()
    encounter_id = uuid4()

    response = upload(
        client,
        patient_id=patient_id,
        encounter_id=encounter_id,
    )

    assert (
        response.status_code
        == 201
    )

    call = (
        attachment_service.calls[0]
    )

    assert (
        call["patient_id"]
        == patient_id
    )

    assert (
        call["encounter_id"]
        == encounter_id
    )


# ============================================================
# ENCOUNTER WITHOUT PATIENT
# ============================================================


def test_encounter_without_patient_is_rejected():

    binding_service = FakeBindingService(
        error=(
            DiagnosticEncounterRequiresPatientError(
                "patient required"
            )
        )
    )

    (
        client,
        _,
        attachment_service,
        _,
    ) = make_client(
        binding_service=binding_service
    )

    response = upload(
        client,
        encounter_id=uuid4(),
    )

    assert (
        response.status_code
        == 400
    )

    assert (
        response.json()
        ["detail"]
        ["code"]
        == "DIAGNOSTIC_PATIENT_REQUIRED"
    )

    assert (
        attachment_service.calls
        == []
    )


# ============================================================
# PATIENT NOT FOUND / WRONG PROVIDER
# ============================================================


@pytest.mark.parametrize(
    "error",
    [
        DiagnosticPatientNotFoundError(
            "patient not found"
        ),
        DiagnosticPatientProviderMismatchError(
            "wrong provider"
        ),
    ],
)
def test_invalid_patient_binding_is_hidden_as_not_found(
    error,
):

    binding_service = FakeBindingService(
        error=error
    )

    (
        client,
        _,
        attachment_service,
        _,
    ) = make_client(
        binding_service=binding_service
    )

    response = upload(
        client,
        patient_id=uuid4(),
    )

    assert (
        response.status_code
        == 404
    )

    assert (
        response.json()
        ["detail"]
        ["code"]
        == "DIAGNOSTIC_PATIENT_NOT_FOUND"
    )

    assert (
        attachment_service.calls
        == []
    )


# ============================================================
# ENCOUNTER MISMATCH
# ============================================================


def test_invalid_encounter_binding_is_rejected():

    binding_service = FakeBindingService(
        error=(
            DiagnosticEncounterNotFoundError(
                "encounter not found"
            )
        )
    )

    (
        client,
        _,
        attachment_service,
        _,
    ) = make_client(
        binding_service=binding_service
    )

    response = upload(
        client,
        patient_id=uuid4(),
        encounter_id=uuid4(),
    )

    assert (
        response.status_code
        == 404
    )

    assert (
        response.json()
        ["detail"]
        ["code"]
        == "DIAGNOSTIC_ENCOUNTER_NOT_FOUND"
    )

    assert (
        attachment_service.calls
        == []
    )