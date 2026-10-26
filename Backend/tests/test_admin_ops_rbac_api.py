"""Provider-admin routes: authentication, role checks, provider scoping and
audit records for admin catalog, working-hours writes, analytics and audit
events. No database: services and repositories are fakes."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import dependencies as deps
from app.api.routers import admin_catalog, admin_working_hours, ops
from app.schemas.admin_catalog import AdminDoctorOut
from app.security.staff_context import StaffContext
from app.services.staff_audit_service import StaffAuditService

PROVIDER_A = uuid4()
NOW = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)


def _staff(role, provider_id=PROVIDER_A):
    return StaffContext(
        user_id=uuid4(),
        membership_id=uuid4(),
        provider_id=provider_id,
        role=role,
        doctor_id=uuid4() if role == "doctor" else None,
    )


class _AuditSession:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def refresh(self, value):
        pass


class _AuditRepository:
    def __init__(self):
        self.session = _AuditSession()
        self.added = []

    def add(self, row):
        self.added.append(row)
        return row


class StubAudit(StaffAuditService):
    """The real audit service over an in-memory repository."""

    def __init__(self):
        super().__init__(_AuditRepository())

    @property
    def records(self):
        return [
            {
                "provider_id": row.provider_id, "user_id": row.user_id,
                "patient_id": row.patient_id, "action": row.action,
                "resource_id": row.resource_id, "outcome": row.outcome,
            }
            for row in self.repository.added
        ]


class FakeWorkingHours:
    def __init__(self):
        self.calls = []

    def create(self, provider_id, data, audit=None):
        self.calls.append(("create", provider_id))
        hour_id = uuid4()
        if audit is not None:
            audit(str(hour_id))
        return SimpleNamespace(
            id=hour_id, provider_id=provider_id, doctor_id=data.doctor_id,
            branch_id=data.branch_id, day_of_week=data.day_of_week,
            start_time=data.start_time, end_time=data.end_time,
            slot_duration_minutes=data.slot_duration_minutes,
            is_active=True, created_at=NOW, updated_at=NOW,
        )

    def list(self, provider_id, doctor_id=None, branch_id=None, day_of_week=None):
        self.calls.append(("list", provider_id))
        return []

    def generate_slots(self, provider_id, provider_timezone, data, audit=None):
        self.calls.append(("generate", provider_id))
        if audit is not None:
            audit(None)
        return {
            "provider_id": provider_id, "date_from": data.date_from, "date_to": data.date_to,
            "working_hours_used": 1, "created_slots": 4, "skipped_existing_slots": 0,
        }


class FakeAdminCatalog:
    def __init__(self):
        self.calls = []
        self.idempotency_keys = []

    def create_doctor(self, *, provider_id, data, idempotency_key=None, audit=None):
        self.calls.append(("create_doctor", provider_id))
        self.idempotency_keys.append(idempotency_key)
        doctor_id = uuid4()
        if audit is not None:
            audit(str(doctor_id))
        return AdminDoctorOut(**{
            "id": doctor_id, "provider_id": provider_id, "specialty_id": data.specialty_id,
            "full_name_ar": data.full_name_ar, "full_name_en": data.full_name_en,
            "license_number": None, "consultation_fee": None, "experience_years": None,
            "gender": None, "accepting_new_patients": True, "verification_status": "pending",
            "is_active": True, "branch_ids": data.branch_ids, "service_ids": data.service_ids,
        })

    def update_doctor(self, *, provider_id, doctor_id, data, audit=None):
        self.calls.append(("update_doctor", provider_id))
        if audit is not None:
            audit(str(doctor_id))
        doctor = self.create_doctor(
            provider_id=provider_id,
            data=SimpleNamespace(specialty_id=uuid4(), full_name_ar="د", full_name_en="Dr X",
                                 branch_ids=[], service_ids=[]),
        )
        return doctor.model_copy(update={"id": doctor_id, "is_active": data.is_active})


class FakeOpsRepository:
    def __init__(self):
        self.calls = []

    def appointment_counts(self, *, provider_id, date_from, date_to):
        self.calls.append(("counts", provider_id))
        return [
            {"status": "confirmed", "channel": "voice", "count": 3},
            {"status": "cancelled", "channel": "voice", "count": 1},
            {"status": "confirmed", "channel": "web", "count": 2},
        ]

    def list_audit_events(self, *, provider_id, **filters):
        self.calls.append(("audit", provider_id))
        return [
            SimpleNamespace(
                id=uuid4(), provider_id=provider_id, user_id=uuid4(), membership_id=uuid4(),
                patient_id=None, action="doctor.create", resource_type="doctor",
                resource_id="x", outcome="success", created_at=NOW,
            )
        ]


def _app(staff=None):
    app = FastAPI()
    for router in (admin_catalog.router, admin_working_hours.router, ops.router):
        app.include_router(router, prefix="/api/v1")

    fakes = SimpleNamespace(
        hours=FakeWorkingHours(), catalog=FakeAdminCatalog(),
        ops=FakeOpsRepository(), audit=StubAudit(),
    )
    app.dependency_overrides[deps.get_current_provider] = lambda: SimpleNamespace(
        id=PROVIDER_A, tenant_key="clinic-001", timezone="Africa/Cairo"
    )
    app.dependency_overrides[deps.get_working_hours_service] = lambda: fakes.hours
    app.dependency_overrides[deps.get_admin_catalog_service] = lambda: fakes.catalog
    app.dependency_overrides[deps.get_ops_repository] = lambda: fakes.ops
    app.dependency_overrides[deps.get_staff_audit_service] = lambda: fakes.audit

    if staff is not None:
        app.dependency_overrides[deps.get_current_staff] = lambda: staff
    else:
        # Never reached: the missing bearer token is rejected first.
        app.dependency_overrides[deps.get_staff_access_service] = lambda: object()

    return TestClient(app), fakes


DOCTOR_BODY = {
    "specialty_id": str(uuid4()),
    "full_name_ar": "د. تجربة",
    "full_name_en": "Dr Test",
    "branch_ids": [str(uuid4())],
    "service_ids": [],
}

WORKING_HOUR_BODY = {
    "doctor_id": str(uuid4()),
    "branch_id": str(uuid4()),
    "day_of_week": 1,
    "start_time": "09:00:00",
    "end_time": "12:00:00",
    "slot_duration_minutes": 30,
}

PRIVILEGED = [
    ("post", "/api/v1/admin/doctors", DOCTOR_BODY),
    ("patch", f"/api/v1/admin/doctors/{uuid4()}", {"is_active": False}),
    ("post", f"/api/v1/admin/doctors/{uuid4()}/verification", {"decision": "verified"}),
    ("post", f"/api/v1/admin/doctors/{uuid4()}/resubmit", None),
    ("post", "/api/v1/admin/services", {
        "code": "NEW_SVC", "name_ar": "خدمة", "name_en": "Service", "duration_minutes": 15,
    }),
    ("post", "/api/v1/admin/working-hours", WORKING_HOUR_BODY),
    ("post", "/api/v1/admin/working-hours/generate-slots",
     {"date_from": "2026-10-20", "date_to": "2026-10-21"}),
    ("get", "/api/v1/analytics/appointments?date_from=2026-10-01&date_to=2026-10-31", None),
    ("get", "/api/v1/audit-events", None),
]


def _call(client, method, path, body):
    if body is None:
        return getattr(client, method)(path)
    return getattr(client, method)(path, json=body)


@pytest.mark.parametrize("method,path,body", PRIVILEGED)
def test_privileged_route_without_token_is_401(method, path, body):
    client, fakes = _app()

    response = _call(client, method, path, body)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "STAFF_AUTH_REQUIRED"
    assert fakes.hours.calls == fakes.catalog.calls == fakes.ops.calls == []
    assert fakes.audit.records == []


@pytest.mark.parametrize("role", ["receptionist", "doctor", "lab_staff"])
@pytest.mark.parametrize("method,path,body", PRIVILEGED)
def test_privileged_route_rejects_non_admin_roles(method, path, body, role):
    client, fakes = _app(_staff(role))

    response = _call(client, method, path, body)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "STAFF_PERMISSION_DENIED"
    assert fakes.hours.calls == fakes.catalog.calls == fakes.ops.calls == []


def test_working_hours_list_stays_readable_with_tenant_only():
    # The MCP booking tools read this list with X-Tenant-ID only.
    client, fakes = _app()

    response = client.get("/api/v1/admin/working-hours")

    assert response.status_code == 200
    assert fakes.hours.calls == [("list", PROVIDER_A)]


def test_admin_creates_doctor_for_own_provider_and_is_audited():
    staff = _staff("provider_admin")
    client, fakes = _app(staff)

    response = client.post("/api/v1/admin/doctors", json=DOCTOR_BODY)

    assert response.status_code == 201
    assert response.json()["verification_status"] == "pending"
    assert fakes.catalog.calls == [("create_doctor", PROVIDER_A)]
    assert fakes.audit.records[0]["action"] == "doctor.create"
    assert fakes.audit.records[0]["user_id"] == staff.user_id
    assert fakes.audit.records[0]["provider_id"] == PROVIDER_A
    assert fakes.audit.records[0].get("patient_id") is None


def test_admin_working_hours_writes_are_audited():
    client, fakes = _app(_staff("provider_admin"))

    created = client.post("/api/v1/admin/working-hours", json=WORKING_HOUR_BODY)
    generated = client.post(
        "/api/v1/admin/working-hours/generate-slots",
        json={"date_from": "2026-10-20", "date_to": "2026-10-21"},
    )

    assert created.status_code == 201
    assert generated.status_code == 200
    assert [r["action"] for r in fakes.audit.records] == [
        "working_hours.create",
        "availability_slots.generate",
    ]


@pytest.mark.parametrize(
    "body",
    [
        {**DOCTOR_BODY, "branch_ids": []},
        {**DOCTOR_BODY, "branch_ids": [DOCTOR_BODY["branch_ids"][0]] * 2},
        {**DOCTOR_BODY, "gender": "other"},
        {**DOCTOR_BODY, "full_name_en": "x" * 201},
    ],
)
def test_invalid_doctor_payload_is_422(body):
    client, fakes = _app(_staff("provider_admin"))

    response = client.post("/api/v1/admin/doctors", json=body)

    assert response.status_code == 422
    assert fakes.catalog.calls == []


def test_empty_doctor_update_is_422():
    client, fakes = _app(_staff("provider_admin"))

    response = client.patch(f"/api/v1/admin/doctors/{uuid4()}", json={})

    assert response.status_code == 422
    assert fakes.catalog.calls == []


def test_analytics_uses_the_staff_provider_and_aggregates():
    client, fakes = _app(_staff("provider_admin"))

    response = client.get("/api/v1/analytics/appointments?date_from=2026-10-01&date_to=2026-10-31")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 6
    assert body["by_status"] == {"confirmed": 5, "cancelled": 1}
    assert body["by_channel"] == {"voice": 4, "web": 2}
    assert fakes.ops.calls == [("counts", PROVIDER_A)]


@pytest.mark.parametrize(
    "query",
    ["date_from=2026-10-31&date_to=2026-10-01", "date_from=2025-01-01&date_to=2026-10-01"],
)
def test_analytics_rejects_bad_ranges(query):
    client, fakes = _app(_staff("provider_admin"))

    response = client.get(f"/api/v1/analytics/appointments?{query}")

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_DATE_RANGE"
    assert fakes.ops.calls == []


def test_audit_events_are_provider_scoped_and_the_read_is_audited():
    staff = _staff("provider_admin")
    client, fakes = _app(staff)

    response = client.get("/api/v1/audit-events?action=doctor.create&limit=10")

    assert response.status_code == 200
    assert fakes.ops.calls == [("audit", PROVIDER_A)]
    assert all(row["provider_id"] == str(PROVIDER_A) for row in response.json())
    assert fakes.audit.records[-1]["action"] == "audit_events.read"


def test_audit_events_reject_unsafe_action_filter():
    client, fakes = _app(_staff("provider_admin"))

    response = client.get("/api/v1/audit-events?action=x';DROP TABLE x--")

    assert response.status_code == 422
    assert fakes.ops.calls == []


@pytest.mark.parametrize(
    "method,path,body,action",
    [
        ("post", "/api/v1/admin/doctors", DOCTOR_BODY, "doctor.create"),
        ("patch", f"/api/v1/admin/doctors/{uuid4()}", {"is_active": False}, "doctor.update"),
        ("post", "/api/v1/admin/working-hours", WORKING_HOUR_BODY, "working_hours.create"),
        ("post", "/api/v1/admin/working-hours/generate-slots",
         {"date_from": "2026-10-20", "date_to": "2026-10-21"}, "availability_slots.generate"),
    ],
)
def test_admin_write_audit_is_staged_for_the_service_commit(method, path, body, action):
    # The audit row is handed to the write service (staged, not committed
    # separately), so a failed audit can never follow a committed write.
    client, fakes = _app(_staff("provider_admin"))

    response = _call(client, method, path, body)

    assert response.status_code in (200, 201)
    assert [r["action"] for r in fakes.audit.records] == [action]
    assert fakes.audit.repository.session.commits == 0


def test_idempotency_key_is_passed_to_the_doctor_create():
    client, fakes = _app(_staff("provider_admin"))

    response = client.post(
        "/api/v1/admin/doctors", json=DOCTOR_BODY, headers={"Idempotency-Key": "admin-retry-0001"}
    )

    assert response.status_code == 201
    assert fakes.catalog.idempotency_keys == ["admin-retry-0001"]


def test_too_short_idempotency_key_is_rejected():
    client, fakes = _app(_staff("provider_admin"))

    response = client.post(
        "/api/v1/admin/doctors", json=DOCTOR_BODY, headers={"Idempotency-Key": "short"}
    )

    assert response.status_code == 422
    assert fakes.catalog.calls == []

