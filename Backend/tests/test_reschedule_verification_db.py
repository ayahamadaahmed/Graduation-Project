"""
Rescheduling vs doctor verification, against a real database - opt-in.

Opt-in only: MEDMIND_DB_INTEGRATION=1, plus APP_ENV=staging and DB_SERVER /
DB_NAME / DB_TRUSTED_CONNECTION set explicitly to localhost\\SQLEXPRESS /
MedMind_Audit_Final2 / true. Every connection goes through
test_doctor_verification_concurrency_db.guarded_session: the fail-closed
target guard before connecting, SELECT DB_NAME() after, one outer
transaction that is ALWAYS rolled back, and the connection discarded.

Nothing is committed. Each test builds its own world inside that one
transaction: two test doctors (A verified, B rejected; license
"ZZTEST-RS-<run>"), their branch and service links, four slots 30 days
ahead, and two appointments booked on doctor A through the real booking
service. No existing doctor, slot or appointment is used or changed; the
reads use an existing provider, branch, service and patient only.

Single-session tests: they prove the reschedule rules (refusal before any
write, and the slot conditions), not cross-session locking. Cross-session
reschedule concurrency needs rows committed before the test, so that both
connections see them: it is designed in the report, not implemented here.
"""

import os
from datetime import date, time, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import dependencies as deps
from app.api.routers import appointments
from app.core.config import get_settings, staging_selected
from app.schemas.appointment import AppointmentCreateRequest
from tests.test_doctor_verification_committed_db import enforcement_in_process
from tests.test_doctor_verification_concurrency_db import booking_service, guarded_session
from tests.test_lab_booking_without_doctor_db import NATIONAL_ID


pytestmark = pytest.mark.skipif(
    os.getenv("MEDMIND_DB_INTEGRATION") != "1",
    reason="Set MEDMIND_DB_INTEGRATION=1 to run against an audit database.",
)

MARKER_PREFIX = "ZZTEST-RS-"


@pytest.fixture(autouse=True)
def enforcement_off_outside_overrides():
    if not staging_selected():
        pytest.fail("SAFETY STOP: APP_ENV=staging is required for these tests.")
    get_settings.cache_clear()
    if get_settings().doctor_verification_enforced:
        pytest.fail("SAFETY STOP: DOCTOR_VERIFICATION_ENFORCED must be false outside test overrides.")
    yield
    get_settings.cache_clear()


# A non-lab provider with an active branch that has an MRN code, a specialty
# and a service, and a patient with active provider AND branch profiles at
# that branch (so booking never creates a profile or touches MRN sequences).
SEED_SQL = """
SELECT TOP 1
    provider.id AS provider_id, provider.tenant_key, provider.timezone,
    branch.id AS branch_id,
    (SELECT TOP 1 s.id FROM dbo.specialties AS s
     WHERE s.provider_id = provider.id AND s.is_active = 1 ORDER BY s.id) AS specialty_id,
    (SELECT TOP 1 sv.id FROM dbo.services AS sv
     WHERE sv.provider_id = provider.id AND sv.is_active = 1 ORDER BY sv.id) AS service_id,
    (SELECT TOP 1 p.national_id_hash
     FROM dbo.patients AS p
     JOIN dbo.patient_provider_profiles AS pp
         ON pp.patient_id = p.id AND pp.provider_id = provider.id AND pp.is_active = 1
     JOIN dbo.patient_branch_profiles AS bp
         ON bp.patient_id = p.id AND bp.provider_id = provider.id AND bp.branch_id = branch.id
         AND bp.is_active = 1
     WHERE p.is_active = 1 AND p.national_id_hash IS NOT NULL ORDER BY p.id) AS patient_hash
FROM dbo.providers AS provider
JOIN dbo.branches AS branch
    ON branch.provider_id = provider.id AND branch.is_active = 1 AND branch.mrn_code IS NOT NULL
WHERE provider.is_active = 1
  AND provider.org_type <> 'diagnostic_lab'
  AND EXISTS (SELECT 1 FROM dbo.specialties AS s WHERE s.provider_id = provider.id AND s.is_active = 1)
  AND EXISTS (SELECT 1 FROM dbo.services AS sv WHERE sv.provider_id = provider.id AND sv.is_active = 1)
  AND EXISTS (SELECT 1 FROM dbo.patient_provider_profiles AS pp
              JOIN dbo.patients AS p ON p.id = pp.patient_id
                  AND p.is_active = 1 AND p.national_id_hash IS NOT NULL
              JOIN dbo.patient_branch_profiles AS bp
                  ON bp.patient_id = p.id AND bp.provider_id = provider.id AND bp.branch_id = branch.id
                  AND bp.is_active = 1
              WHERE pp.provider_id = provider.id AND pp.is_active = 1)
ORDER BY provider.tenant_key, branch.id
"""


def _insert_test_world(connection, seed, ids, run):
    """Uncommitted inserts on the connection, before the Session's first
    statement (so no service rollback can undo them)."""
    for doctor, status in ((ids.doctor_a, "verified"), (ids.doctor_b, "rejected")):
        connection.execute(
            text(
                """
                INSERT INTO dbo.doctors
                    (id, provider_id, specialty_id, full_name_ar, full_name_en, license_number,
                     verification_status, is_active)
                VALUES (:id, :provider_id, :specialty_id, :name, :name, :license, :status, 1)
                """
            ),
            {"id": str(doctor), "provider_id": str(seed.provider_id), "specialty_id": str(seed.specialty_id),
             "name": f"ZZ TEST reschedule {run} {status}", "license": f"{MARKER_PREFIX}{run}-{status[0]}",
             "status": status},
        )
        connection.execute(
            text(
                "INSERT INTO dbo.doctor_branches (id, provider_id, doctor_id, branch_id, is_primary, is_active) "
                "VALUES (:id, :provider_id, :doctor_id, :branch_id, 1, 1)"
            ),
            {"id": str(uuid4()), "provider_id": str(seed.provider_id), "doctor_id": str(doctor),
             "branch_id": str(seed.branch_id)},
        )
        connection.execute(
            text(
                "INSERT INTO dbo.doctor_services (id, provider_id, doctor_id, service_id, is_active) "
                "VALUES (:id, :provider_id, :doctor_id, :service_id, 1)"
            ),
            {"id": str(uuid4()), "provider_id": str(seed.provider_id), "doctor_id": str(doctor),
             "service_id": str(seed.service_id)},
        )
    for slot, doctor, start in (
        (ids.a_old_1, ids.doctor_a, time(5, 0)),
        (ids.a_old_2, ids.doctor_a, time(5, 15)),
        (ids.a_new, ids.doctor_a, time(5, 30)),
        (ids.b_new, ids.doctor_b, time(5, 45)),
    ):
        connection.execute(
            text(
                """
                INSERT INTO dbo.doctor_availability_slots
                    (id, provider_id, doctor_id, branch_id, slot_date, start_time, end_time, status)
                VALUES (:id, :provider_id, :doctor_id, :branch_id, :slot_date, :start_time, :end_time, 'available')
                """
            ),
            {"id": str(slot), "provider_id": str(seed.provider_id), "doctor_id": str(doctor),
             "branch_id": str(seed.branch_id), "slot_date": ids.slot_date, "start_time": start,
             "end_time": time(start.hour, start.minute + 15) if start.minute < 45 else time(start.hour + 1, 0)},
        )


@pytest.fixture
def world():
    with guarded_session() as db:
        row = db.connection.execute(text(SEED_SQL)).mappings().first()
        if row is None or None in (row["specialty_id"], row["service_id"], row["patient_hash"]):
            pytest.skip("No non-lab provider with an MRN branch, specialty, service and profiled patient.")
        seed = SimpleNamespace(tenant_key=row["tenant_key"], timezone=row["timezone"],
                               patient_hash=row["patient_hash"])
        for key in ("provider_id", "branch_id", "specialty_id", "service_id"):
            setattr(seed, key, UUID(str(row[key])))
        run = uuid4().hex[:10]
        ids = SimpleNamespace(
            doctor_a=uuid4(), doctor_b=uuid4(),
            a_old_1=uuid4(), a_old_2=uuid4(), a_new=uuid4(), b_new=uuid4(),
            slot_date=date.today() + timedelta(days=30),
        )
        _insert_test_world(db.connection, seed, ids, run)

        # Two starting appointments on doctor A, through the real booking
        # service (its commit() only releases a SAVEPOINT).
        booker = booking_service(db.session, seed.patient_hash)
        references = [
            booker.create_confirmed_booking(
                provider_id=seed.provider_id, provider_timezone=seed.timezone,
                data=AppointmentCreateRequest(national_id=NATIONAL_ID, slot_id=slot,
                                              service_id=seed.service_id, channel="web"),
            ).appointment_reference
            for slot in (ids.a_old_1, ids.a_old_2)
        ]

        app = FastAPI()
        app.include_router(appointments.router, prefix="/api/v1")
        app.dependency_overrides[deps.get_db_session] = lambda: db.session
        app.dependency_overrides[deps.get_appointment_service] = lambda: booking_service(
            db.session, seed.patient_hash,
        )
        yield SimpleNamespace(db=db, seed=seed, ids=ids, client=TestClient(app),
                              first=references[0], second=references[1])

    # Everything was rolled back: no test doctor reached the committed state.
    with guarded_session() as check:
        assert check.session.execute(
            text("SELECT COUNT(*) FROM dbo.doctors WHERE license_number LIKE :marker"),
            {"marker": f"{MARKER_PREFIX}%"},
        ).scalar_one() == 0


def reschedule(world, reference, new_slot):
    return world.client.post(
        f"/api/v1/appointments/{reference}/reschedule",
        json={"national_id": NATIONAL_ID, "new_slot_id": str(new_slot), "reason": "test"},
        headers={"X-Tenant-ID": world.seed.tenant_key},
    )


def appointment(world, reference):
    row = world.db.session.execute(
        text(
            "SELECT id, slot_id, doctor_id, status, reschedule_count FROM dbo.appointments "
            "WHERE provider_id = :provider_id AND appointment_reference = :reference"
        ),
        {"provider_id": str(world.seed.provider_id), "reference": reference},
    ).one()
    return SimpleNamespace(id=UUID(str(row[0])), slot_id=UUID(str(row[1])), doctor_id=UUID(str(row[2])),
                           status=row[3], reschedule_count=row[4])


def slot_status(world, slot_id):
    return world.db.session.execute(
        text("SELECT status FROM dbo.doctor_availability_slots WHERE id = :id"), {"id": str(slot_id)},
    ).scalar_one()


def history_count(world, appointment_id):
    return world.db.session.execute(
        text("SELECT COUNT(*) FROM dbo.appointment_status_history WHERE appointment_id = :id"),
        {"id": str(appointment_id)},
    ).scalar_one()


# ============================================================ tests


def test_rescheduling_onto_a_rejected_doctor_is_409_and_changes_nothing(world):
    before = appointment(world, world.first)
    history_before = history_count(world, before.id)

    with enforcement_in_process():
        response = reschedule(world, world.first, world.ids.b_new)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "DOCTOR_NOT_BOOKABLE"
    after = appointment(world, world.first)
    assert (after.slot_id, after.doctor_id, after.status, after.reschedule_count) == (
        world.ids.a_old_1, world.ids.doctor_a, before.status, before.reschedule_count,
    )
    assert slot_status(world, world.ids.a_old_1) == "booked"
    assert slot_status(world, world.ids.b_new) == "available"
    assert history_count(world, before.id) == history_before


def test_rescheduling_onto_a_verified_doctor_succeeds_control(world):
    before = appointment(world, world.first)
    history_before = history_count(world, before.id)

    with enforcement_in_process():
        response = reschedule(world, world.first, world.ids.a_new)

    assert response.status_code == 200
    after = appointment(world, world.first)
    assert (after.slot_id, after.reschedule_count) == (world.ids.a_new, before.reschedule_count + 1)
    assert slot_status(world, world.ids.a_old_1) == "available"
    assert slot_status(world, world.ids.a_new) == "booked"
    assert history_count(world, before.id) == history_before + 1


def test_without_enforcement_a_rejected_doctor_is_still_reschedulable(world):
    """Documents the rollout gate: with the flag off (the default), the
    verification status is not checked."""
    response = reschedule(world, world.first, world.ids.b_new)

    assert response.status_code == 200
    assert appointment(world, world.first).doctor_id == world.ids.doctor_b


def test_two_reschedules_onto_one_slot_only_one_succeeds(world):
    """Sequential, one transaction: the slot rule (only an 'available' slot
    can be taken), not cross-session locking."""
    second_before = appointment(world, world.second)
    history_before = history_count(world, second_before.id)

    assert reschedule(world, world.first, world.ids.a_new).status_code == 200
    loser = reschedule(world, world.second, world.ids.a_new)

    assert loser.status_code == 409
    assert loser.json()["detail"]["code"] == "NEW_SLOT_UNAVAILABLE"
    second_after = appointment(world, world.second)
    assert (second_after.slot_id, second_after.reschedule_count) == (world.ids.a_old_2, second_before.reschedule_count)
    assert slot_status(world, world.ids.a_old_2) == "booked"
    assert appointment(world, world.first).slot_id == world.ids.a_new
    assert history_count(world, second_before.id) == history_before
