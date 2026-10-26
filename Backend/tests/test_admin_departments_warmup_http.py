"""HTTP contracts for provider-admin writes, the working-hours list,
departments and the AI warm-up (API coverage audit, package 3).

Complements, without repeating:
- test_admin_ops_rbac_api.py: 401/403 and audit staging for the admin routes;
- test_security_hardening.py: AdminCatalogService audit/rollback units;
- test_department_specialties.py / test_departments.py: department links and
  the department service/model;
- test_gateway_service_policy.py / test_ai_chat_service_auth.py: /ai/* caller
  policy in depth.

Real routers, schemas and validators. The admin-catalog routes run the REAL
AdminCatalogService over an in-memory repository and a fake idempotency
service, so its error codes are the real ones. The catalog, working-hours
service, AI registry and planner are fakes. No database, network or AI.
"""

import json
import logging
from datetime import datetime, time, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

from app.api import dependencies as deps
from app.api.routers import admin_catalog, admin_working_hours, catalog, medmind_ai
from app.core.config import get_settings
from app.core.idempotency_exceptions import IdempotencyConflictError
from app.schemas.catalog import DepartmentOut, ServiceOut
from app.schemas.working_hours import SlotGenerationResult, WorkingHourOut
from app.security.service_auth import SERVICE_TOKEN_HEADER
from app.security.staff_context import StaffContext
from app.services.admin_catalog_service import AdminCatalogService
from tests.test_admin_ops_rbac_api import StubAudit

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)
PROVIDER_A = SimpleNamespace(id=uuid4(), tenant_key="clinic-001", timezone="Africa/Cairo",
                             org_type="clinic", name="Clinic A")
PROVIDER_B = SimpleNamespace(id=uuid4(), tenant_key="clinic-002", timezone="Asia/Riyadh",
                             org_type="clinic", name="Clinic B")
PROVIDERS = {"clinic-001": PROVIDER_A, "clinic-002": PROVIDER_B}


def _code(response):
    return response.json()["detail"]["code"]


# ============================================================ fakes


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeAdminRepository:
    """In-memory stand-in for AdminCatalogRepository (same method names)."""

    def __init__(self):
        self.session = FakeSession()
        self.added = []
        self.specialties = set()  # (provider_id, specialty_id)
        self.service_codes = set()  # (provider_id, code)
        self.doctors = {}  # (provider_id, doctor_id) -> doctor

    def active_specialty_ids(self, provider_id, ids):
        return {i for i in ids if (provider_id, i) in self.specialties}

    def service_code_exists(self, provider_id, code):
        return (provider_id, code) in self.service_codes

    def get_doctor(self, provider_id, doctor_id):
        return self.doctors.get((provider_id, doctor_id))

    def doctor_link_ids(self, provider_id, doctor_id):
        return [], []

    def add(self, row):
        self.added.append(row)

    def flush(self):
        pass


class FakeIdempotency:
    """Same contract as IdempotencyService.begin: replay, conflict, or a new record."""

    def __init__(self):
        self.records = {}  # (tenant, operation, key) -> (payload, record)

    def begin(self, db, *, tenant_id, operation, idempotency_key, payload):
        slot = (tenant_id, operation, idempotency_key)
        if slot in self.records:
            stored_payload, record = self.records[slot]
            if stored_payload != payload:
                raise IdempotencyConflictError("different payload")
            return SimpleNamespace(is_replay=True, record=record,
                                   cached_response=json.loads(record.response_body))
        record = SimpleNamespace()
        self.records[slot] = (payload, record)
        return SimpleNamespace(is_replay=False, record=record, cached_response=None)


def _doctor(provider):
    return SimpleNamespace(
        id=uuid4(), provider_id=provider.id, specialty_id=uuid4(), full_name_ar="د. اختبار",
        full_name_en="Dr Test", license_number=None, consultation_fee=None, experience_years=3,
        gender=None, accepting_new_patients=True, verification_status="pending", is_active=True,
        updated_at=NOW,
    )


class FakeWorkingHoursService:
    def __init__(self):
        self.calls = []
        self.rows = {
            PROVIDER_A.id: [self._row(PROVIDER_A, 0), self._row(PROVIDER_A, 2)],
            PROVIDER_B.id: [self._row(PROVIDER_B, 4)],
        }

    @staticmethod
    def _row(provider, day):
        return SimpleNamespace(
            id=uuid4(), provider_id=provider.id, doctor_id=uuid4(), branch_id=uuid4(), day_of_week=day,
            start_time=time(9, 0), end_time=time(12, 0), slot_duration_minutes=30, is_active=True,
            created_at=NOW, updated_at=NOW,
        )

    def list(self, provider_id, doctor_id=None, branch_id=None, day_of_week=None):
        self.calls.append(("list", dict(provider_id=provider_id, doctor_id=doctor_id,
                                        branch_id=branch_id, day_of_week=day_of_week)))
        return [r for r in self.rows.get(provider_id, []) if day_of_week is None or r.day_of_week == day_of_week]

    def create(self, provider_id, data, audit=None):
        self.calls.append(("create", dict(provider_id=provider_id, data=data)))
        if audit is not None:
            audit("hour-id")
        return SimpleNamespace(
            id=uuid4(), provider_id=provider_id, doctor_id=data.doctor_id, branch_id=data.branch_id,
            day_of_week=data.day_of_week, start_time=data.start_time, end_time=data.end_time,
            slot_duration_minutes=data.slot_duration_minutes, is_active=True, created_at=NOW, updated_at=NOW,
        )

    def generate_slots(self, provider_id, provider_timezone, data, audit=None):
        self.calls.append(("generate", dict(provider_id=provider_id, provider_timezone=provider_timezone, data=data)))
        if audit is not None:
            audit(None)
        return SlotGenerationResult(
            provider_id=provider_id, date_from=data.date_from, date_to=data.date_to,
            working_hours_used=2, created_slots=12, skipped_existing_slots=1,
        )


class FakeCatalog:
    def __init__(self):
        self.calls = []
        self.departments = {
            PROVIDER_A.id: [self._dept(PROVIDER_A, "CARD", None), self._dept(PROVIDER_A, "LAB", BRANCH_A1)],
            PROVIDER_B.id: [self._dept(PROVIDER_B, "DERM", None)],
        }

    @staticmethod
    def _dept(provider, code, branch_id):
        return SimpleNamespace(
            id=uuid4(), provider_id=provider.id, branch_id=branch_id, code=code, name_ar="قسم",
            name_en=f"Dept {code}", description_ar=None, description_en=None, phone=None, is_active=True,
        )

    def get_provider(self, tenant_key):
        return PROVIDERS.get(tenant_key)

    def get_departments(self, provider_id, branch_id=None):
        self.calls.append(("get_departments", provider_id, branch_id))
        rows = self.departments.get(provider_id, [])
        # Provider-wide departments (no branch) apply to every branch.
        return [r for r in rows if branch_id is None or r.branch_id in (None, branch_id)]


BRANCH_A1 = uuid4()


# ============================================================ admin fixture


@pytest.fixture
def admin():
    repository, idempotency = FakeAdminRepository(), FakeIdempotency()
    hours, catalog_service, audit = FakeWorkingHoursService(), FakeCatalog(), StubAudit()
    staff = {"value": StaffContext(user_id=uuid4(), membership_id=uuid4(), provider_id=PROVIDER_A.id,
                                   role="provider_admin", doctor_id=None)}

    app = FastAPI()
    for router in (admin_catalog.router, admin_working_hours.router, catalog.router):
        app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[deps.get_catalog_service] = lambda: catalog_service
    app.dependency_overrides[deps.get_admin_catalog_service] = lambda: AdminCatalogService(
        repository, idempotency_service=idempotency
    )
    app.dependency_overrides[deps.get_working_hours_service] = lambda: hours
    app.dependency_overrides[deps.get_staff_audit_service] = lambda: audit
    # Staff auth itself is covered in test_admin_ops_rbac_api.py.
    app.dependency_overrides[deps.get_current_staff] = lambda: staff["value"]
    client = TestClient(app)

    def call(method, path, body=None, *, tenant="clinic-001", key=None, params=None):
        headers = {"X-Tenant-ID": tenant}
        if key is not None:
            headers["Idempotency-Key"] = key
        return client.request(method, path, headers=headers, json=body, params=params)

    return SimpleNamespace(call=call, repository=repository, hours=hours, catalog=catalog_service,
                           audit=audit, staff=staff)


SERVICES = "/api/v1/admin/services"


def _service_body(**overrides):
    return {"code": "NEW_SVC", "name_ar": "خدمة جديدة", "name_en": "New service", "duration_minutes": 20,
            **overrides}


# ============================================================ POST /admin/services


def test_create_service_returns_201_with_the_service_contract(admin):
    specialty = uuid4()
    admin.repository.specialties.add((PROVIDER_A.id, specialty))

    response = admin.call("POST", SERVICES, _service_body(price="150.00", specialty_ids=[str(specialty)]))

    assert response.status_code == 201
    body = response.json()
    assert set(body) == set(ServiceOut.model_fields)
    assert (body["code"], body["service_type"], body["duration_minutes"], body["is_active"]) == (
        "NEW_SVC", "consultation", 20, True)
    assert UUID(body["provider_id"]) == PROVIDER_A.id
    assert admin.repository.session.commits == 1
    assert [r["action"] for r in admin.audit.records] == ["service.create"]


def test_duplicate_specialty_ids_are_rejected_by_reject_duplicates(admin):
    specialty = str(uuid4())

    response = admin.call("POST", SERVICES, _service_body(specialty_ids=[specialty, specialty]))

    assert response.status_code == 422
    assert "specialty_ids must be unique" in response.text
    assert admin.repository.added == []


@pytest.mark.parametrize(
    "overrides",
    [{"code": "lower_case"}, {"code": "A"}, {"code": "-BAD"}, {"name_en": "X"}, {"duration_minutes": 4},
     {"duration_minutes": 481}, {"service_type": "lab_test"}, {"price": "-1"}, {"specialty_ids": ["nope"]}],
)
def test_invalid_service_fields_are_422(admin, overrides):
    response = admin.call("POST", SERVICES, _service_body(**overrides))

    assert response.status_code == 422
    assert admin.repository.added == []


def test_an_existing_service_code_is_409(admin):
    admin.repository.service_codes.add((PROVIDER_A.id, "NEW_SVC"))

    response = admin.call("POST", SERVICES, _service_body())

    assert response.status_code == 409
    assert _code(response) == "SERVICE_CODE_EXISTS"
    assert admin.repository.session.commits == 0 and admin.audit.records == []


def test_the_same_code_in_another_provider_is_allowed(admin):
    admin.repository.service_codes.add((PROVIDER_B.id, "NEW_SVC"))

    assert admin.call("POST", SERVICES, _service_body()).status_code == 201


def test_another_providers_specialty_is_404(admin):
    foreign = uuid4()
    admin.repository.specialties.add((PROVIDER_B.id, foreign))

    response = admin.call("POST", SERVICES, _service_body(specialty_ids=[str(foreign)]))

    assert response.status_code == 404
    assert _code(response) == "SPECIALTY_NOT_FOUND"
    assert admin.repository.session.commits == 0


@pytest.mark.parametrize("key", ["short77", "k" * 129])
def test_service_idempotency_key_length_is_validated(admin, key):
    response = admin.call("POST", SERVICES, _service_body(), key=key)

    assert response.status_code == 422
    assert admin.repository.added == []


def test_a_retried_service_create_replays_the_first_response(admin):
    first = admin.call("POST", SERVICES, _service_body(), key="svc-create-0001")
    second = admin.call("POST", SERVICES, _service_body(), key="svc-create-0001")

    assert (first.status_code, second.status_code) == (201, 201)
    assert second.json() == first.json()
    assert len([r for r in admin.repository.added if type(r).__name__ == "Service"]) == 1
    assert len(admin.audit.records) == 1  # the replay writes nothing


def test_reusing_a_service_key_with_another_body_is_409(admin):
    admin.call("POST", SERVICES, _service_body(), key="svc-create-0002")

    response = admin.call("POST", SERVICES, _service_body(name_en="Other name"), key="svc-create-0002")

    assert response.status_code == 409
    assert _code(response) == "IDEMPOTENCY_CONFLICT"


# ============================================================ PATCH /admin/doctors/{id}


def _patch(admin, doctor_id, body, tenant="clinic-001"):
    return admin.call("PATCH", f"/api/v1/admin/doctors/{doctor_id}", body, tenant=tenant)


def test_doctor_update_returns_the_changed_doctor(admin):
    doctor = _doctor(PROVIDER_A)
    admin.repository.doctors[(PROVIDER_A.id, doctor.id)] = doctor

    response = _patch(admin, doctor.id, {"is_active": False, "consultation_fee": "250.50"})

    assert response.status_code == 200
    body = response.json()
    assert UUID(body["id"]) == doctor.id
    assert (body["is_active"], body["consultation_fee"], body["accepting_new_patients"]) == (False, "250.50", True)
    assert (body["branch_ids"], body["service_ids"]) == ([], [])
    assert admin.repository.session.commits == 1
    assert [r["action"] for r in admin.audit.records] == ["doctor.update"]


def test_doctor_fee_can_be_cleared_with_null(admin):
    doctor = _doctor(PROVIDER_A)
    doctor.consultation_fee = "100.00"
    admin.repository.doctors[(PROVIDER_A.id, doctor.id)] = doctor

    response = _patch(admin, doctor.id, {"consultation_fee": None})

    assert response.status_code == 200
    assert response.json()["consultation_fee"] is None


@pytest.mark.parametrize("field", ["is_active", "accepting_new_patients"])
def test_a_null_flag_is_422_invalid_doctor_update(admin, field):
    doctor = _doctor(PROVIDER_A)
    admin.repository.doctors[(PROVIDER_A.id, doctor.id)] = doctor

    response = _patch(admin, doctor.id, {field: None})

    assert response.status_code == 422
    assert _code(response) == "INVALID_DOCTOR_UPDATE"
    assert admin.repository.session.commits == 0 and admin.audit.records == []


def test_an_unknown_doctor_is_404(admin):
    response = _patch(admin, uuid4(), {"is_active": False})

    assert response.status_code == 404
    assert _code(response) == "DOCTOR_NOT_FOUND"


def test_another_providers_doctor_is_reported_as_not_found(admin):
    doctor = _doctor(PROVIDER_B)
    admin.repository.doctors[(PROVIDER_B.id, doctor.id)] = doctor

    response = _patch(admin, doctor.id, {"is_active": False})

    assert response.status_code == 404
    assert _code(response) == "DOCTOR_NOT_FOUND"
    assert doctor.is_active is True


@pytest.mark.parametrize("body", [{"consultation_fee": "-5"}, {"is_active": "maybe"}])
def test_invalid_doctor_update_values_are_422(admin, body):
    doctor = _doctor(PROVIDER_A)
    admin.repository.doctors[(PROVIDER_A.id, doctor.id)] = doctor

    assert _patch(admin, doctor.id, body).status_code == 422


def test_a_malformed_doctor_id_is_422(admin):
    assert _patch(admin, "not-a-uuid", {"is_active": False}).status_code == 422


# ============================================================ POST /admin/working-hours

HOURS = "/api/v1/admin/working-hours"


def _hour_body(**overrides):
    return {"doctor_id": str(uuid4()), "branch_id": str(uuid4()), "day_of_week": 1,
            "start_time": "09:00:00", "end_time": "12:00:00", "slot_duration_minutes": 30, **overrides}


def test_working_hour_create_returns_201_with_the_contract(admin):
    response = admin.call("POST", HOURS, _hour_body())

    assert response.status_code == 201
    body = response.json()
    assert set(body) == set(WorkingHourOut.model_fields)
    assert (body["day_of_week"], body["start_time"], body["end_time"]) == (1, "09:00:00", "12:00:00")
    (_, kwargs), = admin.hours.calls
    assert kwargs["provider_id"] == PROVIDER_A.id


def test_branch_level_hours_without_a_doctor_are_accepted(admin):
    body = _hour_body()
    body.pop("doctor_id")

    response = admin.call("POST", HOURS, body)

    assert response.status_code == 201
    assert response.json()["doctor_id"] is None


@pytest.mark.parametrize(
    "overrides",
    [{"end_time": "09:00:00"}, {"end_time": "08:00:00"}, {"day_of_week": -1}, {"day_of_week": 7},
     {"slot_duration_minutes": 4}, {"slot_duration_minutes": 241}, {"start_time": "25:00:00"},
     {"branch_id": None}],
)
def test_invalid_working_hours_are_422(admin, overrides):
    body = _hour_body(**overrides)
    if overrides.get("branch_id", "") is None:
        body.pop("branch_id")

    response = admin.call("POST", HOURS, body)

    assert response.status_code == 422
    assert admin.hours.calls == []


def test_the_time_range_error_names_the_rule(admin):
    response = admin.call("POST", HOURS, _hour_body(end_time="08:00:00"))

    assert "end_time must be after start_time" in response.text


# ============================================================ POST /admin/working-hours/generate-slots

GENERATE = "/api/v1/admin/working-hours/generate-slots"


def test_slot_generation_returns_the_result_contract(admin):
    response = admin.call("POST", GENERATE, {"date_from": "2026-11-01", "date_to": "2026-11-07"})

    assert response.status_code == 200
    assert response.json() == {
        "provider_id": str(PROVIDER_A.id), "date_from": "2026-11-01", "date_to": "2026-11-07",
        "working_hours_used": 2, "created_slots": 12, "skipped_existing_slots": 1,
    }
    (_, kwargs), = admin.hours.calls
    assert (kwargs["provider_id"], kwargs["provider_timezone"]) == (PROVIDER_A.id, "Africa/Cairo")


def test_a_one_day_and_a_90_day_range_are_accepted(admin):
    assert admin.call("POST", GENERATE, {"date_from": "2026-11-01", "date_to": "2026-11-01"}).status_code == 200
    assert admin.call("POST", GENERATE, {"date_from": "2026-11-01", "date_to": "2027-01-30"}).status_code == 200


@pytest.mark.parametrize(
    "body, message",
    [
        ({"date_from": "2026-11-07", "date_to": "2026-11-01"}, "date_to must be on or after date_from"),
        ({"date_from": "2026-11-01", "date_to": "2027-01-31"}, "cannot exceed 90 days"),
        ({"date_from": "2026-11-01"}, None),
        ({"date_from": "not-a-date", "date_to": "2026-11-01"}, None),
        ({"date_from": "2026-11-01", "date_to": "2026-11-02", "doctor_id": "nope"}, None),
    ],
)
def test_invalid_slot_generation_ranges_are_422(admin, body, message):
    response = admin.call("POST", GENERATE, body)

    assert response.status_code == 422
    if message:
        assert message in response.text
    assert admin.hours.calls == []


# ============================================================ GET /admin/working-hours


def test_working_hours_list_is_scoped_to_the_tenant(admin):
    a = admin.call("GET", HOURS, tenant="clinic-001").json()
    b = admin.call("GET", HOURS, tenant="clinic-002").json()

    assert {UUID(r["provider_id"]) for r in a} == {PROVIDER_A.id} and len(a) == 2
    assert {UUID(r["provider_id"]) for r in b} == {PROVIDER_B.id} and len(b) == 1
    assert [c[1]["provider_id"] for c in admin.hours.calls] == [PROVIDER_A.id, PROVIDER_B.id]


def test_working_hours_list_passes_every_filter(admin):
    doctor_id, branch_id = uuid4(), uuid4()

    response = admin.call("GET", HOURS, params={"doctor_id": str(doctor_id), "branch_id": str(branch_id),
                                                "day_of_week": 2})

    assert response.status_code == 200
    (_, kwargs), = admin.hours.calls
    assert kwargs == {"provider_id": PROVIDER_A.id, "doctor_id": doctor_id, "branch_id": branch_id, "day_of_week": 2}


def test_working_hours_list_can_be_empty(admin):
    response = admin.call("GET", HOURS, params={"day_of_week": 6})

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("params", [{"day_of_week": 7}, {"day_of_week": -1}, {"day_of_week": "monday"},
                                    {"doctor_id": "nope"}, {"branch_id": "nope"}])
def test_invalid_working_hours_filters_are_422(admin, params):
    response = admin.call("GET", HOURS, params=params)

    assert response.status_code == 422
    assert admin.hours.calls == []


def test_working_hours_list_requires_a_known_tenant(admin):
    assert admin.call("GET", HOURS, tenant="no-such-clinic").status_code == 404


# ============================================================ GET /departments

DEPARTMENTS = "/api/v1/departments"


def test_departments_are_scoped_to_the_tenant_with_the_contract(admin):
    a = admin.call("GET", DEPARTMENTS, tenant="clinic-001")
    b = admin.call("GET", DEPARTMENTS, tenant="clinic-002")

    assert a.status_code == b.status_code == 200
    assert {d["code"] for d in a.json()} == {"CARD", "LAB"}
    assert {d["code"] for d in b.json()} == {"DERM"}
    assert set(a.json()[0]) == set(DepartmentOut.model_fields)
    assert ("get_departments", PROVIDER_A.id, None) in admin.catalog.calls


def test_departments_branch_filter_keeps_provider_wide_departments(admin):
    response = admin.call("GET", DEPARTMENTS, params={"branch_id": str(BRANCH_A1)})

    assert {d["code"] for d in response.json()} == {"CARD", "LAB"}
    assert admin.catalog.calls == [("get_departments", PROVIDER_A.id, BRANCH_A1)]


def test_departments_of_another_branch_are_excluded(admin):
    response = admin.call("GET", DEPARTMENTS, params={"branch_id": str(uuid4())})

    assert {d["code"] for d in response.json()} == {"CARD"}


def test_departments_can_be_empty(admin):
    admin.catalog.departments[PROVIDER_B.id] = []

    response = admin.call("GET", DEPARTMENTS, tenant="clinic-002")

    assert response.status_code == 200
    assert response.json() == []


def test_departments_reject_a_malformed_branch_id(admin):
    assert admin.call("GET", DEPARTMENTS, params={"branch_id": "nope"}).status_code == 422
    assert admin.catalog.calls == []


@pytest.mark.parametrize("tenant, status_code", [(None, 422), ("no-such-clinic", 404)])
def test_departments_require_a_known_tenant(admin, tenant, status_code):
    if tenant is None:
        response = TestClient(_bare_catalog_app(admin)).get(DEPARTMENTS)
    else:
        response = admin.call("GET", DEPARTMENTS, tenant=tenant)

    assert response.status_code == status_code


def _bare_catalog_app(admin):
    app = FastAPI()
    app.include_router(catalog.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_catalog_service] = lambda: admin.catalog
    return app


# ============================================================ POST /ai/warmup

VOICE_TOKEN = "voice-gateway-test-token-0123456789abcdef"
MCP_TOKEN = "mcp-server-test-token-0123456789abcdef0123"
WARMUP = "/api/v1/ai/warmup"


class FakeRegistry:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    async def get(self, *, tenant_id, tenant_context):
        self.calls.append((tenant_id, tenant_context))
        if self.error is not None:
            raise self.error


class FakePlanner:
    def __init__(self):
        self.warmups = 0

    async def warmup(self):
        self.warmups += 1
        return True


@pytest.fixture
def warmup(monkeypatch):
    monkeypatch.setenv(
        "MEDMIND_SERVICE_CREDENTIALS",
        f"voice_gateway={VOICE_TOKEN}@clinic-001,vet-001;mcp_server={MCP_TOKEN}@clinic-001",
    )
    get_settings.cache_clear()
    providers = {
        "clinic-001": PROVIDER_A,
        # A case-insensitive database lookup could resolve this header to clinic-001.
        "CLINIC-001": PROVIDER_A,
        "vet-001": SimpleNamespace(id=uuid4(), tenant_key="vet-001", timezone="Africa/Cairo",
                                   org_type="veterinary", name="Vet"),
    }
    lookups = []

    def provider_for(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
        lookups.append(x_tenant_id)
        return providers[x_tenant_id]

    app = FastAPI()
    app.include_router(medmind_ai.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_current_provider] = provider_for
    app.state.medmind_registry = FakeRegistry()
    client = TestClient(app)

    def call(tenant="clinic-001", token=VOICE_TOKEN):
        return client.post(WARMUP, headers={"X-Tenant-ID": tenant, SERVICE_TOKEN_HEADER: token})

    yield SimpleNamespace(app=app, call=call, lookups=lookups)
    get_settings.cache_clear()


def test_warmup_returns_ready_with_the_tenant_and_planner_state(warmup):
    planner = FakePlanner()
    warmup.app.state.medmind_qwen_planner = planner

    response = warmup.call()

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "tenant_id", "qwen_ready", "elapsed_ms"}
    assert (body["status"], body["tenant_id"], body["qwen_ready"]) == ("ready", "clinic-001", True)
    assert isinstance(body["elapsed_ms"], (int, float))
    (tenant_id, context), = warmup.app.state.medmind_registry.calls
    assert (tenant_id, context.tenant_id, context.provider_id) == ("clinic-001", "clinic-001", PROVIDER_A.id)
    assert planner.warmups == 1


def test_warmup_without_a_planner_reports_qwen_not_ready(warmup):
    response = warmup.call()

    assert response.status_code == 200
    assert response.json()["qwen_ready"] is False
    assert len(warmup.app.state.medmind_registry.calls) == 1


def test_a_failed_tenant_warmup_is_503_without_details(warmup, caplog):
    caplog.set_level(logging.ERROR)
    warmup.app.state.medmind_registry = FakeRegistry(error=RuntimeError("simulated-internal-failure"))

    response = warmup.call()

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "MEDMIND_WARMUP_FAILED",
                                          "message": "MedMind warm-up could not be completed."}}
    assert "simulated-internal-failure" not in response.text


def test_a_tenant_context_mismatch_is_500_before_any_warmup(warmup):
    # Header "CLINIC-001" resolves to provider "clinic-001" (allowed), but the
    # header and the resolved tenant differ: the route fails closed.
    response = warmup.call(tenant="CLINIC-001")

    assert response.status_code == 500
    assert _code(response) == "TENANT_CONTEXT_MISMATCH"
    assert warmup.app.state.medmind_registry.calls == []


def test_an_unsupported_provider_type_is_403(warmup):
    response = warmup.call(tenant="vet-001")

    assert response.status_code == 403
    assert _code(response) == "PROVIDER_TYPE_UNSUPPORTED"
    assert warmup.app.state.medmind_registry.calls == []


def test_warmup_is_gateway_only(warmup):
    # Full /ai/* policy coverage: test_gateway_service_policy.py.
    response = warmup.call(token=MCP_TOKEN)

    assert response.status_code == 403
    assert _code(response) == "SERVICE_NOT_ALLOWED"
    assert warmup.lookups == [] and warmup.app.state.medmind_registry.calls == []
