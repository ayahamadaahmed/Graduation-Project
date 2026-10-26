"""Final offline HTTP-contract package (API coverage audit, package 4).

Covers what packages 1-3 and the older suites leave open:
audit-events parameters and shape, specialties, slots, providers/current,
patients/lookup and patients/{id}/profile contracts, the real
AdminCatalogService behind POST /admin/doctors, and GET /auth/me.

Real routers, schemas, validators, tenant resolution (get_current_provider)
and, for /auth/me, the real JWT and membership checks. Repositories, services
and the database are fakes. No database, network or AI. All values are fake.
"""

from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api import dependencies as deps
from app.api.routers import admin_catalog, auth, catalog, ops, patients
from app.core.config import get_settings
from app.schemas.catalog import ProviderOut, SlotOut, SpecialtyOut
from app.schemas.ops import AuditEventOut
from app.schemas.patient import PatientLookupResult, PatientProfileUpdateResponse
from app.security.service_auth import SERVICE_TOKEN_HEADER
from app.security.staff_context import StaffContext
from app.security.tokens import create_access_token
from app.services.admin_catalog_service import AdminCatalogService
from app.services.staff_access_service import StaffAccessService
from tests.test_admin_departments_warmup_http import FakeAdminRepository, FakeIdempotency
from tests.test_admin_ops_rbac_api import StubAudit
from tests.test_current_staff_resolution import FakeAuthRepository

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)
TEST_JWT_SECRET = "test-only-signing-key-not-production-0123456789abcdef"
MCP_TOKEN = "mcp-server-test-token-0123456789abcdef0123"
NATIONAL_ID = "29001011234567"  # synthetic


def _provider(key, tz):
    return SimpleNamespace(
        id=uuid4(), tenant_key=key, name=f"Clinic {key}", slug=key, org_type="clinic",
        verification_status="verified", default_language="ar", timezone=tz, currency_code="EGP",
        phone=None, email=None, address=None, is_active=True,
    )


PROVIDER_A = _provider("clinic-001", "Africa/Cairo")
PROVIDER_B = _provider("clinic-002", "Asia/Riyadh")
PROVIDERS = {"clinic-001": PROVIDER_A, "clinic-002": PROVIDER_B}


def _code(response):
    return response.json()["detail"]["code"]


# ============================================================ catalog fakes


class FakeCatalog:
    def __init__(self):
        self.calls = []
        self.branch_a = SimpleNamespace(id=uuid4(), name_ar="الفرع", name_en="Main branch")
        self.specialties = {
            PROVIDER_A.id: [self._specialty(PROVIDER_A, "DERM"), self._specialty(PROVIDER_A, "CARD")],
            PROVIDER_B.id: [self._specialty(PROVIDER_B, "ENT")],
        }
        self.slots = {
            PROVIDER_A.id: [self._slot(PROVIDER_A, self.branch_a.id), self._slot(PROVIDER_A, uuid4())],
            PROVIDER_B.id: [],
        }

    @staticmethod
    def _specialty(provider, code):
        return SimpleNamespace(id=uuid4(), provider_id=provider.id, code=code, name_ar="تخصص",
                               name_en=f"Specialty {code}", description_ar=None, description_en=None,
                               is_active=True)

    @staticmethod
    def _slot(provider, branch_id):
        return SimpleNamespace(id=uuid4(), provider_id=provider.id, doctor_id=uuid4(), branch_id=branch_id,
                               slot_date=date(2026, 11, 2), start_time=time(10, 0), end_time=time(10, 30),
                               status="available")

    def get_provider(self, tenant_key):
        return PROVIDERS.get(tenant_key)

    def get_specialties(self, provider_id):
        self.calls.append(("get_specialties", provider_id))
        return self.specialties.get(provider_id, [])

    def get_available_slots(self, **kwargs):
        self.calls.append(("get_available_slots", kwargs))
        return self.slots.get(kwargs["provider_id"], [])

    def get_branches(self, provider_id):
        self.calls.append(("get_branches", provider_id))
        return [self.branch_a] if provider_id == PROVIDER_A.id else []


@pytest.fixture
def catalog_api():
    fake = FakeCatalog()
    app = FastAPI()
    app.include_router(catalog.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_catalog_service] = lambda: fake
    client = TestClient(app)

    def get(path, tenant="clinic-001", **params):
        headers = {} if tenant is None else {"X-Tenant-ID": tenant}
        return client.get(path, headers=headers, params=params)

    return SimpleNamespace(get=get, catalog=fake)


# ============================================================ GET /providers/current


def test_current_provider_returns_the_resolved_tenant(catalog_api):
    response = catalog_api.get("/api/v1/providers/current", tenant="clinic-002")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == set(ProviderOut.model_fields)
    assert (UUID(body["id"]), body["tenant_key"], body["timezone"]) == (PROVIDER_B.id, "clinic-002", "Asia/Riyadh")


@pytest.mark.parametrize("tenant, status_code", [("no-such-clinic", 404), (None, 422), ("x" * 101, 422)])
def test_current_provider_requires_a_known_valid_tenant(catalog_api, tenant, status_code):
    response = catalog_api.get("/api/v1/providers/current", tenant=tenant)

    assert response.status_code == status_code
    if status_code == 404:
        assert _code(response) == "PROVIDER_NOT_FOUND"


# ============================================================ GET /specialties


def test_specialties_are_scoped_to_the_tenant_with_the_contract(catalog_api):
    a = catalog_api.get("/api/v1/specialties", tenant="clinic-001")
    b = catalog_api.get("/api/v1/specialties", tenant="clinic-002")

    assert a.status_code == b.status_code == 200
    assert {s["code"] for s in a.json()} == {"DERM", "CARD"}
    assert {s["code"] for s in b.json()} == {"ENT"}
    assert set(a.json()[0]) == set(SpecialtyOut.model_fields)
    assert catalog_api.catalog.calls == [("get_specialties", PROVIDER_A.id), ("get_specialties", PROVIDER_B.id)]


def test_specialties_can_be_empty(catalog_api):
    catalog_api.catalog.specialties[PROVIDER_B.id] = []

    response = catalog_api.get("/api/v1/specialties", tenant="clinic-002")

    assert response.status_code == 200
    assert response.json() == []


# ============================================================ GET /slots


def test_slots_return_the_contract_with_branch_names(catalog_api):
    doctor_id = uuid4()

    response = catalog_api.get("/api/v1/slots", slot_date="2026-11-02", doctor_id=str(doctor_id), limit=5)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2 and set(body[0]) == set(SlotOut.model_fields)
    named = [s for s in body if s["branch_id"] == str(catalog_api.catalog.branch_a.id)]
    assert named[0]["branch_name_en"] == "Main branch"
    unnamed = [s for s in body if s["branch_id"] != str(catalog_api.catalog.branch_a.id)]
    assert unnamed[0]["branch_name_en"] is None  # branch not in this tenant's list
    (_, kwargs), = [c for c in catalog_api.catalog.calls if c[0] == "get_available_slots"]
    assert kwargs == {"provider_id": PROVIDER_A.id, "slot_date": date(2026, 11, 2), "doctor_id": doctor_id,
                      "branch_id": None, "limit": 5}


def test_slots_are_scoped_to_the_tenant_and_default_limit_100(catalog_api):
    response = catalog_api.get("/api/v1/slots", tenant="clinic-002", slot_date="2026-11-02")

    assert response.status_code == 200
    assert response.json() == []
    (_, kwargs), = [c for c in catalog_api.catalog.calls if c[0] == "get_available_slots"]
    assert (kwargs["provider_id"], kwargs["limit"]) == (PROVIDER_B.id, 100)


@pytest.mark.parametrize("limit", [1, 200])
def test_slot_limit_bounds_are_inclusive(catalog_api, limit):
    assert catalog_api.get("/api/v1/slots", slot_date="2026-11-02", limit=limit).status_code == 200


@pytest.mark.parametrize(
    "params",
    [{}, {"slot_date": "not-a-date"}, {"slot_date": "2026-11-02", "limit": 0},
     {"slot_date": "2026-11-02", "limit": 201}, {"slot_date": "2026-11-02", "doctor_id": "nope"},
     {"slot_date": "2026-11-02", "branch_id": "nope"}],
)
def test_invalid_slot_queries_are_422(catalog_api, params):
    response = catalog_api.get("/api/v1/slots", **params)

    assert response.status_code == 422
    assert catalog_api.catalog.calls == []


# ============================================================ GET /audit-events


class FakeOps:
    def __init__(self):
        self.calls = []
        self.rows = []

    def list_audit_events(self, **kwargs):
        self.calls.append(kwargs)
        return self.rows


@pytest.fixture
def audit_api():
    staff = StaffContext(user_id=uuid4(), membership_id=uuid4(), provider_id=PROVIDER_A.id,
                         role="provider_admin", doctor_id=None)
    ops_repo, audit = FakeOps(), StubAudit()
    app = FastAPI()
    app.include_router(ops.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_current_staff] = lambda: staff  # staff auth: test_admin_ops_rbac_api
    app.dependency_overrides[deps.get_ops_repository] = lambda: ops_repo
    app.dependency_overrides[deps.get_staff_audit_service] = lambda: audit
    client = TestClient(app)
    return SimpleNamespace(get=lambda **p: client.get("/api/v1/audit-events", params=p),
                           ops=ops_repo, audit=audit, staff=staff)


def test_audit_events_pass_every_filter_and_default_limit(audit_api):
    user_id = uuid4()

    audit_api.get(created_from="2026-10-01T00:00:00Z", created_to="2026-10-31T23:59:59Z",
                  action="doctor.create", user_id=str(user_id))
    audit_api.get()

    first, second = audit_api.ops.calls
    assert first["provider_id"] == PROVIDER_A.id
    assert first["created_from"] == datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert first["created_to"] == datetime(2026, 10, 31, 23, 59, 59, tzinfo=timezone.utc)
    assert (first["action"], first["user_id"], first["limit"]) == ("doctor.create", user_id, 50)
    assert second == {"provider_id": PROVIDER_A.id, "created_from": None, "created_to": None,
                      "action": None, "user_id": None, "limit": 50}


def test_audit_events_empty_result_is_still_audited(audit_api):
    response = audit_api.get()

    assert response.status_code == 200
    assert response.json() == []
    assert [r["action"] for r in audit_api.audit.records] == ["audit_events.read"]


def test_audit_events_response_shape(audit_api):
    audit_api.ops.rows = [SimpleNamespace(
        id=uuid4(), provider_id=PROVIDER_A.id, user_id=uuid4(), membership_id=uuid4(), patient_id=None,
        action="appointment.confirm", resource_type="appointment", resource_id="r-1", outcome="success",
        created_at=NOW,
    )]

    response = audit_api.get()

    assert set(response.json()[0]) == set(AuditEventOut.model_fields)


@pytest.mark.parametrize("limit", [1, 200])
def test_audit_event_limit_bounds_are_inclusive(audit_api, limit):
    assert audit_api.get(limit=limit).status_code == 200
    assert audit_api.ops.calls[0]["limit"] == limit


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 201}, {"limit": "many"}, {"created_from": "yesterday"}, {"created_to": "2026-13-01"},
     {"user_id": "not-a-uuid"}, {"action": ""}, {"action": "Doctor.Create"}, {"action": "a" * 101}],
)
def test_invalid_audit_event_queries_are_422(audit_api, params):
    response = audit_api.get(**params)

    assert response.status_code == 422
    assert audit_api.ops.calls == [] and audit_api.audit.records == []


@pytest.mark.parametrize(
    "created_from, created_to",
    [
        ("2026-10-31T00:00:00Z", "2026-10-01T00:00:00Z"),            # reversed, UTC
        ("2026-10-31T00:00:00", "2026-10-01T00:00:00"),              # reversed, no offset
        ("2026-10-01T10:00:00+00:00", "2026-10-01T12:00:00+03:00"),  # 10:00Z then 09:00Z
        ("2026-10-01T00:00:00Z", "2026-10-31T00:00:00"),             # offset on one bound only
        ("2026-10-01T00:00:00", "2026-10-31T00:00:00+02:00"),
    ],
    ids=["reversed-utc", "reversed-naive", "reversed-across-offsets", "mixed-aware-naive", "mixed-naive-aware"],
)
def test_invalid_audit_event_ranges_are_422_before_the_repository(audit_api, created_from, created_to):
    response = audit_api.get(created_from=created_from, created_to=created_to)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_DATE_RANGE"
    assert created_from not in response.text and created_to not in response.text
    assert audit_api.ops.calls == [] and audit_api.audit.records == []


@pytest.mark.parametrize(
    "created_from, created_to, expected_from, expected_to",
    [
        # Equal bounds stay valid (the repository window is created_from <= t < created_to).
        ("2026-10-01T00:00:00Z", "2026-10-01T00:00:00Z",
         datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 10, 1, tzinfo=timezone.utc)),
        ("2026-10-01T00:00:00", "2026-10-01T00:00:00", datetime(2026, 10, 1), datetime(2026, 10, 1)),
        # The same instant written with different offsets is equal, not reversed.
        ("2026-10-01T03:00:00+03:00", "2026-10-01T00:00:00Z",
         datetime(2026, 10, 1, 3, tzinfo=timezone(timedelta(hours=3))), datetime(2026, 10, 1, tzinfo=timezone.utc)),
        # Ordered ranges, both with offsets or both without.
        ("2026-10-01T10:00:00+03:00", "2026-10-01T08:00:00Z",
         datetime(2026, 10, 1, 10, tzinfo=timezone(timedelta(hours=3))),
         datetime(2026, 10, 1, 8, tzinfo=timezone.utc)),
        ("2026-10-01T00:00:00", "2026-10-31T00:00:00", datetime(2026, 10, 1), datetime(2026, 10, 31)),
    ],
    ids=["equal-utc", "equal-naive", "equal-across-offsets", "ordered-across-offsets", "ordered-naive"],
)
def test_valid_audit_event_ranges_reach_the_repository_and_are_audited(
    audit_api, created_from, created_to, expected_from, expected_to,
):
    response = audit_api.get(created_from=created_from, created_to=created_to)

    assert response.status_code == 200
    (call,) = audit_api.ops.calls
    assert call["provider_id"] == audit_api.staff.provider_id
    assert (call["created_from"], call["created_to"]) == (expected_from, expected_to)
    assert [r["action"] for r in audit_api.audit.records] == ["audit_events.read"]


@pytest.mark.parametrize(
    "params",
    [{"created_from": "2026-10-01T00:00:00Z"}, {"created_from": "2026-10-01T00:00:00"},
     {"created_to": "2026-10-01T00:00:00Z"}, {"created_to": "2026-10-01T00:00:00"}],
    ids=["from-utc-only", "from-naive-only", "to-utc-only", "to-naive-only"],
)
def test_a_single_audit_event_bound_needs_no_comparison(audit_api, params):
    assert audit_api.get(**params).status_code == 200
    assert len(audit_api.ops.calls) == 1


# ============================================================ /patients/lookup and /profile


class FakePatientService:
    def __init__(self):
        self.calls = []
        self.found = True
        self.error = None
        self.patient_id = uuid4()

    def lookup(self, **kwargs):
        self.calls.append(("lookup", kwargs))
        if not self.found:
            return None
        return PatientLookupResult(patient_id=self.patient_id, patient_code="P-TEST-0001",
                                   display_name="Test Patient", masked_national_id="**********4567",
                                   phone="+20100000000")

    def update_profile(self, **kwargs):
        self.calls.append(("update_profile", kwargs))
        if self.error is not None:
            raise self.error
        return PatientProfileUpdateResponse(patient_id=kwargs["patient_id"], display_name="Test Patient",
                                            phone="+20100000000", updated_fields=["patient_name"])


@pytest.fixture
def patient_api(monkeypatch):
    monkeypatch.setenv("MEDMIND_SERVICE_CREDENTIALS", f"mcp_server={MCP_TOKEN}@clinic-001,clinic-002")
    monkeypatch.setenv("BOOKING_SERVICE_AUTH_MODE", "enforce")
    get_settings.cache_clear()
    service = FakePatientService()
    app = FastAPI()
    app.include_router(patients.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_catalog_service] = lambda: FakeCatalog()
    app.dependency_overrides[deps.get_patient_service] = lambda: service
    client = TestClient(app)

    def call(method, path, body, tenant="clinic-001"):
        return client.request(method, path, json=body,
                              headers={"X-Tenant-ID": tenant, SERVICE_TOKEN_HEADER: MCP_TOKEN})

    yield SimpleNamespace(call=call, service=service)
    get_settings.cache_clear()


LOOKUP = "/api/v1/patients/lookup"


@pytest.mark.parametrize("tenant, provider", [("clinic-001", PROVIDER_A), ("clinic-002", PROVIDER_B)])
def test_patient_lookup_found_shape_and_provider_passthrough(patient_api, tenant, provider):
    response = patient_api.call("POST", LOOKUP, {"national_id": NATIONAL_ID, "language": "en"}, tenant=tenant)

    assert response.status_code == 200
    body = response.json()
    assert body["found"] is True
    assert set(body["patient"]) == set(PatientLookupResult.model_fields)
    assert body["patient"]["masked_national_id"] == "**********4567"
    assert NATIONAL_ID not in response.text
    assert patient_api.service.calls == [("lookup", {"provider_id": provider.id, "national_id": NATIONAL_ID,
                                                     "language": "en"})]


def test_patient_lookup_not_found(patient_api):
    patient_api.service.found = False

    response = patient_api.call("POST", LOOKUP, {"national_id": NATIONAL_ID})

    assert response.json() == {"found": False, "patient": None}
    assert patient_api.service.calls[0][1]["language"] == "ar"  # default


@pytest.mark.parametrize("body", [{}, {"national_id": "123"}, {"national_id": NATIONAL_ID + "1"},
                                  {"national_id": NATIONAL_ID, "language": "fr"}])
def test_patient_lookup_validation(patient_api, body):
    assert patient_api.call("POST", LOOKUP, body).status_code == 422
    assert patient_api.service.calls == []


def _profile_path(patient_id=None):
    return f"/api/v1/patients/{patient_id or uuid4()}/profile"


def _profile_body(**overrides):
    return {"national_id": NATIONAL_ID, "patient_name": "Test Patient", "language": "ar", "channel": "voice",
            **overrides}


def test_profile_update_success_and_passthrough(patient_api):
    patient_id = uuid4()

    response = patient_api.call("PATCH", _profile_path(patient_id), _profile_body(phone="+20111111111"),
                                tenant="clinic-002")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == set(PatientProfileUpdateResponse.model_fields)
    assert UUID(body["patient_id"]) == patient_id
    assert NATIONAL_ID not in response.text
    (_, kwargs), = patient_api.service.calls
    assert kwargs == {"provider_id": PROVIDER_B.id, "patient_id": patient_id, "national_id": NATIONAL_ID,
                      "patient_name": "Test Patient", "phone": "+20111111111", "language": "ar", "channel": "voice"}


def test_profile_update_with_only_a_phone_is_accepted(patient_api):
    body = _profile_body(phone="+20111111111")
    body.pop("patient_name")

    assert patient_api.call("PATCH", _profile_path(), body).status_code == 200


@pytest.mark.parametrize(
    "overrides, drop",
    [
        ({}, ["patient_name"]),  # no patient field to change (language alone does not count)
        ({"patient_name": None, "phone": None}, []),
        ({}, ["language"]),
        ({}, ["channel"]),
        ({"language": "fr"}, []),
        ({"channel": "sms"}, []),
        ({"patient_name": "X"}, []),
        ({"patient_name": "x" * 201}, []),
        ({"national_id": "123"}, []),
        ({}, ["national_id"]),
    ],
)
def test_profile_update_validation(patient_api, overrides, drop):
    body = _profile_body(**overrides)
    for key in drop:
        body.pop(key)

    response = patient_api.call("PATCH", _profile_path(), body)

    assert response.status_code == 422
    assert patient_api.service.calls == []


def test_profile_update_rejects_a_malformed_patient_id(patient_api):
    assert patient_api.call("PATCH", "/api/v1/patients/not-a-uuid/profile", _profile_body()).status_code == 422


def test_profile_update_service_errors_keep_their_contract(patient_api):
    patient_api.service.error = HTTPException(status_code=404, detail={"code": "PATIENT_NOT_FOUND",
                                                                        "message": "fake"})

    response = patient_api.call("PATCH", _profile_path(), _profile_body())

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "PATIENT_NOT_FOUND", "message": "fake"}}


# ============================================================ POST /admin/doctors (real service)


class DoctorRepository(FakeAdminRepository):
    def __init__(self):
        super().__init__()
        self.branches = set()  # (provider_id, branch_id)
        self.services = set()  # (provider_id, service_id)
        self.licenses = set()  # (provider_id, license)

    def active_branch_ids(self, provider_id, ids):
        return {i for i in ids if (provider_id, i) in self.branches}

    def active_service_ids(self, provider_id, ids):
        return {i for i in ids if (provider_id, i) in self.services}

    def license_exists(self, provider_id, license_number):
        return (provider_id, license_number) in self.licenses


@pytest.fixture
def doctor_api():
    repository, audit = DoctorRepository(), StubAudit()
    idempotency = FakeIdempotency()
    staff = StaffContext(user_id=uuid4(), membership_id=uuid4(), provider_id=PROVIDER_A.id,
                         role="provider_admin", doctor_id=None)
    app = FastAPI()
    app.include_router(admin_catalog.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_catalog_service] = lambda: FakeCatalog()
    app.dependency_overrides[deps.get_admin_catalog_service] = lambda: AdminCatalogService(
        repository, idempotency_service=idempotency
    )
    app.dependency_overrides[deps.get_staff_audit_service] = lambda: audit
    app.dependency_overrides[deps.get_current_staff] = lambda: staff  # staff auth: test_admin_ops_rbac_api
    client = TestClient(app)

    specialty, branch, branch2, service = uuid4(), uuid4(), uuid4(), uuid4()
    repository.specialties.add((PROVIDER_A.id, specialty))
    repository.branches |= {(PROVIDER_A.id, branch), (PROVIDER_A.id, branch2)}
    repository.services.add((PROVIDER_A.id, service))

    def body(**overrides):
        return {"specialty_id": str(specialty), "full_name_ar": "د. اختبار", "full_name_en": "Dr Test",
                "branch_ids": [str(branch), str(branch2)], "service_ids": [str(service)], **overrides}

    def post(data, key=None):
        headers = {"X-Tenant-ID": "clinic-001"}
        if key:
            headers["Idempotency-Key"] = key
        return client.post("/api/v1/admin/doctors", json=data, headers=headers)

    return SimpleNamespace(post=post, body=body, repository=repository, audit=audit,
                           ids=SimpleNamespace(specialty=specialty, branch=branch, branch2=branch2, service=service))


def _doctor_rows(repository):
    return [r for r in repository.added if type(r).__name__ == "Doctor"]


def test_create_doctor_saves_links_and_returns_pending(doctor_api):
    response = doctor_api.post(doctor_api.body(license_number=" LIC-1 "))

    assert response.status_code == 201
    body = response.json()
    assert (body["verification_status"], body["is_active"], body["license_number"]) == ("pending", True, "LIC-1")
    added = [type(r).__name__ for r in doctor_api.repository.added]
    assert added.count("Doctor") == 1 and added.count("DoctorBranch") == 2 and added.count("DoctorService") == 1
    primary = [r for r in doctor_api.repository.added if type(r).__name__ == "DoctorBranch" and r.is_primary]
    assert [p.branch_id for p in primary] == [doctor_api.ids.branch]  # the first branch is primary
    assert doctor_api.repository.session.commits == 1
    assert [r["action"] for r in doctor_api.audit.records] == ["doctor.create"]


@pytest.mark.parametrize("field", ["branch_ids", "service_ids"])
def test_duplicate_links_are_rejected(doctor_api, field):
    same = str(uuid4())

    response = doctor_api.post(doctor_api.body(**{field: [same, same]}))

    assert response.status_code == 422
    assert f"{field} must be unique" in response.text
    assert doctor_api.repository.added == []


@pytest.mark.parametrize(
    "override, code",
    [
        ("specialty", "SPECIALTY_NOT_FOUND"),
        ("branch", "BRANCH_NOT_FOUND"),
        ("service", "SERVICE_NOT_FOUND"),
    ],
)
def test_foreign_or_unknown_references_are_404(doctor_api, override, code):
    foreign = str(uuid4())
    field = {"specialty": ("specialty_id", foreign), "branch": ("branch_ids", [foreign]),
             "service": ("service_ids", [foreign])}[override]

    response = doctor_api.post(doctor_api.body(**{field[0]: field[1]}))

    assert response.status_code == 404
    assert _code(response) == code
    assert _doctor_rows(doctor_api.repository) == []
    assert doctor_api.repository.session.commits == 0 and doctor_api.audit.records == []


def test_one_foreign_branch_among_valid_ones_is_404(doctor_api):
    response = doctor_api.post(doctor_api.body(branch_ids=[str(doctor_api.ids.branch), str(uuid4())]))

    assert response.status_code == 404
    assert _code(response) == "BRANCH_NOT_FOUND"


def test_an_existing_license_is_409(doctor_api):
    doctor_api.repository.licenses.add((PROVIDER_A.id, "LIC-1"))

    response = doctor_api.post(doctor_api.body(license_number="LIC-1"))

    assert response.status_code == 409
    assert _code(response) == "DOCTOR_LICENSE_EXISTS"
    assert _doctor_rows(doctor_api.repository) == []


def test_a_blank_license_is_stored_as_none_and_never_conflicts(doctor_api):
    doctor_api.repository.licenses.add((PROVIDER_A.id, ""))

    response = doctor_api.post(doctor_api.body(license_number="   "))

    assert response.status_code == 201
    assert response.json()["license_number"] is None


def test_a_retried_doctor_create_replays_the_first_response(doctor_api):
    first = doctor_api.post(doctor_api.body(), key="doctor-create-0001")
    second = doctor_api.post(doctor_api.body(), key="doctor-create-0001")

    assert (first.status_code, second.status_code) == (201, 201)
    assert second.json() == first.json()
    assert len(_doctor_rows(doctor_api.repository)) == 1
    assert len(doctor_api.audit.records) == 1


def test_reusing_a_doctor_key_with_another_body_is_409(doctor_api):
    doctor_api.post(doctor_api.body(), key="doctor-create-0002")

    response = doctor_api.post(doctor_api.body(full_name_en="Dr Other"), key="doctor-create-0002")

    assert response.status_code == 409
    assert _code(response) == "IDEMPOTENCY_CONFLICT"
    assert len(_doctor_rows(doctor_api.repository)) == 1


@pytest.mark.parametrize(
    "overrides",
    [{"branch_ids": []}, {"full_name_en": "X"}, {"experience_years": 81}, {"consultation_fee": "-1"},
     {"gender": "other"}, {"specialty_id": "nope"}],
)
def test_invalid_doctor_payloads_are_422(doctor_api, overrides):
    assert doctor_api.post(doctor_api.body(**overrides)).status_code == 422
    assert doctor_api.repository.added == []


# ============================================================ GET /auth/me


@pytest.fixture
def me_api(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    get_settings.cache_clear()
    state = SimpleNamespace(access=None)
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_catalog_service] = lambda: FakeCatalog()
    app.dependency_overrides[deps.get_staff_access_service] = lambda: state.access or object()
    client = TestClient(app)

    def login_as(role, provider=PROVIDER_A, *, active=True, user_active=True):
        user = SimpleNamespace(id=uuid4())
        membership = SimpleNamespace(id=uuid4(), provider_id=provider.id, role=role,
                                     doctor_id=uuid4() if role == "doctor" else None)
        state.access = StaffAccessService(FakeAuthRepository(user=user if user_active else None,
                                                             membership=membership if active else None))
        token = create_access_token(user_id=user.id, membership_id=membership.id, provider_id=provider.id)
        return token, user, membership

    def me(token=None, tenant="clinic-001"):
        headers = {"X-Tenant-ID": tenant}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return client.get("/api/v1/auth/me", headers=headers)

    yield SimpleNamespace(login_as=login_as, me=me)
    get_settings.cache_clear()


@pytest.mark.parametrize("role", ["provider_admin", "doctor", "receptionist", "lab_staff"])
def test_auth_me_returns_the_verified_staff_context(me_api, role):
    token, user, membership = me_api.login_as(role)

    response = me_api.me(token)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"user_id", "membership_id", "provider_id", "role", "doctor_id"}
    assert (UUID(body["user_id"]), UUID(body["membership_id"]), UUID(body["provider_id"]), body["role"]) == (
        user.id, membership.id, PROVIDER_A.id, role)
    assert (body["doctor_id"] is not None) == (role == "doctor")
    assert token not in response.text


@pytest.mark.parametrize("token, code", [(None, "STAFF_AUTH_REQUIRED"), ("not-a-jwt", "INVALID_ACCESS_TOKEN")])
def test_auth_me_rejects_missing_or_invalid_tokens(me_api, token, code):
    me_api.login_as("receptionist")

    response = me_api.me(token)

    assert response.status_code == 401
    assert _code(response) == code


def test_auth_me_rejects_a_token_for_another_tenant(me_api):
    token, _, _ = me_api.login_as("provider_admin", provider=PROVIDER_A)

    response = me_api.me(token, tenant="clinic-002")

    assert response.status_code == 403
    assert _code(response) == "STAFF_TENANT_MISMATCH"


@pytest.mark.parametrize("kwargs", [{"active": False}, {"user_active": False}])
def test_auth_me_rejects_an_inactive_membership_or_account(me_api, kwargs):
    token, _, _ = me_api.login_as("receptionist", **kwargs)

    response = me_api.me(token)

    assert response.status_code == 401
    assert _code(response) == "INVALID_STAFF_SESSION"


def test_auth_me_requires_a_known_tenant(me_api):
    token, _, _ = me_api.login_as("receptionist")

    assert me_api.me(token, tenant="no-such-clinic").status_code == 404
