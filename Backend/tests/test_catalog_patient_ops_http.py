"""HTTP-level tests for existing catalog, staff patient lookup and health
endpoints (API coverage audit, package 1).

Real routers, real tenant resolution (get_current_provider), real staff JWT
and membership checks; only the catalog service, patient service, audit sink
and database engine are fakes. No database, network or AI. All identifiers
and names are fake.
"""

import logging
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api import dependencies as deps
from app.api.routers import catalog, health, public_catalog, staff_patients
from app.core.config import get_settings
from app.security.tokens import create_access_token
from app.services.staff_access_service import StaffAccessService
from tests.test_admin_ops_rbac_api import StubAudit
from tests.test_current_staff_resolution import FakeAuthRepository

TEST_JWT_SECRET = "test-only-signing-key-not-production-0123456789abcdef"
NATIONAL_ID = "29001011234567"  # synthetic
OTHER_NATIONAL_ID = "29001017654321"  # synthetic

PROVIDER_A = SimpleNamespace(id=uuid4(), tenant_key="clinic-001", timezone="Africa/Cairo")
PROVIDER_B = SimpleNamespace(id=uuid4(), tenant_key="clinic-002", timezone="Africa/Cairo")
UNLISTED_PROVIDER_ID = uuid4()


def _branch(provider, code):
    return SimpleNamespace(
        id=uuid4(), provider_id=provider.id, code=code, name_ar="فرع", name_en=f"Branch {code}",
        voice_label_ar=None, voice_label_en=None, voice_featured_rank=None,
        address_ar=None, address_en=None, governorate="Cairo", phone=None, whatsapp=None,
        timezone="Africa/Cairo", is_active=True,
    )


def _service(provider, code, service_type):
    return SimpleNamespace(
        id=uuid4(), provider_id=provider.id, code=code, name_ar="خدمة", name_en=f"Service {code}",
        voice_label_ar=None, voice_label_en=None, voice_featured_rank=None,
        duration_minutes=30, price=Decimal("150.00"), service_type=service_type,
        requires_preparation=False, preparation_instructions_ar=None, preparation_instructions_en=None,
        is_active=True,
    )


def _doctor(provider, specialty_id, name):
    return SimpleNamespace(
        id=uuid4(), provider_id=provider.id, specialty_id=specialty_id,
        full_name_ar="د. اختبار", full_name_en=name, specialty_name_ar=None, specialty_name_en=None,
        consultation_fee=Decimal("300.00"), experience_years=5, gender="female", rating_avg=None,
        review_count=0, accepting_new_patients=True, verification_status="verified", is_active=True,
    )


SPECIALTY_A = uuid4()


class FakeCatalogService:
    """Rows keyed by provider id; records every call's arguments."""

    def __init__(self):
        self.calls = []
        self.providers = {"clinic-001": PROVIDER_A, "clinic-002": PROVIDER_B}
        self.branches = {
            PROVIDER_A.id: [_branch(PROVIDER_A, "A-MAIN"), _branch(PROVIDER_A, "A-EAST")],
            PROVIDER_B.id: [_branch(PROVIDER_B, "B-MAIN")],
        }
        self.services = {
            PROVIDER_A.id: [_service(PROVIDER_A, "CONSULT", "consultation"), _service(PROVIDER_A, "CBC", "diagnostic")],
            PROVIDER_B.id: [_service(PROVIDER_B, "XRAY", "diagnostic")],
        }
        self.doctors = {
            PROVIDER_A.id: [_doctor(PROVIDER_A, SPECIALTY_A, "Dr A1"), _doctor(PROVIDER_A, uuid4(), "Dr A2")],
            PROVIDER_B.id: [_doctor(PROVIDER_B, uuid4(), "Dr B1")],
        }
        self.public = [
            SimpleNamespace(id=PROVIDER_A.id, name="Clinic A", slug="clinic-a", org_type="clinic", default_language="ar"),
            SimpleNamespace(id=PROVIDER_B.id, name="Lab B", slug="lab-b", org_type="diagnostic_lab", default_language="ar"),
        ]

    def get_provider(self, tenant_key):
        self.calls.append(("get_provider", tenant_key))
        return self.providers.get(tenant_key)

    def get_branches(self, provider_id):
        self.calls.append(("get_branches", provider_id))
        return self.branches.get(provider_id, [])

    def get_services(self, *, provider_id, service_type, doctor_id, specialty_id):
        self.calls.append(("get_services", dict(provider_id=provider_id, service_type=service_type,
                                                 doctor_id=doctor_id, specialty_id=specialty_id)))
        rows = self.services.get(provider_id, [])
        return [r for r in rows if service_type is None or r.service_type == service_type]

    def get_doctors(self, *, provider_id, specialty_id, branch_id, service_id):
        self.calls.append(("get_doctors", dict(provider_id=provider_id, specialty_id=specialty_id,
                                                branch_id=branch_id, service_id=service_id)))
        rows = self.doctors.get(provider_id, [])
        return [r for r in rows if specialty_id is None or r.specialty_id == specialty_id]

    def get_public_providers(self, *, org_type=None):
        self.calls.append(("get_public_providers", org_type))
        return [p for p in self.public if org_type is None or p.org_type == org_type]

    def get_public_provider_branches(self, provider_id):
        self.calls.append(("get_public_provider_branches", provider_id))
        if provider_id == UNLISTED_PROVIDER_ID:
            return None  # not a public provider
        return self.branches.get(provider_id, [])


class FakePatientService:
    """One synthetic patient, registered with provider A only."""

    def __init__(self):
        self.calls = []
        self.patient_id = uuid4()

    def lookup(self, *, provider_id, national_id, language):
        self.calls.append(dict(provider_id=provider_id, language=language))
        if provider_id == PROVIDER_A.id and national_id == NATIONAL_ID:
            return SimpleNamespace(
                patient_id=self.patient_id, patient_code="P-TEST-0001", display_name="Test Patient",
                masked_national_id="2900********67", phone="+20100000000",
            )
        return None


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    get_settings.cache_clear()

    catalog_service, patient_service, audit = FakeCatalogService(), FakePatientService(), StubAudit()
    state = SimpleNamespace(access=None)

    app = FastAPI()
    for router in (catalog.router, public_catalog.router, staff_patients.router):
        app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[deps.get_catalog_service] = lambda: catalog_service
    app.dependency_overrides[deps.get_patient_service] = lambda: patient_service
    app.dependency_overrides[deps.get_staff_audit_service] = lambda: audit
    app.dependency_overrides[deps.get_staff_access_service] = lambda: state.access or object()
    client = TestClient(app)

    def staff_token(role, provider=PROVIDER_A, *, active=True):
        user = SimpleNamespace(id=uuid4())
        membership = SimpleNamespace(id=uuid4(), provider_id=provider.id, role=role,
                                     doctor_id=uuid4() if role == "doctor" else None)
        state.access = StaffAccessService(
            FakeAuthRepository(user=user, membership=membership if active else None)
        )
        return create_access_token(user_id=user.id, membership_id=membership.id, provider_id=provider.id), user

    yield SimpleNamespace(client=client, catalog=catalog_service, patients=patient_service, audit=audit,
                          staff_token=staff_token)
    get_settings.cache_clear()


def _code(response):
    return response.json()["detail"]["code"]


def _tenant(key="clinic-001", token=None):
    headers = {"X-Tenant-ID": key}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# ============================================================ GET /public/providers


def test_public_providers_lists_only_the_requested_org_type_without_auth(api):
    response = api.client.get("/api/v1/public/providers", params={"org_type": "clinic"})

    assert response.status_code == 200
    body = response.json()
    assert [p["slug"] for p in body] == ["clinic-a"]
    assert set(body[0]) == {"id", "name", "slug", "org_type", "default_language"}
    assert ("get_public_providers", "clinic") in api.catalog.calls


def test_public_providers_returns_an_empty_list(api):
    response = api.client.get("/api/v1/public/providers", params={"org_type": "hospital"})

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("params", [{"org_type": "pharmacy"}, {"org_type": ""}])
def test_public_providers_reject_an_invalid_org_type(api, params):
    response = api.client.get("/api/v1/public/providers", params=params)

    assert response.status_code == 422
    assert not [c for c in api.catalog.calls if c[0] == "get_public_providers"]


# ============================================================ GET /public/providers/{id}/branches


def test_public_branches_returns_the_providers_branches(api):
    response = api.client.get(f"/api/v1/public/providers/{PROVIDER_A.id}/branches")

    assert response.status_code == 200
    body = response.json()
    assert {b["code"] for b in body} == {"A-MAIN", "A-EAST"}
    assert all(UUID(b["provider_id"]) == PROVIDER_A.id for b in body)
    # Public shape only: no phone, WhatsApp, timezone or active flag.
    assert set(body[0]) == {"id", "provider_id", "code", "name_ar", "name_en", "address_ar", "address_en", "governorate"}


def test_public_branches_returns_an_empty_list_for_a_provider_without_branches(api):
    provider_id = uuid4()

    response = api.client.get(f"/api/v1/public/providers/{provider_id}/branches")

    assert response.status_code == 200
    assert response.json() == []


def test_public_branches_of_an_unavailable_provider_are_404(api):
    response = api.client.get(f"/api/v1/public/providers/{UNLISTED_PROVIDER_ID}/branches")

    assert response.status_code == 404
    assert _code(response) == "PUBLIC_PROVIDER_NOT_FOUND"


def test_public_branches_rejects_a_malformed_provider_id(api):
    response = api.client.get("/api/v1/public/providers/not-a-uuid/branches")

    assert response.status_code == 422


# ============================================================ tenant-scoped catalog reads

TENANT_READS = ["/api/v1/branches", "/api/v1/services", "/api/v1/doctors"]


@pytest.mark.parametrize("path", TENANT_READS)
def test_tenant_reads_require_the_tenant_header(api, path):
    response = api.client.get(path)

    assert response.status_code == 422
    assert api.catalog.calls == []


@pytest.mark.parametrize("path", TENANT_READS)
def test_tenant_reads_reject_an_unknown_tenant(api, path):
    response = api.client.get(path, headers=_tenant("no-such-clinic"))

    assert response.status_code == 404
    assert _code(response) == "PROVIDER_NOT_FOUND"
    assert api.catalog.calls == [("get_provider", "no-such-clinic")]


@pytest.mark.parametrize("path", TENANT_READS)
def test_tenant_reads_need_no_staff_or_service_token(api, path):
    response = api.client.get(path, headers=_tenant())

    assert response.status_code == 200


def test_branches_are_scoped_to_the_resolved_tenant(api):
    a = api.client.get("/api/v1/branches", headers=_tenant("clinic-001")).json()
    b = api.client.get("/api/v1/branches", headers=_tenant("clinic-002")).json()

    assert {x["code"] for x in a} == {"A-MAIN", "A-EAST"}
    assert {x["code"] for x in b} == {"B-MAIN"}
    assert ("get_branches", PROVIDER_A.id) in api.catalog.calls
    assert ("get_branches", PROVIDER_B.id) in api.catalog.calls


def test_branches_empty_list(api):
    api.catalog.branches[PROVIDER_B.id] = []

    response = api.client.get("/api/v1/branches", headers=_tenant("clinic-002"))

    assert response.status_code == 200
    assert response.json() == []


def test_services_are_scoped_and_filtered(api):
    response = api.client.get("/api/v1/services", headers=_tenant("clinic-001"), params={"service_type": "diagnostic"})

    assert response.status_code == 200
    assert [s["code"] for s in response.json()] == ["CBC"]
    (_, kwargs), = [c for c in api.catalog.calls if c[0] == "get_services"]
    assert kwargs == {"provider_id": PROVIDER_A.id, "service_type": "diagnostic", "doctor_id": None, "specialty_id": None}


def test_services_pass_doctor_and_specialty_filters(api):
    doctor_id, specialty_id = uuid4(), uuid4()

    api.client.get(
        "/api/v1/services", headers=_tenant("clinic-002"),
        params={"doctor_id": str(doctor_id), "specialty_id": str(specialty_id)},
    )

    (_, kwargs), = [c for c in api.catalog.calls if c[0] == "get_services"]
    assert kwargs == {"provider_id": PROVIDER_B.id, "service_type": None,
                      "doctor_id": doctor_id, "specialty_id": specialty_id}


def test_services_empty_list(api):
    response = api.client.get("/api/v1/services", headers=_tenant("clinic-002"), params={"service_type": "surgery"})

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    "params",
    [{"service_type": "x" * 31}, {"service_type": "lab_test"}, {"doctor_id": "not-a-uuid"},
     {"specialty_id": "not-a-uuid"}],
)
def test_services_reject_invalid_filters(api, params):
    response = api.client.get("/api/v1/services", headers=_tenant(), params=params)

    assert response.status_code == 422
    assert not [c for c in api.catalog.calls if c[0] == "get_services"]


def test_doctors_are_scoped_and_filtered(api):
    response = api.client.get(
        "/api/v1/doctors", headers=_tenant("clinic-001"), params={"specialty_id": str(SPECIALTY_A)}
    )

    assert response.status_code == 200
    body = response.json()
    assert [d["full_name_en"] for d in body] == ["Dr A1"]
    assert UUID(body[0]["provider_id"]) == PROVIDER_A.id
    (_, kwargs), = [c for c in api.catalog.calls if c[0] == "get_doctors"]
    assert kwargs == {"provider_id": PROVIDER_A.id, "specialty_id": SPECIALTY_A, "branch_id": None, "service_id": None}


def test_doctors_of_another_tenant_are_not_returned(api):
    response = api.client.get("/api/v1/doctors", headers=_tenant("clinic-002"))

    assert [d["full_name_en"] for d in response.json()] == ["Dr B1"]


def test_doctors_empty_list(api):
    response = api.client.get(
        "/api/v1/doctors", headers=_tenant("clinic-002"), params={"specialty_id": str(SPECIALTY_A)}
    )

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("param", ["specialty_id", "branch_id", "service_id"])
def test_doctors_reject_malformed_ids(api, param):
    response = api.client.get("/api/v1/doctors", headers=_tenant(), params={param: "not-a-uuid"})

    assert response.status_code == 422
    assert not [c for c in api.catalog.calls if c[0] == "get_doctors"]


# ============================================================ POST /staff/patients/lookup

LOOKUP = "/api/v1/staff/patients/lookup"


@pytest.mark.parametrize("role", ["doctor", "receptionist", "lab_staff"])
def test_staff_lookup_finds_the_patient_and_audits_it(api, role):
    token, user = api.staff_token(role)

    response = api.client.post(LOOKUP, headers=_tenant(token=token), json={"national_id": NATIONAL_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["found"] is True
    assert set(body["patient"]) == {"patient_id", "patient_code", "display_name", "masked_national_id", "phone"}
    assert NATIONAL_ID not in response.text  # only the masked form is returned
    assert api.patients.calls == [{"provider_id": PROVIDER_A.id, "language": "ar"}]
    (record,) = api.audit.records
    assert (record["action"], record["outcome"]) == ("patient.lookup", "success")
    assert record["patient_id"] == api.patients.patient_id
    assert record["user_id"] == user.id


def test_staff_lookup_not_found_is_audited_without_a_patient(api):
    token, _ = api.staff_token("receptionist")

    response = api.client.post(LOOKUP, headers=_tenant(token=token), json={"national_id": OTHER_NATIONAL_ID})

    assert response.status_code == 200
    assert response.json() == {"found": False, "patient": None}
    (record,) = api.audit.records
    assert (record["outcome"], record["patient_id"]) == ("not_found", None)


def test_staff_lookup_is_scoped_to_the_staff_members_provider(api):
    # The synthetic patient is registered with provider A only.
    token, _ = api.staff_token("receptionist", provider=PROVIDER_B)

    response = api.client.post(LOOKUP, headers=_tenant("clinic-002", token=token), json={"national_id": NATIONAL_ID})

    assert response.json() == {"found": False, "patient": None}
    assert api.patients.calls == [{"provider_id": PROVIDER_B.id, "language": "ar"}]


def test_staff_lookup_passes_the_language(api):
    token, _ = api.staff_token("doctor")

    api.client.post(LOOKUP, headers=_tenant(token=token), json={"national_id": NATIONAL_ID, "language": "en"})

    assert api.patients.calls == [{"provider_id": PROVIDER_A.id, "language": "en"}]


def test_staff_lookup_requires_a_staff_token(api):
    response = api.client.post(LOOKUP, headers=_tenant(), json={"national_id": NATIONAL_ID})

    assert response.status_code == 401
    assert _code(response) == "STAFF_AUTH_REQUIRED"
    assert api.patients.calls == [] and api.audit.records == []


def test_staff_lookup_rejects_an_invalid_token(api):
    api.staff_token("receptionist")

    response = api.client.post(LOOKUP, headers=_tenant(token="not-a-jwt"), json={"national_id": NATIONAL_ID})

    assert response.status_code == 401
    assert _code(response) == "INVALID_ACCESS_TOKEN"
    assert api.patients.calls == []


def test_staff_lookup_rejects_a_token_for_another_provider(api):
    token, _ = api.staff_token("receptionist", provider=PROVIDER_A)

    response = api.client.post(LOOKUP, headers=_tenant("clinic-002", token=token), json={"national_id": NATIONAL_ID})

    assert response.status_code == 403
    assert _code(response) == "STAFF_TENANT_MISMATCH"
    assert api.patients.calls == [] and api.audit.records == []


def test_staff_lookup_rejects_an_inactive_membership(api):
    token, _ = api.staff_token("receptionist", active=False)

    response = api.client.post(LOOKUP, headers=_tenant(token=token), json={"national_id": NATIONAL_ID})

    assert response.status_code == 401
    assert _code(response) == "INVALID_STAFF_SESSION"
    assert api.patients.calls == []


def test_staff_lookup_current_role_policy_excludes_provider_admin(api):
    # Pins current behaviour (staff_patients.py: doctor, receptionist, lab_staff).
    token, _ = api.staff_token("provider_admin")

    response = api.client.post(LOOKUP, headers=_tenant(token=token), json={"national_id": NATIONAL_ID})

    assert response.status_code == 403
    assert _code(response) == "STAFF_PERMISSION_DENIED"
    assert api.patients.calls == [] and api.audit.records == []


@pytest.mark.parametrize(
    "body",
    [{}, {"national_id": "123"}, {"national_id": NATIONAL_ID + "0"}, {"national_id": NATIONAL_ID, "language": "fr"}],
)
def test_staff_lookup_validates_the_request(api, body):
    token, _ = api.staff_token("receptionist")

    response = api.client.post(LOOKUP, headers=_tenant(token=token), json=body)

    assert response.status_code == 422
    assert api.patients.calls == [] and api.audit.records == []


def test_staff_lookup_does_not_log_the_national_id(api, caplog):
    caplog.set_level(logging.DEBUG)
    token, _ = api.staff_token("receptionist")

    api.client.post(LOOKUP, headers=_tenant(token=token), json={"national_id": NATIONAL_ID})

    assert NATIONAL_ID not in caplog.text
    assert token not in caplog.text


# ============================================================ GET /health and GET /ready


class FakeEngine:
    """Stands in for app.db.session.engine; never opens a real connection."""

    def __init__(self, fail=False):
        self.fail = fail
        self.statements = []

    @contextmanager
    def connect(self):
        if self.fail:
            raise OperationalError("SELECT 1", {}, Exception("simulated outage"))
        yield SimpleNamespace(execute=lambda statement: self.statements.append(str(statement)))


@pytest.fixture
def health_client(monkeypatch):
    import app.main as backend_main

    engine = FakeEngine()
    monkeypatch.setattr(health, "engine", engine)
    # Not used as a context manager: the application lifespan does not run.
    return TestClient(backend_main.app), engine


@pytest.mark.parametrize("path", ["/health", "/ready"])
def test_readiness_reports_a_reachable_database(health_client, path):
    client, engine = health_client

    response = client.get(path)

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["database"]) == ("ok", "connected")
    assert engine.statements == ["SELECT 1"]


@pytest.mark.parametrize("path", ["/health", "/ready"])
def test_readiness_reports_an_unreachable_database_as_503(health_client, path):
    client, engine = health_client
    engine.fail = True

    response = client.get(path)

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "disconnected"}
    assert "simulated outage" not in response.text


def test_ready_and_health_are_the_same_check(health_client):
    client, _ = health_client

    assert client.get("/ready").json() == client.get("/health").json()


@pytest.mark.parametrize("path", ["/health", "/ready"])
@pytest.mark.parametrize("fail", [False, True])
def test_readiness_never_reveals_database_details(health_client, path, fail):
    client, engine = health_client
    engine.fail = fail

    body = client.get(path).json()

    # Unauthenticated: exactly these keys, no database name or server.
    assert set(body) == {"status", "database"}
    from app.core.config import get_settings

    assert get_settings().db_name not in str(body)


def test_readiness_needs_no_auth_or_tenant(health_client):
    client, _ = health_client

    response = client.get("/health", headers={})

    assert response.status_code == 200
