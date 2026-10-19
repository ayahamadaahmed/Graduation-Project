"""Diagnostic attachment patient binding requires the patient's national ID.

Real DiagnosticAttachmentBindingService + upload route with in-memory fakes,
plus the chat persistence path (attachment -> report). No database.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import dependencies as deps
from app.api.routers import diagnostics
from app.core.patient_identity import normalize_national_id
from app.security.service_auth import ServiceContext, require_trusted_service
from app.services.ai_chat_session_registry import AIChatSessionRegistry
from app.services.diagnostic_attachment_binding_service import (
    DiagnosticAttachmentBindingService,
    DiagnosticInvalidNationalIdError,
    DiagnosticNationalIdRequiredError,
    DiagnosticPatientNotFoundError,
    DiagnosticPatientProviderMismatchError,
)
from app.services.radiology_persistence_adapter import RadiologyPersistenceAdapter
from tests.test_diagnostic_attachment_upload_api import FakeAttachmentService
from tests.test_radiology_persistence_adapter import (
    FakeAttachmentService as FakeStoredAttachmentLookup,
)
from tests.test_radiology_persistence_adapter import (
    FakeRadiologyPersistenceService,
    make_request,
)

# Test-only identity values (not real national IDs).
NID_PATIENT = "29001010100011"
NID_OTHER = "29001010100022"
NID_UNKNOWN = "29001010100099"


class FakeIdentityProtector:
    def hash_national_id(self, national_id):
        return "hash:" + normalize_national_id(national_id)


class World:
    """Provider A with `patient` and `other`; provider B with neither."""

    def __init__(self):
        self.provider_a, self.provider_b = uuid4(), uuid4()
        self.patient = SimpleNamespace(id=uuid4())
        self.other = SimpleNamespace(id=uuid4())
        self.by_hash = {
            "hash:" + NID_PATIENT: self.patient,
            "hash:" + NID_OTHER: self.other,
        }
        self.profiles = {
            (self.patient.id, self.provider_a),
            (self.other.id, self.provider_a),
        }
        self.factory_calls = 0

    # --- PatientRepository surface used by the binding service ---------------
    def get_active_by_national_id_hash(self, national_id_hash):
        return self.by_hash.get(national_id_hash)

    def get_active_by_id(self, patient_id):
        return next((p for p in (self.patient, self.other) if p.id == patient_id), None)

    def get_provider_profile(self, *, patient_id, provider_id):
        if (patient_id, provider_id) in self.profiles:
            return SimpleNamespace(is_active=True)
        return None

    def protector(self):
        self.factory_calls += 1
        return FakeIdentityProtector()

    def service(self):
        return DiagnosticAttachmentBindingService(
            patient_repository=self,
            encounter_repository=SimpleNamespace(get_for_patient_provider=lambda **kw: None),
            identity_protector_factory=self.protector,
        )


# ================================================================ binding service


def test_matching_identity_binds_patient():
    w = World()
    binding = w.service().resolve(provider_id=w.provider_a, patient_id=w.patient.id, national_id=NID_PATIENT)
    assert binding.patient_id == w.patient.id


def test_another_patients_national_id_is_patient_not_found():
    w = World()
    with pytest.raises(DiagnosticPatientNotFoundError):
        w.service().resolve(provider_id=w.provider_a, patient_id=w.patient.id, national_id=NID_OTHER)


def test_unknown_national_id_is_patient_not_found():
    w = World()
    with pytest.raises(DiagnosticPatientNotFoundError):
        w.service().resolve(provider_id=w.provider_a, patient_id=w.patient.id, national_id=NID_UNKNOWN)


@pytest.mark.parametrize("national_id", ["2900101010001X", "123", "290010101000111"])
def test_malformed_national_id_is_rejected(national_id):
    w = World()
    with pytest.raises(DiagnosticInvalidNationalIdError) as exc_info:
        w.service().resolve(provider_id=w.provider_a, patient_id=w.patient.id, national_id=national_id)
    assert national_id not in str(exc_info.value)


@pytest.mark.parametrize("national_id", [None, "", "   "])
def test_patient_binding_without_national_id_is_rejected(national_id):
    w = World()
    with pytest.raises(DiagnosticNationalIdRequiredError):
        w.service().resolve(provider_id=w.provider_a, patient_id=w.patient.id, national_id=national_id)


def test_correct_identity_at_another_provider_is_rejected():
    w = World()
    with pytest.raises(DiagnosticPatientProviderMismatchError):
        w.service().resolve(provider_id=w.provider_b, patient_id=w.patient.id, national_id=NID_PATIENT)


def test_unbound_upload_needs_no_identity_or_keys():
    w = World()
    binding = w.service().resolve(provider_id=w.provider_a)
    assert binding.patient_id is None and binding.encounter_id is None
    assert w.factory_calls == 0


# ================================================================ upload API


def _client(w, provider_id):
    store = FakeAttachmentService()
    app = FastAPI()
    app.include_router(diagnostics.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_current_provider] = lambda: SimpleNamespace(
        id=provider_id, tenant_key="clinic-001"
    )
    app.dependency_overrides[deps.get_diagnostic_attachment_service] = lambda: store
    app.dependency_overrides[deps.get_diagnostic_attachment_binding_service] = w.service
    # Uploads need a trusted gateway allowed for the tenant and a session it owns.
    app.dependency_overrides[require_trusted_service] = lambda: ServiceContext(
        name="test_gateway", allowed_tenants=frozenset({"clinic-001"})
    )
    sessions = AIChatSessionRegistry(idle_timeout_seconds=3600)
    app.state.ai_chat_session_registry = sessions
    client = TestClient(app)
    client.medmind_session_id = sessions.create(
        provider_id=provider_id, service_name="test_gateway", channel="web"
    ).session_id
    return client, store


def _upload(client, **form):
    data = {"session_id": client.medmind_session_id, **{k: str(v) for k, v in form.items()}}
    return client.post(
        "/api/v1/diagnostics/attachments",
        data=data,
        files={"file": ("xray.jpg", b"fake-image-data", "image/jpeg")},
    )


def test_api_matching_identity_stores_binding_without_national_id():
    w = World()
    client, store = _client(w, w.provider_a)
    response = _upload(client, patient_id=w.patient.id, national_id=NID_PATIENT)
    assert response.status_code == 201
    assert store.calls[0]["patient_id"] == w.patient.id
    assert NID_PATIENT not in str(store.calls) and NID_PATIENT not in response.text


@pytest.mark.parametrize("national_id", [NID_OTHER, NID_UNKNOWN])
def test_api_mismatched_identity_is_404_and_stores_nothing(national_id):
    w = World()
    client, store = _client(w, w.provider_a)
    response = _upload(client, patient_id=w.patient.id, national_id=national_id)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "DIAGNOSTIC_PATIENT_NOT_FOUND"
    assert not store.calls


def test_api_malformed_identity_is_422_and_not_echoed():
    w = World()
    client, store = _client(w, w.provider_a)
    response = _upload(client, patient_id=w.patient.id, national_id="2900101010001X")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_NATIONAL_ID"
    assert "2900101010001X" not in response.text
    assert not store.calls


def test_api_missing_identity_with_patient_is_422():
    w = World()
    client, store = _client(w, w.provider_a)
    response = _upload(client, patient_id=w.patient.id)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "NATIONAL_ID_REQUIRED"
    assert not store.calls


def test_api_cross_provider_is_404_and_stores_nothing():
    w = World()
    client, store = _client(w, w.provider_b)
    response = _upload(client, patient_id=w.patient.id, national_id=NID_PATIENT)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "DIAGNOSTIC_PATIENT_NOT_FOUND"
    assert not store.calls


def test_api_unbound_upload_still_works():
    w = World()
    client, store = _client(w, w.provider_a)
    response = _upload(client)
    assert response.status_code == 201
    assert store.calls[0]["patient_id"] is None
    assert w.factory_calls == 0


# ================================================================ chat persistence path


def _persist_report_for_stored_attachment(stored_call):
    """What /ai/chat does after analysis: adapter.persist with the stored attachment."""
    attachment = SimpleNamespace(
        id=uuid4(), patient_id=stored_call["patient_id"], encounter_id=stored_call["encounter_id"]
    )
    persistence = FakeRadiologyPersistenceService()
    RadiologyPersistenceAdapter(
        attachment_service=FakeStoredAttachmentLookup(attachment),
        radiology_persistence_service=persistence,
    ).persist(provider_id=uuid4(), request=make_request())
    return persistence.calls[0]


def test_unverified_upload_cannot_produce_patient_linked_report():
    w = World()
    client, store = _client(w, w.provider_a)

    # Attempt to bind someone else's record with a wrong national ID: rejected, nothing stored.
    assert _upload(client, patient_id=w.patient.id, national_id=NID_OTHER).status_code == 404
    assert not store.calls

    # The only way through without identity is an unbound upload ...
    assert _upload(client).status_code == 201
    report = _persist_report_for_stored_attachment(store.calls[0])

    # ... whose chat-persisted report is linked to no patient.
    assert report["patient_id"] is None
    assert report["encounter_id"] is None


def test_verified_upload_produces_report_for_that_patient_only():
    w = World()
    client, store = _client(w, w.provider_a)
    assert _upload(client, patient_id=w.patient.id, national_id=NID_PATIENT).status_code == 201
    report = _persist_report_for_stored_attachment(store.calls[0])
    assert report["patient_id"] == w.patient.id
