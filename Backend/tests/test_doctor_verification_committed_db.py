"""
Committed rejection -> later booking, against a real database. WRITES COMMITTED ROWS.

Double opt-in: MEDMIND_DB_INTEGRATION=1 AND MEDMIND_DB_COMMIT_TESTS=1, plus
APP_ENV=staging and DB_SERVER / DB_NAME / DB_TRUSTED_CONNECTION set
explicitly to localhost\\SQLEXPRESS / MedMind_Audit_Final2 / true. Every
connection goes through the same fail-closed target guard as
test_doctor_verification_concurrency_db (before connecting) and checks
SELECT DB_NAME() after connecting.

No existing row is changed. The test creates, and commits, only test rows
marked with this run's id (license_number "ZZTEST-DV-<run>"):

  setup     doctors (1, 'verified'), doctor_branches (1), doctor_availability_slots (1)
  rejection via the real route: doctors status -> 'rejected' (that row only),
            doctor_verification_decisions (1), staff_audit_logs (1)
  booking   separate connection, always rolled back: expected 409
            DOCTOR_NOT_BOOKABLE, no appointment or status-history row
  retire    doctors is_active -> 0 (that row only)

Retention (policy "Option B"): every row above is kept permanently; nothing
is deleted. The retire step makes the kept doctor inert: an inactive doctor
is never listed, searched or bookable, with or without enforcement (its slot
stays but cannot be booked). Each run adds one such set of rows.

The retire step runs even when the test fails. It still retires the doctor,
then fails, if any committed appointment refers to the test doctor or slot
(a booking that leaked; kept for review). A run refuses to start while an
active "ZZTEST-DV-" doctor exists (an earlier run that was never retired).
DOCTOR_VERIFICATION_ENFORCED is turned on only inside this test process,
only for the booking step, and restored.
"""

import os
from contextlib import contextmanager
from datetime import date, time, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import dependencies as deps
from app.api.routers import admin_catalog, appointments
from app.core.config import get_settings, staging_selected
from app.security.staff_context import StaffContext
from tests.test_doctor_verification_concurrency_db import (
    _quietly,
    _require_approved_target,
    booking_service,
    guarded_session,
)
from tests.test_lab_booking_without_doctor_db import APPROVED_DATABASE, NATIONAL_ID


pytestmark = pytest.mark.skipif(
    os.getenv("MEDMIND_DB_INTEGRATION") != "1" or os.getenv("MEDMIND_DB_COMMIT_TESTS") != "1",
    reason="Writes committed rows: set MEDMIND_DB_INTEGRATION=1 and MEDMIND_DB_COMMIT_TESTS=1.",
)

MARKER_PREFIX = "ZZTEST-DV-"
REASON = "Committed-rejection test (disposable doctor)."


@pytest.fixture(autouse=True)
def enforcement_off_outside_the_booking_step():
    if not staging_selected():
        pytest.fail("SAFETY STOP: APP_ENV=staging is required for these tests.")
    get_settings.cache_clear()
    if get_settings().doctor_verification_enforced:
        pytest.fail("SAFETY STOP: DOCTOR_VERIFICATION_ENFORCED must be false outside the booking step.")
    yield
    get_settings.cache_clear()


@contextmanager
def enforcement_in_process():
    previous = os.environ.get("DOCTOR_VERIFICATION_ENFORCED")
    os.environ["DOCTOR_VERIFICATION_ENFORCED"] = "true"
    get_settings.cache_clear()
    try:
        assert get_settings().doctor_verification_enforced is True
        yield
    finally:
        if previous is None:
            os.environ.pop("DOCTOR_VERIFICATION_ENFORCED", None)
        else:
            os.environ["DOCTOR_VERIFICATION_ENFORCED"] = previous
        get_settings.cache_clear()


@contextmanager
def committing_connection():
    """A guarded connection WITHOUT an outer rollback: the caller commits
    explicitly. Anything not committed is rolled back; the connection is
    always discarded."""
    engine = _require_approved_target()
    connection = engine.connect()
    try:
        if connection.execute(text("SELECT DB_NAME()")).scalar_one() != APPROVED_DATABASE:
            pytest.fail("SAFETY STOP: unexpected connected database.")
        connection.rollback()
        connection.execute(text("SET LOCK_TIMEOUT 10000"))
        # End the transaction that statement auto-began (SET is a session
        # setting, not transactional): a Session bound to this connection
        # then begins, and really commits, its own transaction instead of
        # joining one it would never commit (the default
        # "conditional_savepoint" mode becomes "rollback_only" there).
        connection.commit()
        try:
            yield connection
        finally:
            _quietly(connection.rollback)  # no-op after an explicit commit
    finally:
        _quietly(connection.invalidate)
        _quietly(connection.close)


# ============================================================ committed seed (read only)

SEED_SQL = """
SELECT TOP 1
    provider.id AS provider_id, provider.tenant_key, provider.timezone,
    membership.id AS membership_id, membership.user_id,
    (SELECT TOP 1 b.id FROM dbo.branches AS b
     WHERE b.provider_id = provider.id AND b.is_active = 1 ORDER BY b.id) AS branch_id,
    (SELECT TOP 1 s.id FROM dbo.specialties AS s
     WHERE s.provider_id = provider.id AND s.is_active = 1 ORDER BY s.id) AS specialty_id,
    (SELECT TOP 1 sv.id FROM dbo.services AS sv
     WHERE sv.provider_id = provider.id AND sv.is_active = 1 ORDER BY sv.id) AS service_id,
    (SELECT TOP 1 p.national_id_hash
     FROM dbo.patients AS p
     JOIN dbo.patient_provider_profiles AS pp
         ON pp.patient_id = p.id AND pp.provider_id = provider.id AND pp.is_active = 1
     WHERE p.is_active = 1 AND p.national_id_hash IS NOT NULL ORDER BY p.id) AS patient_hash
FROM dbo.providers AS provider
JOIN dbo.provider_memberships AS membership
    ON membership.provider_id = provider.id
    AND membership.role = 'provider_admin' AND membership.is_active = 1
WHERE provider.is_active = 1
  AND provider.org_type <> 'diagnostic_lab'
  AND EXISTS (SELECT 1 FROM dbo.branches AS b WHERE b.provider_id = provider.id AND b.is_active = 1)
  AND EXISTS (SELECT 1 FROM dbo.specialties AS s WHERE s.provider_id = provider.id AND s.is_active = 1)
  AND EXISTS (SELECT 1 FROM dbo.services AS sv WHERE sv.provider_id = provider.id AND sv.is_active = 1)
  AND EXISTS (SELECT 1 FROM dbo.patient_provider_profiles AS pp
              JOIN dbo.patients AS p ON p.id = pp.patient_id
                  AND p.is_active = 1 AND p.national_id_hash IS NOT NULL
              WHERE pp.provider_id = provider.id AND pp.is_active = 1)
ORDER BY provider.tenant_key, membership.id
"""


def _active_test_doctors():
    """Kept test doctors that were never retired (still listable/bookable)."""
    with guarded_session() as db:
        return db.session.execute(
            text("SELECT COUNT(*) FROM dbo.doctors WHERE license_number LIKE :marker AND is_active = 1"),
            {"marker": f"{MARKER_PREFIX}%"},
        ).scalar_one()


def _committed(sql, **params):
    """One read on a fresh guarded connection: the committed state."""
    with guarded_session() as db:
        return db.session.execute(text(sql), params).scalar_one()


# ============================================================ setup and cleanup


def _create_disposable_rows(seed, ids, run):
    with committing_connection() as connection:
        connection.execute(
            text(
                """
                INSERT INTO dbo.doctors
                    (id, provider_id, specialty_id, full_name_ar, full_name_en, license_number,
                     verification_status, is_active)
                VALUES (:id, :provider_id, :specialty_id, :name, :name, :license, 'verified', 1)
                """
            ),
            {"id": str(ids.doctor), "provider_id": str(seed.provider_id),
             "specialty_id": str(seed.specialty_id), "name": f"ZZ TEST doctor verification {run}",
             "license": f"{MARKER_PREFIX}{run}"},
        )
        connection.execute(
            text(
                """
                INSERT INTO dbo.doctor_branches (id, provider_id, doctor_id, branch_id, is_primary, is_active)
                VALUES (:id, :provider_id, :doctor_id, :branch_id, 1, 1)
                """
            ),
            {"id": str(ids.doctor_branch), "provider_id": str(seed.provider_id),
             "doctor_id": str(ids.doctor), "branch_id": str(seed.branch_id)},
        )
        connection.execute(
            text(
                """
                INSERT INTO dbo.doctor_availability_slots
                    (id, provider_id, doctor_id, branch_id, slot_date, start_time, end_time, status)
                VALUES (:id, :provider_id, :doctor_id, :branch_id, :slot_date, :start_time, :end_time, 'available')
                """
            ),
            {"id": str(ids.slot), "provider_id": str(seed.provider_id), "doctor_id": str(ids.doctor),
             "branch_id": str(seed.branch_id), "slot_date": ids.slot_date,
             "start_time": time(5, 0), "end_time": time(5, 15)},
        )
        connection.commit()


def _retire_test_doctor(ids):
    """Option B: keep every test row; only make the kept doctor inactive,
    so it can never be listed or booked. Nothing is deleted. Fails (after
    retiring) if a committed appointment refers to the test doctor or slot."""
    params = {"doctor_id": str(ids.doctor), "slot_id": str(ids.slot), "marker": f"{MARKER_PREFIX}%"}
    with committing_connection() as connection:
        retired = connection.execute(
            text(
                "UPDATE dbo.doctors SET is_active = 0, updated_at = SYSUTCDATETIME() "
                "WHERE id = :doctor_id AND license_number LIKE :marker"
            ),
            params,
        ).rowcount
        assert retired == 1, f"retire expected 1 test doctor row, got {retired}"
        connection.commit()
        leaked = connection.execute(
            text("SELECT COUNT(*) FROM dbo.appointments WHERE doctor_id = :doctor_id OR slot_id = :slot_id"),
            params,
        ).scalar_one()
        connection.rollback()  # ends the read's transaction; nothing to undo
    if leaked:
        pytest.fail(
            f"{leaked} committed appointment(s) refer to the test doctor/slot (doctor {ids.doctor}). "
            "The doctor was retired; every row is kept for review."
        )


@pytest.fixture
def disposable_doctor():
    if _active_test_doctors():
        pytest.fail(
            f"SAFETY STOP: an active test doctor ({MARKER_PREFIX}*) from an earlier run was never "
            "retired and may be listable or bookable; review it before another run."
        )
    with guarded_session() as db:
        row = db.connection.execute(text(SEED_SQL)).mappings().first()
    if row is None or None in (row["branch_id"], row["specialty_id"], row["service_id"], row["patient_hash"]):
        pytest.skip("No provider with an active provider_admin, branch, specialty, service and patient profile.")

    seed = SimpleNamespace(**{k: row[k] for k in ("tenant_key", "timezone", "patient_hash")})
    for key in ("provider_id", "membership_id", "user_id", "branch_id", "specialty_id", "service_id"):
        setattr(seed, key, UUID(str(row[key])))
    run = uuid4().hex[:12]
    ids = SimpleNamespace(
        doctor=uuid4(), doctor_branch=uuid4(), slot=uuid4(),
        slot_date=date.today() + timedelta(days=30),  # far from the seeded slots
    )
    _create_disposable_rows(seed, ids, run)
    try:
        yield SimpleNamespace(seed=seed, ids=ids, run=run)
    finally:
        _retire_test_doctor(ids)
        assert _active_test_doctors() == 0
        # Kept, inert: the doctor row is inactive; nothing was deleted.
        assert _committed(
            "SELECT COUNT(*) FROM dbo.doctors WHERE id = :id AND is_active = 0", id=str(ids.doctor),
        ) == 1


# ============================================================ the test


def test_a_committed_rejection_blocks_a_later_booking(disposable_doctor):
    seed, ids = disposable_doctor.seed, disposable_doctor.ids
    admin = StaffContext(
        user_id=seed.user_id, membership_id=seed.membership_id, provider_id=seed.provider_id,
        role="provider_admin", doctor_id=None,
    )

    # 1. Reject through the real route; the service's commit() really commits.
    with committing_connection() as connection:
        session = Session(bind=connection, autoflush=False, expire_on_commit=False)
        try:
            app = FastAPI()
            app.include_router(admin_catalog.router, prefix="/api/v1")
            app.dependency_overrides[deps.get_db_session] = lambda: session
            app.dependency_overrides[deps.get_current_staff] = lambda: admin
            rejected = TestClient(app).post(
                f"/api/v1/admin/doctors/{ids.doctor}/verification",
                json={"decision": "rejected", "reason": REASON},
                headers={"X-Tenant-ID": seed.tenant_key},
            )
        finally:
            session.close()
    assert rejected.status_code == 200
    assert rejected.json()["verification_status"] == "rejected"

    # 2. Durable: seen from a new connection.
    doctor = {"id": str(ids.doctor)}
    assert _committed("SELECT verification_status FROM dbo.doctors WHERE id = :id", **doctor) == "rejected"
    assert _committed(
        "SELECT COUNT(*) FROM dbo.doctor_verification_decisions "
        "WHERE doctor_id = :id AND decision = 'rejected' AND previous_status = 'verified'", **doctor,
    ) == 1
    assert _committed(
        "SELECT COUNT(*) FROM dbo.staff_audit_logs "
        "WHERE resource_type = 'doctor' AND resource_id = :id AND action = 'doctor.reject'", **doctor,
    ) == 1

    # 3. A later booking, in a separate (always rolled back) transaction, with
    #    enforcement on in this process only.
    with enforcement_in_process(), guarded_session() as db:
        app = FastAPI()
        app.include_router(appointments.router, prefix="/api/v1")
        app.dependency_overrides[deps.get_db_session] = lambda: db.session
        app.dependency_overrides[deps.get_appointment_service] = lambda: booking_service(
            db.session, seed.patient_hash,
        )
        history_before = db.session.execute(text("SELECT COUNT(*) FROM dbo.appointment_status_history")).scalar_one()

        booking = TestClient(app).post(
            "/api/v1/appointments",
            json={"national_id": NATIONAL_ID, "slot_id": str(ids.slot),
                  "service_id": str(seed.service_id), "channel": "web"},
            headers={"X-Tenant-ID": seed.tenant_key},
        )

        assert booking.status_code == 409
        assert booking.json()["detail"]["code"] == "DOCTOR_NOT_BOOKABLE"
        assert db.session.execute(
            text("SELECT COUNT(*) FROM dbo.appointments WHERE slot_id = :slot OR doctor_id = :doctor"),
            {"slot": str(ids.slot), "doctor": str(ids.doctor)},
        ).scalar_one() == 0
        assert db.session.execute(text("SELECT COUNT(*) FROM dbo.appointment_status_history")).scalar_one() \
            == history_before
        assert db.session.execute(
            text("SELECT status FROM dbo.doctor_availability_slots WHERE id = :id"), {"id": str(ids.slot)},
        ).scalar_one() == "available"

    # 4. The committed rejection is still in effect; nothing was booked.
    assert _committed("SELECT verification_status FROM dbo.doctors WHERE id = :id", **doctor) == "rejected"
    assert _committed("SELECT COUNT(*) FROM dbo.appointments WHERE doctor_id = :id", **doctor) == 0
