"""
Weekly-plan acceptance checks over HTTP against the isolated audit database.

Opt-in only: MEDMIND_DB_INTEGRATION=1. Reuses the db_session fixture from
test_lab_booking_without_doctor_db, which refuses anything but
localhost\\SQLEXPRESS / MedMind_Audit_Final2 and rolls back one outer
transaction at the end: the staff account, doctor, schedule, slots,
appointments and audit rows created here never persist.

Requests go through the real routers, the real JWT + membership check and
the real services. Only the national-ID protector is replaced (it maps two
synthetic national IDs to existing seeded patients) and the DB session is
the rolled-back test session. No external service is called.
"""

import os
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import dependencies as deps
from app.api.routers import (
    admin_catalog,
    admin_working_hours,
    appointments,
    catalog,
    ops,
    search,
)
from app.core.config import get_settings
from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.patient_branch_profile_repository import (
    PatientBranchProfileRepository,
)
from app.repositories.patient_repository import PatientRepository
from app.security.tokens import create_access_token
from app.services.appointment_service import AppointmentService
from app.services.idempotency_service import idempotency_service
from app.services.patient_branch_profile_service import (
    PatientBranchProfileService,
)
from tests.test_lab_booking_without_doctor_db import (  # noqa: F401  db_session is a fixture
    active_patient_hash,
    db_session,
    future_date,
    one,
    provider,
)


pytestmark = pytest.mark.skipif(
    os.getenv("MEDMIND_DB_INTEGRATION") != "1",
    reason="Set MEDMIND_DB_INTEGRATION=1 to run against an audit database.",
)

TEST_JWT_SECRET = "test-only-signing-key-not-production-0123456789abcdef"
# Test-only MCP -> Backend credential (app/security/booking_auth.py).
TEST_MCP_TOKEN = "test-only-mcp-server-token-0123456789abcdef"

# Synthetic national IDs; each maps to one seeded patient of one provider.
NID_CLINIC_2 = "29001011234567"
NID_CLINIC_3 = "29001017654321"

TENANT = "clinic-002"
OTHER_TENANT = "clinic-003"


class MappedHashProtector:
    def __init__(self, hashes: dict[str, str]) -> None:
        self.hashes = hashes

    def hash_national_id(self, national_id: str) -> str:
        return self.hashes[national_id]


@pytest.fixture
def jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("JWT_SECRET_KEY")
    get_settings.cache_clear()


@pytest.fixture
def booking_service_enforced(monkeypatch):
    """Booking routes in enforce mode, with a test mcp_server credential for both tenants."""
    monkeypatch.setenv(
        "MEDMIND_SERVICE_CREDENTIALS",
        f"mcp_server={TEST_MCP_TOKEN}@{TENANT},{OTHER_TENANT}",
    )
    monkeypatch.setenv("BOOKING_SERVICE_AUTH_MODE", "enforce")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _staff_token(session, provider_id, role="provider_admin"):
    """A staff account + membership inside the rolled-back transaction."""
    user_id, membership_id = uuid4(), uuid4()

    session.execute(
        text(
            "INSERT INTO dbo.user_accounts (id, email, password_hash, is_active) "
            "VALUES (:id, :email, 'not-a-real-hash', 1)"
        ),
        {"id": str(user_id), "email": f"pytest-{user_id.hex}@example.invalid"},
    )
    session.execute(
        text(
            "INSERT INTO dbo.provider_memberships (id, user_id, provider_id, role, doctor_id, is_active) "
            "VALUES (:id, :user_id, :provider_id, :role, NULL, 1)"
        ),
        {
            "id": str(membership_id),
            "user_id": str(user_id),
            "provider_id": str(provider_id),
            "role": role,
        },
    )

    # Release the savepoint: the account now exists "before" the requests,
    # so a request's own rollback cannot discard it. The outer test
    # transaction is still rolled back at the end.
    session.commit()

    return create_access_token(
        user_id=user_id,
        membership_id=membership_id,
        provider_id=provider_id,
    )


def _client(session):
    clinic_2 = provider(session, TENANT)
    clinic_3 = provider(session, OTHER_TENANT)

    protector = MappedHashProtector(
        {
            NID_CLINIC_2: active_patient_hash(session, clinic_2.id),
            NID_CLINIC_3: active_patient_hash(session, clinic_3.id),
        }
    )

    def appointment_service():
        return AppointmentService(
            repository=AppointmentRepository(session),
            patient_repository=PatientRepository(session),
            identity_protector=protector,
            branch_profile_service=PatientBranchProfileService(
                PatientBranchProfileRepository(session)
            ),
            idempotency_service=idempotency_service,
        )

    app = FastAPI()
    for router in (
        search.router,
        catalog.router,
        admin_catalog.router,
        admin_working_hours.router,
        appointments.router,
        ops.router,
    ):
        app.include_router(router, prefix="/api/v1")

    app.dependency_overrides[deps.get_db_session] = lambda: session
    app.dependency_overrides[deps.get_appointment_service] = appointment_service

    return TestClient(app), clinic_2, clinic_3


def _headers(tenant, token=None, *, service=False, **extra):
    headers = {"X-Tenant-ID": tenant, **extra}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if service:
        headers["X-MedMind-Service-Token"] = TEST_MCP_TOKEN
    return headers


def _first_id(session, sql, **params):
    return str(one(session, sql, **params).id)


def _new_doctor_with_schedule(client, session, clinic, token, target_date):
    """Acceptance 3: admin adds a doctor + hours, then generates 05:00-06:00 slots."""
    specialty_id = _first_id(
        session,
        "SELECT TOP 1 id FROM dbo.specialties WHERE provider_id = :p AND is_active = 1 ORDER BY code",
        p=str(clinic.id),
    )
    branch_id = _first_id(
        session,
        "SELECT TOP 1 id FROM dbo.branches WHERE provider_id = :p AND is_active = 1 ORDER BY code",
        p=str(clinic.id),
    )
    service_id = _first_id(
        session,
        "SELECT TOP 1 id FROM dbo.services WHERE provider_id = :p AND is_active = 1 "
        "AND service_type = 'consultation' ORDER BY code",
        p=str(clinic.id),
    )

    name = f"Dr Pytest {uuid4().hex[:8]}"
    created = client.post(
        "/api/v1/admin/doctors",
        headers=_headers(TENANT, token),
        json={
            "specialty_id": specialty_id,
            "full_name_ar": "د. اختبار",
            "full_name_en": name,
            "branch_ids": [branch_id],
            "service_ids": [service_id],
        },
    )
    assert created.status_code == 201, created.text
    doctor_id = created.json()["id"]

    hours = client.post(
        "/api/v1/admin/working-hours",
        headers=_headers(TENANT, token),
        json={
            "doctor_id": doctor_id,
            "branch_id": branch_id,
            "day_of_week": target_date.weekday(),
            "start_time": "05:00:00",
            "end_time": "06:00:00",
            "slot_duration_minutes": 30,
        },
    )
    assert hours.status_code == 201, hours.text

    generated = client.post(
        "/api/v1/admin/working-hours/generate-slots",
        headers=_headers(TENANT, token),
        json={
            "date_from": target_date.isoformat(),
            "date_to": target_date.isoformat(),
            "doctor_id": doctor_id,
        },
    )
    assert generated.status_code == 200, generated.text
    assert generated.json()["created_slots"] == 2

    return doctor_id, name, branch_id, service_id


# ============================================================
# 1. Global search across providers
# ============================================================


def test_global_search_spans_providers(db_session):
    client, clinic_2, _ = _client(db_session)
    start = future_date(clinic_2.timezone, days=1)

    doctors = client.get("/api/v1/search/doctors?limit=100")
    slots = client.get(
        "/api/v1/search/availability",
        params={
            "date_from": start.isoformat(),
            "date_to": (start + timedelta(days=3)).isoformat(),
            "limit": 200,
        },
    )
    labs = client.get("/api/v1/search/providers?org_type=diagnostic_lab")

    assert doctors.status_code == slots.status_code == labs.status_code == 200
    assert len({row["provider_id"] for row in doctors.json()}) >= 2
    assert len({row["provider_id"] for row in slots.json()}) >= 2
    assert labs.json() and all(row["org_type"] == "diagnostic_lab" for row in labs.json())
    # Pharmacies are not part of the booking catalog.
    assert all(row["provider_org_type"] != "pharmacy" for row in doctors.json())
    assert "tenant_key" not in labs.json()[0]


# ============================================================
# 3. Admin adds a doctor + schedule and it appears in search
# ============================================================


def test_admin_doctor_and_schedule_appear_in_search(db_session, jwt_secret):
    client, clinic_2, _ = _client(db_session)
    token = _staff_token(db_session, clinic_2.id)
    target_date = future_date(clinic_2.timezone, days=5)

    doctor_id, name, _, _ = _new_doctor_with_schedule(
        client, db_session, clinic_2, token, target_date
    )

    found = client.get(f"/api/v1/search/doctors?provider_id={clinic_2.id}&q={name}")
    assert [row["id"] for row in found.json()] == [doctor_id]

    global_slots = client.get(
        f"/api/v1/search/availability?date_from={target_date}&doctor_id={doctor_id}"
    )
    assert len(global_slots.json()) == 2

    tenant_slots = client.get(
        f"/api/v1/doctors/{doctor_id}/availability?date_from={target_date}",
        headers=_headers(TENANT),
    )
    assert tenant_slots.status_code == 200
    assert len(tenant_slots.json()) == 2

    actions = {
        row[0]
        for row in db_session.execute(
            text("SELECT action FROM dbo.staff_audit_logs WHERE provider_id = :p AND resource_id = :d"),
            {"p": str(clinic_2.id), "d": doctor_id},
        ).all()
    }
    assert actions == {"doctor.create"}


def test_admin_operations_are_denied_across_tenants_and_roles(db_session, jwt_secret):
    client, clinic_2, clinic_3 = _client(db_session)
    admin_token = _staff_token(db_session, clinic_2.id)
    receptionist_token = _staff_token(db_session, clinic_2.id, role="receptionist")

    foreign_branch = _first_id(
        db_session,
        "SELECT TOP 1 id FROM dbo.branches WHERE provider_id = :p AND is_active = 1",
        p=str(clinic_3.id),
    )
    own_specialty = _first_id(
        db_session,
        "SELECT TOP 1 id FROM dbo.specialties WHERE provider_id = :p AND is_active = 1",
        p=str(clinic_2.id),
    )
    body = {
        "specialty_id": own_specialty,
        "full_name_ar": "د. اختبار",
        "full_name_en": "Dr Cross Tenant",
        "branch_ids": [foreign_branch],
    }

    # clinic-002 token used against clinic-003.
    wrong_tenant = client.post(
        "/api/v1/admin/doctors", headers=_headers(OTHER_TENANT, admin_token), json=body
    )
    # Another provider's branch inside the admin's own provider.
    foreign_link = client.post(
        "/api/v1/admin/doctors", headers=_headers(TENANT, admin_token), json=body
    )
    wrong_role = client.post(
        "/api/v1/admin/doctors", headers=_headers(TENANT, receptionist_token), json=body
    )
    no_token = client.post("/api/v1/admin/doctors", headers=_headers(TENANT), json=body)

    assert wrong_tenant.status_code == 403
    assert wrong_tenant.json()["detail"]["code"] == "STAFF_TENANT_MISMATCH"
    assert foreign_link.status_code == 404
    assert foreign_link.json()["detail"]["code"] == "BRANCH_NOT_FOUND"
    assert wrong_role.status_code == 403
    assert no_token.status_code == 401

    created = db_session.execute(
        text("SELECT COUNT(*) FROM dbo.doctors WHERE full_name_en = 'Dr Cross Tenant'")
    ).scalar_one()
    assert created == 0


# ============================================================
# 2 + 5. Booking lifecycle, duplicate booking, cross-tenant denial
# ============================================================


def test_booking_lifecycle_duplicate_and_cross_tenant(db_session, jwt_secret, booking_service_enforced):
    client, clinic_2, clinic_3 = _client(db_session)
    token = _staff_token(db_session, clinic_2.id)
    target_date = future_date(clinic_2.timezone, days=6)

    doctor_id, _, _, service_id = _new_doctor_with_schedule(
        client, db_session, clinic_2, token, target_date
    )
    slots = client.get(
        f"/api/v1/doctors/{doctor_id}/availability?date_from={target_date}",
        headers=_headers(TENANT),
    ).json()
    first_slot, second_slot = slots[0]["id"], slots[1]["id"]

    booking = {
        "national_id": NID_CLINIC_2,
        "slot_id": first_slot,
        "service_id": service_id,
        "channel": "web",
    }

    # --- create (idempotent replay returns the same booking) -----------
    key = f"pytest-accept-{uuid4().hex}"
    created = client.post(
        "/api/v1/appointments", headers=_headers(TENANT, service=True, **{"Idempotency-Key": key}), json=booking
    )
    replay = client.post(
        "/api/v1/appointments", headers=_headers(TENANT, service=True, **{"Idempotency-Key": key}), json=booking
    )
    assert created.status_code == 201, created.text
    assert replay.status_code == 201
    reference = created.json()["appointment_reference"]
    assert replay.json()["appointment_reference"] == reference

    # --- duplicate booking of the same slot is rejected ----------------
    # --- enforce mode: no MCP credential, no booking -------------------
    unauthenticated = client.post("/api/v1/appointments", headers=_headers(TENANT), json=booking)
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["detail"]["code"] == "SERVICE_AUTH_REQUIRED"

    duplicate = client.post("/api/v1/appointments", headers=_headers(TENANT, service=True), json=booking)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "SLOT_UNAVAILABLE"

    # --- cross-tenant: clinic-003 cannot book clinic-002's slot ---------
    cross_booking = client.post(
        "/api/v1/appointments",
        headers=_headers(OTHER_TENANT, service=True),
        json={**booking, "national_id": NID_CLINIC_3, "slot_id": second_slot},
    )
    assert cross_booking.status_code in (404, 409, 422)
    assert cross_booking.status_code != 201

    # --- cross-tenant: clinic-003 cannot read or cancel it -------------
    cross_lookup = client.post(
        "/api/v1/appointments/lookup",
        headers=_headers(OTHER_TENANT, service=True),
        json={"national_id": NID_CLINIC_3, "appointment_reference": reference},
    )
    cross_cancel = client.post(
        f"/api/v1/appointments/{reference}/cancel",
        headers=_headers(OTHER_TENANT, service=True),
        json={"national_id": NID_CLINIC_3},
    )
    cross_staff_read = client.get(
        f"/api/v1/appointments/reference/{reference}", headers=_headers(OTHER_TENANT, token)
    )
    assert cross_lookup.status_code == 404
    assert cross_cancel.status_code == 404
    assert cross_staff_read.status_code == 403

    # --- retrieve (patient and staff) ----------------------------------
    patient_read = client.post(
        "/api/v1/appointments/lookup",
        headers=_headers(TENANT, service=True),
        json={"national_id": NID_CLINIC_2, "appointment_reference": reference},
    )
    staff_read = client.get(
        f"/api/v1/appointments/reference/{reference}", headers=_headers(TENANT, token)
    )
    assert patient_read.status_code == 200
    assert staff_read.status_code == 200
    assert staff_read.json()["slot_id"] == first_slot

    # --- confirm: bookings are created confirmed; make this one pending
    #     inside the rolled-back transaction to exercise the transition --
    db_session.execute(
        text(
            "UPDATE dbo.appointments SET status = 'pending', confirmed_at = NULL "
            "WHERE provider_id = :p AND appointment_reference = :r"
        ),
        {"p": str(clinic_2.id), "r": reference},
    )
    confirm_body = {"national_id": NID_CLINIC_2, "changed_by": "patient"}
    no_credential = client.post(
        f"/api/v1/appointments/{reference}/confirm", headers=_headers(TENANT), json=confirm_body
    )
    assert no_credential.status_code == 401
    # The MCP service confirms; then a provider admin confirms again (no-op).
    confirmed = client.post(
        f"/api/v1/appointments/{reference}/confirm", headers=_headers(TENANT, service=True), json=confirm_body
    )
    confirmed_again = client.post(
        f"/api/v1/appointments/{reference}/confirm", headers=_headers(TENANT, token), json=confirm_body
    )
    assert confirmed.status_code == 200, confirmed.text
    assert (confirmed.json()["previous_status"], confirmed.json()["status"]) == ("pending", "confirmed")
    assert confirmed.json()["confirmed_at"] is not None
    assert confirmed_again.status_code == 200, confirmed_again.text
    assert confirmed_again.json()["previous_status"] == "confirmed"

    # --- reschedule to the second slot ---------------------------------
    rescheduled = client.post(
        f"/api/v1/appointments/{reference}/reschedule",
        headers=_headers(TENANT, service=True),
        json={"national_id": NID_CLINIC_2, "new_slot_id": second_slot},
    )
    assert rescheduled.status_code == 200, rescheduled.text
    assert rescheduled.json()["new_slot_id"] == second_slot
    assert rescheduled.json()["old_slot_status"] == "available"

    # --- cancel ---------------------------------------------------------
    cancelled = client.post(
        f"/api/v1/appointments/{reference}/cancel",
        headers=_headers(TENANT, service=True),
        json={"national_id": NID_CLINIC_2, "reason": "pytest"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["slot_status"] == "available"

    cannot_confirm = client.post(
        f"/api/v1/appointments/{reference}/confirm", headers=_headers(TENANT, service=True), json=confirm_body
    )
    assert cannot_confirm.status_code == 409

    events = [
        row[0]
        for row in db_session.execute(
            text(
                "SELECT h.event_type FROM dbo.appointment_status_history AS h "
                "JOIN dbo.appointments AS a ON a.id = h.appointment_id "
                "WHERE a.provider_id = :p AND a.appointment_reference = :r "
                "ORDER BY h.changed_at, CASE h.event_type WHEN 'created' THEN 0 "
                "WHEN 'confirmed' THEN 1 WHEN 'rescheduled' THEN 2 ELSE 3 END"
            ),
            {"p": str(clinic_2.id), "r": reference},
        ).all()
    ]
    assert events == ["created", "confirmed", "rescheduled", "cancelled"]

    # --- analytics + audit trail for the provider admin ----------------
    analytics = client.get(
        f"/api/v1/analytics/appointments?date_from={target_date}&date_to={target_date}",
        headers=_headers(TENANT, token),
    )
    assert analytics.status_code == 200
    assert analytics.json()["by_status"].get("cancelled", 0) >= 1

    audit_events = client.get("/api/v1/audit-events?limit=200", headers=_headers(TENANT, token))
    assert audit_events.status_code == 200
    assert {"doctor.create", "working_hours.create", "appointment.read", "appointment.confirm"} <= {
        row["action"] for row in audit_events.json()
    }
    assert all(row["provider_id"] == str(clinic_2.id) for row in audit_events.json())


def test_concurrent_slot_guard_exists(db_session):
    """The unique filtered index is the last line of defence against two
    transactions booking one slot (the service also locks the slot row)."""
    row = db_session.execute(
        text(
            "SELECT i.is_unique, i.has_filter, i.filter_definition "
            "FROM sys.indexes AS i WHERE i.name = 'UX_appointments_active_slot'"
        )
    ).mappings().first()

    assert row is not None
    assert row["is_unique"] and row["has_filter"]
    assert "cancelled" in row["filter_definition"]


def test_global_search_filters_run_on_sql_server(db_session):
    """Every search filter executes on SQL Server and returns only matching rows."""
    client, clinic_2, _ = _client(db_session)

    branch = one(
        db_session,
        "SELECT TOP 1 id, governorate FROM dbo.branches "
        "WHERE provider_id = :p AND is_active = 1 AND governorate IS NOT NULL ORDER BY code",
        p=str(clinic_2.id),
    )
    link = one(
        db_session,
        """
        SELECT TOP 1 doctor.full_name_en, specialty.code AS specialty_code,
               service.code AS service_code
        FROM dbo.doctors AS doctor
        JOIN dbo.specialties AS specialty ON specialty.id = doctor.specialty_id
        JOIN dbo.doctor_services AS ds ON ds.doctor_id = doctor.id AND ds.is_active = 1
        JOIN dbo.services AS service ON service.id = ds.service_id AND service.is_active = 1
        JOIN dbo.doctor_branches AS db ON db.doctor_id = doctor.id AND db.is_active = 1
        WHERE doctor.provider_id = :p AND doctor.is_active = 1 AND db.branch_id = :b
        ORDER BY doctor.full_name_en
        """,
        p=str(clinic_2.id),
        b=str(branch.id),
    )

    providers = client.get(
        "/api/v1/search/providers",
        params={"governorate": branch.governorate, "specialty_code": link.specialty_code},
    )
    doctors = client.get(
        "/api/v1/search/doctors",
        params={
            "provider_id": str(clinic_2.id),
            "branch_id": str(branch.id),
            "governorate": branch.governorate,
            "specialty_code": link.specialty_code,
            "service_code": link.service_code,
            "q": link.full_name_en[:6],
        },
    )
    no_match = client.get("/api/v1/search/doctors", params={"q": "zz%_[no-such-doctor]"})

    assert providers.status_code == doctors.status_code == no_match.status_code == 200
    assert str(clinic_2.id) in {row["id"] for row in providers.json()}
    assert link.full_name_en in {row["full_name_en"] for row in doctors.json()}
    assert all(row["specialty_code"] == link.specialty_code for row in doctors.json())
    # LIKE wildcards in user text are matched literally.
    assert no_match.json() == []

    start = future_date(clinic_2.timezone, days=1)
    slots = client.get(
        "/api/v1/search/availability",
        params={
            "date_from": start.isoformat(),
            "date_to": (start + timedelta(days=6)).isoformat(),
            "time_from": "08:00",
            "time_to": "20:00",
            "org_type": "clinic",
            "governorate": branch.governorate,
            "specialty_code": link.specialty_code,
            "limit": 200,
        },
    )
    assert slots.status_code == 200
    for row in slots.json():
        assert row["provider_org_type"] == "clinic"
        assert row["governorate"] == branch.governorate
        assert row["specialty_code"] == link.specialty_code
        assert "08:00:00" <= row["start_time"] < "20:00:00"


def _doctor_body(session, clinic, name):
    return {
        "specialty_id": _first_id(
            session,
            "SELECT TOP 1 id FROM dbo.specialties WHERE provider_id = :p AND is_active = 1 ORDER BY code",
            p=str(clinic.id),
        ),
        "full_name_ar": "د. اختبار",
        "full_name_en": name,
        "branch_ids": [
            _first_id(
                session,
                "SELECT TOP 1 id FROM dbo.branches WHERE provider_id = :p AND is_active = 1 ORDER BY code",
                p=str(clinic.id),
            )
        ],
    }


def _count(session, sql, **params):
    return session.execute(text(sql), params).scalar_one()


def test_admin_doctor_create_retry_with_idempotency_key_creates_one_doctor(db_session, jwt_secret):
    client, clinic_2, _ = _client(db_session)
    token = _staff_token(db_session, clinic_2.id)
    name = f"Dr Pytest Idem {uuid4().hex[:8]}"
    body = _doctor_body(db_session, clinic_2, name)
    headers = _headers(TENANT, token, **{"Idempotency-Key": f"pytest-admin-{uuid4().hex}"})

    first = client.post("/api/v1/admin/doctors", headers=headers, json=body)
    retry = client.post("/api/v1/admin/doctors", headers=headers, json=body)
    changed = client.post(
        "/api/v1/admin/doctors", headers=headers, json={**body, "full_name_en": name + " B"}
    )

    assert first.status_code == retry.status_code == 201
    assert retry.json()["id"] == first.json()["id"]
    assert changed.status_code == 409
    assert changed.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert _count(db_session, "SELECT COUNT(*) FROM dbo.doctors WHERE full_name_en LIKE :n", n=name + "%") == 1
    assert _count(
        db_session,
        "SELECT COUNT(*) FROM dbo.staff_audit_logs WHERE action = 'doctor.create' AND resource_id = :d",
        d=first.json()["id"],
    ) == 1


def test_admin_doctor_create_is_not_saved_when_its_audit_fails(db_session, jwt_secret, monkeypatch):
    from app.services.staff_audit_service import StaffAuditService

    client, clinic_2, _ = _client(db_session)
    token = _staff_token(db_session, clinic_2.id)
    name = f"Dr Pytest NoAudit {uuid4().hex[:8]}"

    def failing_stage(self, **kwargs):
        raise RuntimeError("audit storage unavailable")

    monkeypatch.setattr(StaffAuditService, "stage", failing_stage)

    with pytest.raises(RuntimeError):
        client.post(
            "/api/v1/admin/doctors",
            headers=_headers(TENANT, token),
            json=_doctor_body(db_session, clinic_2, name),
        )

    # Write and audit share one transaction: no unaudited doctor exists.
    assert _count(db_session, "SELECT COUNT(*) FROM dbo.doctors WHERE full_name_en = :n", n=name) == 0
