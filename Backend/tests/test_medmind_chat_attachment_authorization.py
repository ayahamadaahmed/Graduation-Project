from types import SimpleNamespace
from uuid import uuid4

import pytest
from decimal import Decimal
from fastapi.testclient import (
    TestClient,
)

from app.main import app

from app.api.dependencies import (
    get_current_provider,
    get_diagnostic_attachment_service,
    get_pathology_persistence_adapter,
    get_radiology_persistence_adapter,
)

import app.api.routers.medmind_ai as medmind_router

from app.services.diagnostic_attachment_service import (
    DiagnosticAttachmentNotFoundError,
    InvalidDiagnosticAttachmentError,
)

class FakeRadiologyPersistenceAdapter:

    def __init__(
        self,
    ):
        self.calls = []

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

        return SimpleNamespace(
            id=uuid4()
        )


class FakePathologyPersistenceAdapter:

    def __init__(
        self,
    ):
        self.calls = []

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

        return SimpleNamespace(
            id=uuid4()
        )
# ============================================================
# TEST HELPERS
# ============================================================


@pytest.fixture(
    autouse=True,
)
def clear_test_state():

    app.dependency_overrides.clear()

    old_registry = getattr(
        app.state,
        "medmind_registry",
        None,
    )

    yield

    app.dependency_overrides.clear()

    if old_registry is None:

        if hasattr(
            app.state,
            "medmind_registry",
        ):
            delattr(
                app.state,
                "medmind_registry",
            )

    else:

        app.state.medmind_registry = (
            old_registry
        )


# ============================================================
# FAKE ATTACHMENT SERVICE
# ============================================================


class FakeAttachmentService:

    def __init__(
        self,
        *,
        invalid_ids=None,
    ):

        self.attachments = {}

        self.paths = {}

        self.invalid_ids = (
            invalid_ids
            or set()
        )

        self.calls = []

        self.resolve_calls = []

    def get(
        self,
        *,
        provider_id,
        attachment_id,
    ):

        self.calls.append(
            {
                "provider_id":
                    provider_id,

                "attachment_id":
                    attachment_id,
            }
        )

        if (
            attachment_id
            in self.invalid_ids
        ):

            raise (
                InvalidDiagnosticAttachmentError(
                    "Invalid attachment_id."
                )
            )

        attachment = (
            self.attachments.get(
                (
                    provider_id,
                    attachment_id,
                )
            )
        )

        if attachment is None:

            raise (
                DiagnosticAttachmentNotFoundError(
                    "Diagnostic attachment "
                    "was not found."
                )
            )

        return attachment

    def resolve_path(
        self,
        *,
        provider_id,
        attachment_id,
    ):

        self.resolve_calls.append(
            {
                "provider_id":
                    provider_id,

                "attachment_id":
                    attachment_id,
            }
        )

        key = (
            provider_id,
            attachment_id,
        )

        path = self.paths.get(
            key
        )

        if path is None:

            raise (
                DiagnosticAttachmentNotFoundError(
                    "Diagnostic attachment "
                    "file was not found."
                )
            )

        return path


# ============================================================
# FAKE MEDMIND SERVICE
# ============================================================

class FakeMedMindService:

    def __init__(
        self,
    ):
        self.calls = []
        self.diagnostic_result = None
        self.diagnostic_results = {}

    async def chat(
        self,
        *,
        session_id,
        message,
        channel,
        diagnostic_mode=None,
        medical_education_hint=False,
        attachment_ids=None,
        conversation_context=None,
        trusted_attachments=None,
    ):

        self.calls.append(
            {
                "session_id":
                    session_id,

                "message":
                    message,

                "channel":
                    channel,

                "diagnostic_mode":
                    diagnostic_mode,

                "medical_education_hint":
                    medical_education_hint,

                "attachment_ids":
                    attachment_ids,

                "conversation_context":
                    conversation_context,

                "trusted_attachments":
                    trusted_attachments,
            }
        )

        attachment_id = attachment_ids[0] if attachment_ids else None
        return {
            "reply":
                "ok",

            "language":
                "en",

            "intent":
                "unknown",

            "diagnostic_result":
                self.diagnostic_results.get(attachment_id, self.diagnostic_result),

            "state": {
                "stage":
                    "idle",
            },
        }


# ============================================================
# FAKE REGISTRY
# ============================================================


class FakeRegistry:

    def __init__(
        self,
        service,
    ):

        self.service = service

        self.calls = []

    async def get(
        self,
        *,
        tenant_id,
        tenant_context=None,
    ):

        self.calls.append(
            {
                "tenant_id":
                    tenant_id,

                "tenant_context":
                    tenant_context,
            }
        )

        return self.service


# ============================================================
# CLIENT FACTORY
# ============================================================


def make_client(
    monkeypatch,
    *,
    attachment_service,
):

    provider = SimpleNamespace(
        id=uuid4(),
        tenant_key="clinic-001",
        org_type="clinic",
    )

    medmind_service = (
        FakeMedMindService()
    )

    registry = FakeRegistry(
        medmind_service
    )

    app.state.medmind_registry = (
        registry
    )

    app.dependency_overrides[
        get_current_provider
    ] = lambda: provider

    app.dependency_overrides[
        get_diagnostic_attachment_service
    ] = lambda: attachment_service

    monkeypatch.setattr(
        medmind_router,
        "build_tenant_context",
        lambda provider:
            SimpleNamespace(
                tenant_id="clinic-001",
            ),
    )

    radiology_persistence_adapter = (
        FakeRadiologyPersistenceAdapter()
    )

    pathology_persistence_adapter = (
        FakePathologyPersistenceAdapter()
    )

    medmind_service.pathology_persistence_adapter = (
        pathology_persistence_adapter
    )

    app.dependency_overrides[
        get_pathology_persistence_adapter
    ] = lambda: (
        pathology_persistence_adapter
    )

    medmind_service.radiology_persistence_adapter = (
        radiology_persistence_adapter
    )

    app.dependency_overrides[
        get_radiology_persistence_adapter
    ] = lambda: (
        radiology_persistence_adapter
    )

    return (
        TestClient(app),
        provider,
        medmind_service,
    )


# ============================================================
# REQUEST PAYLOAD
# ============================================================


def payload(
    *,
    session_id="session-1",
    attachment_id=None,
):

    data = {
        "session_id":
            session_id,

        "message":
            "Analyze this report",

        "channel":
            "web",
    }

    if attachment_id is not None:

        data[
            "attachment_ids"
        ] = [
            attachment_id
        ]

    return data


# ============================================================
# VALID ATTACHMENT
# ============================================================


def test_same_provider_and_session_reaches_medmind_service(
    monkeypatch,
    tmp_path,
):

    attachment_id = (
        "a" * 32
    )

    attachment_service = (
        FakeAttachmentService()
    )

    client, provider, medmind_service = (
        make_client(
            monkeypatch,
            attachment_service=(
                attachment_service
            ),
        )
    )

    # --------------------------------------------------------
    # Fake stored image.
    # --------------------------------------------------------

    image_path = (
        tmp_path
        / "brain.jpg"
    )

    image_path.write_bytes(
        b"fake-image-bytes"
    )

    # --------------------------------------------------------
    # Fake attachment database record.
    # --------------------------------------------------------

    attachment_service.attachments[
        (
            provider.id,
            attachment_id,
        )
    ] = SimpleNamespace(
        attachment_id=(
            attachment_id
        ),

        provider_id=(
            provider.id
        ),

        session_id=(
            "session-1"
        ),

        original_filename=(
            "brain.jpg"
        ),

        content_type=(
            "image/jpeg"
        ),

        patient_id=None,

        encounter_id=None,
    )

    # --------------------------------------------------------
    # Fake trusted storage resolution.
    # --------------------------------------------------------

    attachment_service.paths[
        (
            provider.id,
            attachment_id,
        )
    ] = image_path

    # --------------------------------------------------------
    # Request.
    # --------------------------------------------------------

    response = client.post(
        "/api/v1/ai/chat",
        headers={
            "X-Tenant-ID":
                "clinic-001",
        },
        json=payload(
            attachment_id=(
                attachment_id
            ),
        ),
    )

    # --------------------------------------------------------
    # HTTP result.
    # --------------------------------------------------------

    assert (
        response.status_code
        == 200
    )

    # --------------------------------------------------------
    # Attachment lookup happened once.
    # --------------------------------------------------------

    assert len(
        attachment_service.calls
    ) == 1

    assert (
        attachment_service.calls[0]
        ["provider_id"]
        == provider.id
    )

    assert (
        attachment_service.calls[0]
        ["attachment_id"]
        == attachment_id
    )

    # --------------------------------------------------------
    # Trusted path was resolved.
    # --------------------------------------------------------

    assert len(
        attachment_service.resolve_calls
    ) == 1

    assert (
        attachment_service.resolve_calls[0]
        ["provider_id"]
        == provider.id
    )

    assert (
        attachment_service.resolve_calls[0]
        ["attachment_id"]
        == attachment_id
    )

    # --------------------------------------------------------
    # MedMind received exactly one request.
    # --------------------------------------------------------

    assert len(
        medmind_service.calls
    ) == 1

    call = (
        medmind_service.calls[0]
    )

    assert (
        call["session_id"]
        == "session-1"
    )

    assert (
        call["attachment_ids"]
        == [attachment_id]
    )

    # --------------------------------------------------------
    # Trusted attachment payload.
    # --------------------------------------------------------

    trusted_attachments = (
        call[
            "trusted_attachments"
        ]
    )

    assert (
        trusted_attachments
        is not None
    )

    assert len(
        trusted_attachments
    ) == 1

    trusted = (
        trusted_attachments[0]
    )

    assert (
        trusted.attachment_id
        == attachment_id
    )

    assert (
        trusted.provider_id
        == provider.id
    )

    assert (
        trusted.session_id
        == "session-1"
    )

    assert (
        trusted.original_filename
        == "brain.jpg"
    )

    assert (
        trusted.content_type
        == "image/jpeg"
    )

    assert (
        trusted.data
        == b"fake-image-bytes"
    )

    assert (
        trusted.patient_id
        is None
    )

    assert (
        trusted.encounter_id
        is None
    )


# ============================================================
# INVALID FORMAT
# ============================================================


def test_invalid_attachment_id_returns_400(
    monkeypatch,
):

    attachment_id = (
        "invalid"
    )

    attachment_service = (
        FakeAttachmentService(
            invalid_ids={
                attachment_id
            },
        )
    )

    client, _, medmind_service = (
        make_client(
            monkeypatch,
            attachment_service=(
                attachment_service
            ),
        )
    )

    response = client.post(
        "/api/v1/ai/chat",
        headers={
            "X-Tenant-ID":
                "clinic-001",
        },
        json=payload(
            attachment_id=(
                attachment_id
            ),
        ),
    )

    assert (
        response.status_code
        == 400
    )

    assert (
        response.json()
        ["detail"]
        ["code"]
        == "INVALID_DIAGNOSTIC_ATTACHMENT"
    )

    assert (
        medmind_service.calls
        == []
    )

    # Invalid public ID must fail before
    # resolving a storage path.
    assert (
        attachment_service
        .resolve_calls
        == []
    )


# ============================================================
# WRONG PROVIDER / NOT FOUND
# ============================================================


def test_attachment_not_owned_by_provider_returns_404(
    monkeypatch,
):

    attachment_id = (
        "b" * 32
    )

    attachment_service = (
        FakeAttachmentService()
    )

    client, _, medmind_service = (
        make_client(
            monkeypatch,
            attachment_service=(
                attachment_service
            ),
        )
    )

    response = client.post(
        "/api/v1/ai/chat",
        headers={
            "X-Tenant-ID":
                "clinic-001",
        },
        json=payload(
            attachment_id=(
                attachment_id
            ),
        ),
    )

    assert (
        response.status_code
        == 404
    )

    assert (
        response.json()
        ["detail"]
        ["code"]
        == "DIAGNOSTIC_ATTACHMENT_NOT_FOUND"
    )

    assert (
        medmind_service.calls
        == []
    )

    # Provider ownership lookup fails before
    # any file path is resolved.
    assert (
        attachment_service
        .resolve_calls
        == []
    )


# ============================================================
# WRONG SESSION
# ============================================================


def test_attachment_from_another_session_returns_404(
    monkeypatch,
):

    attachment_id = (
        "c" * 32
    )

    attachment_service = (
        FakeAttachmentService()
    )

    client, provider, medmind_service = (
        make_client(
            monkeypatch,
            attachment_service=(
                attachment_service
            ),
        )
    )

    attachment_service.attachments[
        (
            provider.id,
            attachment_id,
        )
    ] = SimpleNamespace(
        attachment_id=(
            attachment_id
        ),

        provider_id=(
            provider.id
        ),

        # Deliberately different.
        session_id=(
            "another-session"
        ),

        original_filename=(
            "brain.jpg"
        ),

        content_type=(
            "image/jpeg"
        ),

        patient_id=None,

        encounter_id=None,
    )

    response = client.post(
        "/api/v1/ai/chat",
        headers={
            "X-Tenant-ID":
                "clinic-001",
        },
        json=payload(
            session_id=(
                "session-1"
            ),
            attachment_id=(
                attachment_id
            ),
        ),
    )

    assert (
        response.status_code
        == 404
    )

    assert (
        response.json()
        ["detail"]
        ["code"]
        == "DIAGNOSTIC_ATTACHMENT_NOT_FOUND"
    )

    assert (
        medmind_service.calls
        == []
    )

    # Session ownership must be checked
    # before file resolution.
    assert (
        attachment_service
        .resolve_calls
        == []
    )

def test_patient_bound_attachment_can_be_reused_in_later_session(
    monkeypatch,
    tmp_path,
):
    attachment_id = "c" * 32
    patient_id = uuid4()
    attachment_service = FakeAttachmentService()
    client, provider, medmind_service = make_client(
        monkeypatch,
        attachment_service=attachment_service,
    )
    path = tmp_path / "prior-upload.jpg"
    path.write_bytes(b"previously stored image")
    attachment_service.attachments[(provider.id, attachment_id)] = SimpleNamespace(
        attachment_id=attachment_id,
        provider_id=provider.id,
        session_id="earlier-session",
        original_filename="prior-upload.jpg",
        content_type="image/jpeg",
        patient_id=patient_id,
        encounter_id=None,
    )
    attachment_service.paths[(provider.id, attachment_id)] = path
    request_data = payload(session_id="new-session", attachment_id=attachment_id)
    request_data["patient_id"] = str(patient_id)

    response = client.post(
        "/api/v1/ai/chat",
        headers={"X-Tenant-ID": "clinic-001"},
        json=request_data,
    )

    assert response.status_code == 200, response.text
    assert medmind_service.calls[0]["trusted_attachments"][0].attachment_id == attachment_id


def test_structured_follow_up_answers_reach_the_agent_as_patient_history(monkeypatch):
    client, _, medmind_service = make_client(
        monkeypatch,
        attachment_service=FakeAttachmentService(),
    )
    request_data = payload()
    request_data["form_answers"] = {
        "symptoms": "صداع",
        "onset": "منذ أيام",
        "severity": 5,
        "pattern": "تأتي وتختفي",
    }

    response = client.post(
        "/api/v1/ai/chat",
        headers={"X-Tenant-ID": "clinic-001"},
        json=request_data,
    )

    assert response.status_code == 200, response.text
    assert "Patient-provided structured symptom answers" in medmind_service.calls[0]["message"]
    assert '"severity": 5' in medmind_service.calls[0]["message"]


def test_radiology_result_is_persisted_from_chat(
    monkeypatch,
    tmp_path,
):

    attachment_id = (
        "d" * 32
    )

    attachment_service = (
        FakeAttachmentService()
    )

    (
        client,
        provider,
        medmind_service,
    ) = make_client(
        monkeypatch,
        attachment_service=(
            attachment_service
        ),
    )

    image_path = (
        tmp_path
        / "brain.jpg"
    )

    image_path.write_bytes(
        b"fake-image-bytes"
    )

    attachment_service.attachments[
        (
            provider.id,
            attachment_id,
        )
    ] = SimpleNamespace(
        attachment_id=attachment_id,

        provider_id=provider.id,

        session_id="session-1",

        original_filename=(
            "brain.jpg"
        ),

        content_type=(
            "image/jpeg"
        ),

        patient_id=None,

        encounter_id=None,
    )

    attachment_service.paths[
        (
            provider.id,
            attachment_id,
        )
    ] = image_path

    medmind_service.diagnostic_result = {
        "kind":
            "radiology",

        "schema_version":
            "1.0",

        "attachment_id":
            attachment_id,

        "modality":
            "brain_mri",

        "classification":
            "pituitary",

        "probabilities": {
            "glioma": 0.02,
            "meningioma": 0.09,
            "notumor": 0.02,
            "pituitary": 0.87,
        },

        "confidence":
            0.87,

        "inference_latency_ms":
            150.0,

        "model_name":
            "fake-brain-mri-model",

        "model_version":
            "test",

        "limitations":
            [],
    }

    response = client.post(
        "/api/v1/ai/chat",

        headers={
            "X-Tenant-ID":
                "clinic-001",
        },

        json=payload(
            session_id="session-1",
            attachment_id=(
                attachment_id
            ),
        ),
    )

    assert (
        response.status_code
        == 200
    )

    adapter = (
        medmind_service
        .radiology_persistence_adapter
    )

    assert len(
        adapter.calls
    ) == 1

    call = (
        adapter.calls[0]
    )

    assert (
        call["provider_id"]
        == provider.id
    )

    request = (
        call["request"]
    )

    assert (
        request.attachment_id
        == attachment_id
    )

    assert (
        request.modality
        == "brain_mri"
    )

    assert (
        request.classification
        == "pituitary"
    )

    assert (
        request.confidence
        == Decimal("0.87")
    )

    assert (
        request.model_name
        == "fake-brain-mri-model"
    )

    assert (
        request.model_version
        == "test"
    )

    assert (
        request.probabilities[
            "pituitary"
        ]
        == Decimal("0.87")
    )

def test_pathology_result_is_persisted_from_chat(
    monkeypatch,
    tmp_path,
):

    attachment_id = (
        "e" * 32
    )

    attachment_service = (
        FakeAttachmentService()
    )

    (
        client,
        provider,
        medmind_service,
    ) = make_client(
        monkeypatch,
        attachment_service=(
            attachment_service
        ),
    )

    image_path = (
        tmp_path
        / "cbc.png"
    )

    image_path.write_bytes(
        b"fake-lab-image-bytes"
    )

    attachment_service.attachments[
        (
            provider.id,
            attachment_id,
        )
    ] = SimpleNamespace(
        attachment_id=attachment_id,

        provider_id=provider.id,

        session_id="session-1",

        original_filename=(
            "cbc.png"
        ),

        content_type=(
            "image/png"
        ),

        patient_id=None,

        encounter_id=None,
    )

    attachment_service.paths[
        (
            provider.id,
            attachment_id,
        )
    ] = image_path

    medmind_service.diagnostic_result = {
        "kind":
            "pathology",

        "schema_version":
            "1.0",

        "attachment_id":
            attachment_id,

        "document_type":
            "cbc",

        "unreadable_fields":
            [],

        "results": [
            {
                "result_index":
                    0,

                "panel":
                    "cbc",

                "raw_name":
                    "Hemoglobin",

                "canonical_name":
                    "hemoglobin",

                "value":
                    12.0,

                "unit":
                    "g/dL",

                "reference_min":
                    12.0,

                "reference_max":
                    16.0,

                "reference_text":
                    None,

                "flag":
                    "normal",

                "mapping_status":
                    "mapped",
            },

            {
                "result_index":
                    1,

                "panel":
                    "cbc",

                "raw_name":
                    "RBC",

                "canonical_name":
                    "rbc",

                "value":
                    3.3,

                "unit":
                    "10^6/uL",

                "reference_min":
                    4.0,

                "reference_max":
                    5.5,

                "reference_text":
                    None,

                "flag":
                    "low",

                "mapping_status":
                    "mapped",
            },
        ],
    }

    response = client.post(
        "/api/v1/ai/chat",

        headers={
            "X-Tenant-ID":
                "clinic-001",
        },

        json=payload(
            session_id="session-1",
            attachment_id=(
                attachment_id
            ),
        ),
    )

    assert (
        response.status_code
        == 200
    )

    adapter = (
        medmind_service
        .pathology_persistence_adapter
    )

    assert len(
        adapter.calls
    ) == 1

    call = (
        adapter.calls[0]
    )

    assert (
        call["provider_id"]
        == provider.id
    )

    request = (
        call["request"]
    )

    assert (
        request.attachment_id
        == attachment_id
    )

    assert (
        request.schema_version
        == "1.0"
    )

    assert (
        request.document_type
        == "cbc"
    )

    assert (
        request.unreadable_fields
        == []
    )

    assert len(
        request.results
    ) == 2

    hemoglobin = (
        request.results[0]
    )

    assert (
        hemoglobin.result_index
        == 0
    )

    assert (
        hemoglobin.panel
        == "cbc"
    )

    assert (
        hemoglobin.raw_name
        == "Hemoglobin"
    )

    assert (
        hemoglobin.canonical_name
        == "hemoglobin"
    )

    assert (
        hemoglobin.value
        == Decimal("12.0")
    )

    assert (
        hemoglobin.reference_min
        == Decimal("12.0")
    )

    assert (
        hemoglobin.reference_max
        == Decimal("16.0")
    )

    assert (
        hemoglobin.flag
        == "normal"
    )

    assert (
        hemoglobin.mapping_status
        == "mapped"
    )

    rbc = (
        request.results[1]
    )

    assert (
        rbc.result_index
        == 1
    )

    assert (
        rbc.value
        == Decimal("3.3")
    )

    assert (
        rbc.reference_min
        == Decimal("4.0")
    )

    assert (
        rbc.reference_max
        == Decimal("5.5")
    )

    assert (
        rbc.flag
        == "low"
    )

    assert (
        rbc.mapping_status
        == "mapped"
    )


def test_multiple_attachments_are_analyzed_individually(
    monkeypatch,
    tmp_path,
):
    attachment_service = FakeAttachmentService()
    client, provider, medmind_service = make_client(
        monkeypatch,
        attachment_service=attachment_service,
    )
    attachment_ids = ["a" * 32, "b" * 32]
    filenames = ["chest.jpg", "bloodwork.png"]
    for attachment_id, filename in zip(attachment_ids, filenames):
        path = tmp_path / filename
        path.write_bytes(b"file-bytes")
        attachment_service.attachments[(provider.id, attachment_id)] = SimpleNamespace(
            attachment_id=attachment_id,
            provider_id=provider.id,
            session_id="session-1",
            original_filename=filename,
            content_type="image/jpeg" if filename.endswith(".jpg") else "image/png",
            patient_id=None,
            encounter_id=None,
        )
        attachment_service.paths[(provider.id, attachment_id)] = path

    for attachment_id, classification in zip(attachment_ids, ["normal", "abnormal"]):
        medmind_service.diagnostic_results[attachment_id] = {
            "kind": "radiology",
            "schema_version": "1.0",
            "attachment_id": attachment_id,
            "modality": "chest_xray",
            "classification": classification,
            "probabilities": {classification: 0.9, "other": 0.1},
            "confidence": 0.9,
            "inference_latency_ms": 100.0,
            "model_name": "fake-radiology-model",
            "model_version": "test",
            "limitations": [],
        }

    request_data = payload(session_id="session-1")
    request_data["diagnostic_mode"] = "auto_image"
    request_data["attachment_ids"] = attachment_ids
    response = client.post(
        "/api/v1/ai/chat",
        headers={"X-Tenant-ID": "clinic-001"},
        json=request_data,
    )

    assert response.status_code == 200, response.text
    assert len(medmind_service.calls) == 3
    analysis_calls = medmind_service.calls[:2]
    assert [call["trusted_attachments"][0].original_filename for call in analysis_calls] == filenames
    assert len({call["session_id"] for call in analysis_calls}) == 2
    assert all(len(call["trusted_attachments"]) == 1 for call in analysis_calls)
    assert medmind_service.calls[2]["trusted_attachments"] is None
    assert medmind_service.calls[2]["medical_education_hint"] is True
    assert [item["filename"] for item in response.json()["diagnostic_file_replies"]] == filenames
    persisted_ids = {
        call["request"].attachment_id
        for call in medmind_service.radiology_persistence_adapter.calls
    }
    assert persisted_ids == set(attachment_ids)
