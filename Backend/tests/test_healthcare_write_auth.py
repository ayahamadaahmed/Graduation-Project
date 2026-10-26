"""Auth for healthcare writes: diagnostic result persistence (staff) and
patient profile update (national-ID identity). No database."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import dependencies as deps
from app.api.routers import diagnostics, patients
from app.core.config import get_settings
from app.schemas.patient import PatientProfileUpdateRequest
from app.security.staff_context import StaffContext
from app.security.tokens import create_access_token
from app.services.staff_access_service import StaffAccessService
from tests.test_current_staff_resolution import FakeAuthRepository
from tests.test_pathology_persistence_api import FakePathologyAdapter
from tests.test_pathology_persistence_api import make_payload as pathology_payload
from tests.test_patient_profile_update import (
    VALID_NATIONAL_ID,
    FakePatientRepository,
    make_patient,
    make_provider_profile,
    make_service,
)
from tests.test_radiology_persistence_api import FakeRadiologyAdapter
from tests.test_radiology_persistence_api import make_payload as radiology_payload

TEST_JWT_SECRET = "test-only-signing-key-not-production-0123456789abcdef"

ENDPOINTS = {
    "pathology": ("/api/v1/diagnostics/pathology-results", pathology_payload,
                  FakePathologyAdapter, deps.get_pathology_persistence_adapter, "lab_report"),
    "radiology": ("/api/v1/diagnostics/radiology-results", radiology_payload,
                  FakeRadiologyAdapter, deps.get_radiology_persistence_adapter, "radiology_report"),
}


class StubAudit:
    def __init__(self):
        self.records = []

    def record(self, **kwargs):
        self.records.append(kwargs)


def _diagnostics_app(kind, *, staff=None, provider_id=None, access_service=None):
    path, payload, adapter_cls, adapter_dep, _ = ENDPOINTS[kind]
    adapter, audit = adapter_cls(), StubAudit()
    provider_id = provider_id or (staff.provider_id if staff else uuid4())
    app = FastAPI()
    app.include_router(diagnostics.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_current_provider] = lambda: SimpleNamespace(
        id=provider_id, tenant_key="lab-001"
    )
    app.dependency_overrides[adapter_dep] = lambda: adapter
    app.dependency_overrides[deps.get_staff_audit_service] = lambda: audit
    if staff is not None:
        app.dependency_overrides[deps.get_current_staff] = lambda: staff
    else:
        app.dependency_overrides[deps.get_staff_access_service] = lambda: access_service or object()
    return TestClient(app), path, payload, adapter, audit


def _staff(role, provider_id=None):
    return StaffContext(user_id=uuid4(), membership_id=uuid4(), provider_id=provider_id or uuid4(),
                        role=role, doctor_id=uuid4() if role == "doctor" else None)


# ================================================================ diagnostics


@pytest.mark.parametrize("kind", ENDPOINTS)
def test_result_write_without_token_is_401(kind):
    client, path, payload, adapter, audit = _diagnostics_app(kind)
    response = client.post(path, json=payload())
    assert response.status_code == 401
    assert not adapter.calls and not audit.records


@pytest.mark.parametrize("kind", ENDPOINTS)
def test_result_write_with_invalid_token_is_401(kind, monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    get_settings.cache_clear()
    try:
        client, path, payload, adapter, audit = _diagnostics_app(kind)
        response = client.post(path, json=payload(), headers={"Authorization": "Bearer not-a-jwt"})
        assert response.status_code == 401
        assert not adapter.calls
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("kind", ENDPOINTS)
@pytest.mark.parametrize("role", ["receptionist", "provider_admin"])
def test_result_write_by_non_report_role_is_403(kind, role):
    client, path, payload, adapter, audit = _diagnostics_app(kind, staff=_staff(role))
    response = client.post(path, json=payload())
    assert response.status_code == 403
    assert not adapter.calls and not audit.records


@pytest.mark.parametrize("kind", ENDPOINTS)
@pytest.mark.parametrize("role", ["doctor", "lab_staff"])
def test_result_write_by_report_role_succeeds_and_is_audited(kind, role):
    staff = _staff(role)
    client, path, payload, adapter, audit = _diagnostics_app(kind, staff=staff)
    response = client.post(path, json=payload())
    assert response.status_code == 201
    assert adapter.calls[0]["provider_id"] == staff.provider_id
    assert len(audit.records) == 1
    record = audit.records[0]
    assert record["action"] == f"diagnostics.{kind}.persist"
    assert record["resource_type"] == ENDPOINTS[kind][4]
    assert record["resource_id"] == str(adapter.report_id)
    assert record["outcome"] == "success"
    assert record["provider_id"] == staff.provider_id
    assert record["membership_id"] == staff.membership_id


@pytest.mark.parametrize("kind", ENDPOINTS)
def test_token_for_another_provider_is_rejected(kind, monkeypatch):
    """Real token decoding + staff resolution: provider A token, provider B tenant."""
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    get_settings.cache_clear()
    try:
        provider_a, provider_b = uuid4(), uuid4()
        user = SimpleNamespace(id=uuid4())
        membership = SimpleNamespace(id=uuid4(), provider_id=provider_a, role="lab_staff", doctor_id=None)
        token = create_access_token(user_id=user.id, membership_id=membership.id, provider_id=provider_a)
        access = StaffAccessService(FakeAuthRepository(user=user, membership=membership))

        client, path, payload, adapter, audit = _diagnostics_app(
            kind, provider_id=provider_b, access_service=access
        )
        response = client.post(path, json=payload(), headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403
        assert not adapter.calls and not audit.records
    finally:
        get_settings.cache_clear()


# ================================================================ profile PATCH


def _profile_world():
    patient, provider_id = make_patient(), uuid4()
    repo = FakePatientRepository(
        patient=patient,
        provider_profile=make_provider_profile(patient_id=patient.id, provider_id=provider_id),
    )
    return make_service(repo), patient, provider_id


def _update(service, patient, provider_id, national_id):
    return service.update_profile(
        provider_id=provider_id, patient_id=patient.id, national_id=national_id,
        patient_name="آية محمد", phone=None, language="ar", channel="voice",
    )


def test_profile_update_with_matching_national_id_succeeds():
    service, patient, provider_id = _profile_world()
    _update(service, patient, provider_id, VALID_NATIONAL_ID)
    assert patient.full_name_ar == "آية محمد"


def test_profile_update_with_another_patients_national_id_is_404():
    service, patient, provider_id = _profile_world()
    with pytest.raises(HTTPException) as exc_info:
        _update(service, patient, provider_id, "29001010100099")
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "PATIENT_NOT_FOUND"
    assert patient.full_name_ar == "آية أحمد"


def test_profile_update_with_malformed_national_id_is_422():
    service, patient, provider_id = _profile_world()
    with pytest.raises(HTTPException) as exc_info:
        _update(service, patient, provider_id, "2900101010001X")
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "INVALID_NATIONAL_ID"
    assert VALID_NATIONAL_ID not in str(exc_info.value.detail)


def test_profile_request_requires_national_id_and_hides_it():
    with pytest.raises(ValidationError):
        PatientProfileUpdateRequest(patient_name="Aya", language="ar", channel="voice")
    request = PatientProfileUpdateRequest(
        national_id=VALID_NATIONAL_ID, patient_name="Aya", language="ar", channel="voice"
    )
    assert VALID_NATIONAL_ID not in repr(request)


def test_profile_api_without_national_id_is_422_and_passes_it_through():
    calls = []
    service = SimpleNamespace(update_profile=lambda **kw: calls.append(kw) or {
        "patient_id": str(kw["patient_id"]), "display_name": "Aya", "phone": "01023456789", "updated_fields": [],
    })
    app = FastAPI()
    app.include_router(patients.router, prefix="/api/v1")
    provider_id = uuid4()
    app.dependency_overrides[deps.get_current_provider] = lambda: SimpleNamespace(id=provider_id)
    app.dependency_overrides[deps.get_patient_service] = lambda: service
    client = TestClient(app)
    url = f"/api/v1/patients/{uuid4()}/profile"

    missing = client.patch(url, json={"patient_name": "Aya", "language": "ar", "channel": "voice"})
    assert missing.status_code == 422 and not calls

    client.patch(url, json={"national_id": VALID_NATIONAL_ID, "patient_name": "Aya",
                            "language": "ar", "channel": "voice"})
    assert calls and calls[0]["national_id"] == VALID_NATIONAL_ID
    assert calls[0]["provider_id"] == provider_id


# ================================================================ MCP contract


def test_mcp_tool_sends_national_id_in_body_not_url(monkeypatch):
    from mcp_server.tools import patients as patient_tools

    sent = {}

    async def fake_request(**kwargs):
        sent.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(patient_tools.backend_client, "request", fake_request)
    patient_id = str(uuid4())
    asyncio.run(patient_tools.update_patient_profile(
        tenant_id="lab-001", patient_id=patient_id, national_id=VALID_NATIONAL_ID,
        patient_name="Aya", phone=None, language="ar", channel="voice",
    ))
    assert sent["method"] == "PATCH"
    assert sent["path"] == f"/api/v1/patients/{patient_id}/profile"
    assert VALID_NATIONAL_ID not in sent["path"]
    assert sent["json"]["national_id"] == VALID_NATIONAL_ID
    assert sent["json"]["patient_name"] == "Aya"


def test_mcp_server_tool_requires_national_id():
    import inspect

    from mcp_server import server

    fn = getattr(server.update_patient_profile, "fn", server.update_patient_profile)
    parameter = inspect.signature(fn).parameters["national_id"]
    assert parameter.default is inspect.Parameter.empty
