"""
Doctor verification vs booking - lock behavior against a real database.

Opt-in only: MEDMIND_DB_INTEGRATION=1, plus APP_ENV=staging and DB_SERVER /
DB_NAME / DB_TRUSTED_CONNECTION set explicitly to localhost\\SQLEXPRESS /
MedMind_Audit_Final2 / true. Every connection passes the same fail-closed
guard as tests/test_booking_concurrency_db.py, before and after connecting.

Nothing is ever committed: each connection runs inside one outer
transaction that is always rolled back (a service's commit() only releases
a SAVEPOINT), and the connection is then discarded. So every "rejection"
here is uncommitted or rolled back: these tests prove who waits for whom,
never a booking that runs after a rejection really committed (that needs a
disposable copy of the database).

What each test proves about doctor_is_verified's WITH (HOLDLOCK, ROWLOCK):

- Proves HOLDLOCK (fails if the shared lock is released after the read):
  test_repo_booking_status_read_blocks_a_rejection_until_the_booking_ends,
  and the two stress tests, which assert at least one rejection issued
  while a booking held the doctor and that it waited for that booking.
- Compatibility only (fails with UPDLOCK, passes with or without HOLDLOCK):
  test_repo_two_booking_status_reads_of_one_doctor_do_not_block,
  test_service_bookings_of_one_doctor_on_two_slots_do_not_block, and the
  stress tests' check that booking holds overlapped each other.
- Depends on READ_COMMITTED_SNAPSHOT: the two "uncommitted rejection" tests
  prove the hint only when RCSI is ON; with RCSI off a plain read waits
  too, so they pass with or without HOLDLOCK.
- Controls: test_repo_rejection_update_is_not_blocked_without_a_booking and
  the not-enforced run of the two-slot booking test.
- Service refusal: test_service_booking_of_a_rejected_doctor_is_409_without_writes
  (one session; not a cross-session test).

Cross-session tests use only rows already committed in the audit copy and
skip when none fit. Repository-level tests (doctor_is_verified and the
conditional status UPDATE) insert nothing and need no enforcement. The
service-flow tests turn DOCTOR_VERIFICATION_ENFORCED on inside this test
process only, and restore it.
"""

import os
import random
import re
import threading
import time
from contextlib import contextmanager
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings, staging_selected
from app.repositories.admin_catalog_repository import AdminCatalogRepository
from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.patient_branch_profile_repository import (
    PatientBranchProfileRepository,
)
from app.repositories.patient_repository import PatientRepository
from app.repositories.staff_audit_repository import StaffAuditRepository
from app.schemas.appointment import AppointmentCreateRequest
from app.security.staff_context import StaffContext
from app.services.admin_catalog_service import AdminCatalogService
from app.services.appointment_service import AppointmentService
from app.services.patient_branch_profile_service import (
    PatientBranchProfileService,
)
from app.services.staff_audit_service import StaffAuditService
from tests.test_lab_booking_without_doctor_db import (
    APPROVED_DATABASE,
    APPROVED_SERVER,
    NATIONAL_ID,
    FixedHashProtector,
    unsafe_engine_target,
)


pytestmark = pytest.mark.skipif(
    os.getenv("MEDMIND_DB_INTEGRATION") != "1",
    reason="Set MEDMIND_DB_INTEGRATION=1 to run against an audit database.",
)

LOCK_TIMEOUT_MS = 2000
LONG_LOCK_TIMEOUT_MS = 10000
JOIN_TIMEOUT_S = 30
STRESS_JOIN_TIMEOUT_S = 180
# After the stop signal a worker finishes its current iteration: a few
# statements, each bounded by LONG_LOCK_TIMEOUT_MS.
STOP_GRACE_S = 60

# SQL Server error numbers.
LOCK_TIMEOUT_ERROR = 1222
DEADLOCK_ERROR = 1205

REASON = "Concurrency test rejection (always rolled back)."


# ============================================================ safety


def _require_approved_target():
    """Fail closed before any connection: the db_session rules, plus staging
    (so no .env file can supply or change the target)."""
    if not staging_selected():
        pytest.fail("SAFETY STOP: APP_ENV=staging is required for these tests.")

    settings = get_settings()
    if (
        settings.db_server != APPROVED_SERVER
        or settings.db_name != APPROVED_DATABASE
        or not settings.db_trusted_connection
    ):
        pytest.fail(
            "SAFETY STOP: tests may connect only to "
            r"localhost\SQLEXPRESS"
            " / MedMind_Audit_Final2 using Windows Trusted Connection."
        )

    from app.db.session import engine

    # The engine's own target, still before connecting (see db_session).
    reason = unsafe_engine_target(engine)
    if reason is not None:
        pytest.fail(f"SAFETY STOP: the engine does not target the approved audit database ({reason}).")

    return engine


def _quietly(cleanup):
    # A deadlock victim's transaction is already rolled back by the server,
    # so ROLLBACK (TO SAVEPOINT) may fail here; nothing is left to undo.
    try:
        cleanup()
    except SQLAlchemyError:
        pass


@contextmanager
def guarded_session(lock_timeout_ms=LOCK_TIMEOUT_MS):
    """One guarded connection inside an outer transaction that is always
    rolled back. Never returned to the pool: it carries LOCK_TIMEOUT and may
    hold a transaction that a deadlock already aborted."""
    engine = _require_approved_target()
    connection = engine.connect()
    try:
        if connection.execute(text("SELECT DB_NAME()")).scalar_one() != APPROVED_DATABASE:
            pytest.fail("SAFETY STOP: unexpected connected database.")
        connection.rollback()

        outer = connection.begin()
        connection.execute(text(f"SET LOCK_TIMEOUT {int(lock_timeout_ms)}"))
        # Same flush/expiry behavior as SessionLocal (app/db/session.py).
        session = Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            autoflush=False,
            expire_on_commit=False,
        )
        try:
            yield SimpleNamespace(session=session, connection=connection)
        finally:
            _quietly(session.close)
            _quietly(outer.rollback)
    finally:
        _quietly(connection.invalidate)
        _quietly(connection.close)


# Every worker thread these tests start, so none can run on unnoticed.
_WORKER_THREADS = []


def _wait_for(threads, seconds):
    deadline = time.monotonic() + seconds
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    return [thread for thread in threads if thread.is_alive()]


@pytest.fixture(autouse=True)
def no_worker_threads_left_running():
    """Refuse to start a test while an earlier test's worker still runs (its
    connection could still hold doctor or slot locks), and report one that
    outlives this test."""
    leftover = _wait_for([t for t in _WORKER_THREADS if t.is_alive()], STOP_GRACE_S)
    if leftover:
        pytest.fail(
            "SAFETY STOP: worker threads from an earlier test are still running "
            f"({', '.join(t.name for t in leftover)}); their open transactions may "
            "hold locks until LOCK_TIMEOUT, so this test would not be reliable. "
            "Nothing they do is committed. Rerun this module on its own."
        )
    yield
    still_running = _wait_for([t for t in _WORKER_THREADS if t.is_alive()], STOP_GRACE_S)
    _WORKER_THREADS[:] = still_running
    if still_running:
        pytest.fail(
            f"Worker threads still running after the test: {', '.join(t.name for t in still_running)}. "
            "Their transactions are never committed, but they may keep holding locks "
            "until LOCK_TIMEOUT and affect later tests in this run."
        )


@pytest.fixture(autouse=True)
def enforcement_stays_off_outside_overrides():
    if not staging_selected():
        pytest.fail("SAFETY STOP: APP_ENV=staging is required for these tests.")
    get_settings.cache_clear()
    if get_settings().doctor_verification_enforced:
        pytest.fail(
            "SAFETY STOP: DOCTOR_VERIFICATION_ENFORCED must be false outside "
            "the in-process overrides of these tests."
        )
    yield
    get_settings.cache_clear()


@pytest.fixture
def enforcement_in_process():
    """DOCTOR_VERIFICATION_ENFORCED=true for this test process only; the
    previous value (normally unset) and the settings cache are restored."""
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


# ============================================================ helpers


_SQL_ERROR_NUMBER = re.compile(r"\((\d{3,5})\)")


def sql_error_numbers(exc: BaseException) -> frozenset[int]:
    """SQL Server error numbers, e.g. "... (1205)", from the exception and
    every exception chained to it (__cause__ and __context__). A failed
    rollback after a deadlock raises a second error; the 1205 stays
    visible through the chain."""
    numbers, seen, pending = set(), set(), [exc]
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, SQLAlchemyError):
            message = str(getattr(current, "orig", None) or current)
        elif type(current).__module__.startswith("pyodbc"):
            message = str(current)
        else:
            message = ""
        numbers.update(int(n) for n in _SQL_ERROR_NUMBER.findall(message))
        pending += [current.__cause__, current.__context__]
    return frozenset(numbers)


def describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}, SQL Server errors {sorted(sql_error_numbers(exc))}"


def timed(call):
    """Run one statement or service call: its value (or SQLAlchemy error),
    the SQL Server error numbers and the seconds it took."""
    started = time.monotonic()
    try:
        value, errors = call(), frozenset()
    except SQLAlchemyError as exc:
        value, errors = exc, sql_error_numbers(exc)
    return SimpleNamespace(value=value, errors=errors, waited=time.monotonic() - started)


def run_in_thread(target, name="worker"):
    outcome = {}

    def runner():
        try:
            outcome["result"] = target()
        except BaseException as exc:  # includes pytest.fail raised in the thread
            outcome["error"] = exc

    thread = threading.Thread(target=runner, name=name, daemon=True)
    _WORKER_THREADS.append(thread)
    thread.start()
    return thread, outcome


def join(thread, timeout=JOIN_TIMEOUT_S):
    thread.join(timeout)
    assert not thread.is_alive(), f"{thread.name} did not finish in time"


def run_workers(workers, stop):
    """Start every (name, function) worker; on every exit path signal `stop`
    and try to join all of them. Returns their outcomes."""
    started, expired = [], []
    try:
        for name, worker in workers:
            started.append(run_in_thread(worker, name))
        expired = _wait_for([thread for thread, _ in started], STRESS_JOIN_TIMEOUT_S)
    finally:
        stop.set()
        still_running = _wait_for([thread for thread, _ in started], STOP_GRACE_S)
    if still_running:
        pytest.fail(
            f"Workers did not stop: {', '.join(t.name for t in still_running)}. Their "
            "transactions are never committed, but they may still hold doctor or slot "
            "locks until LOCK_TIMEOUT; the next test refuses to start while they run."
        )
    if expired:
        pytest.fail(
            f"The {STRESS_JOIN_TIMEOUT_S} s worker deadline expired for "
            f"{', '.join(t.name for t in expired)}; they were stopped early, so this run is incomplete."
        )
    return [outcome for _, outcome in started]


def result_of(outcome):
    if "error" in outcome:
        raise outcome["error"]
    return outcome["result"]


def read_verified(db, doctor):
    """The booking check's locked read (doctor_is_verified)."""
    return AppointmentRepository(db.session).doctor_is_verified(
        provider_id=doctor.provider_id, doctor_id=doctor.id,
    )


def update_status(db, doctor, expected, new):
    """The verification workflow's conditional UPDATE."""
    return AdminCatalogRepository(db.session).set_doctor_verification_status(
        provider_id=doctor.provider_id, doctor_id=doctor.id,
        expected_status=expected, new_status=new,
    )


def committed_status(doctor):
    with guarded_session() as db:
        return db.session.execute(
            text("SELECT verification_status FROM dbo.doctors WHERE id = :id AND provider_id = :provider_id"),
            {"id": str(doctor.id), "provider_id": str(doctor.provider_id)},
        ).scalar_one()


def slot_state(session, slot_id):
    """(slot status, number of active appointments on the slot)."""
    row = session.execute(
        text(
            """
            SELECT
                slot.status,
                (SELECT COUNT(*) FROM dbo.appointments AS appointment
                 WHERE appointment.slot_id = slot.id
                   AND appointment.status <> 'cancelled') AS active_appointments
            FROM dbo.doctor_availability_slots AS slot
            WHERE slot.id = :id
            """
        ),
        {"id": str(slot_id)},
    ).one()
    return row[0], row[1]


def overlapping(holds_a, holds_b):
    """Pairs of holds (with .start and .end) whose intervals overlap."""
    return [(a, b) for a in holds_a for b in holds_b if a is not b and a.start < b.end and b.start < a.end]


def waits_for(holders, requesters):
    """(holder, requester) pairs where the requester was issued while the
    holder's recorded hold was in progress.

    Recorded holds lie inside the real lock hold (start taken once the lock
    is held, end taken before the release), so such a requester can only
    get its incompatible lock after holder.end."""
    return [(h, r) for h in holders for r in requesters if h.start < r.issued < h.end]


# ============================================================ committed seed data


@pytest.fixture
def doctor():
    """A committed, active, verified doctor (read only, never changed)."""
    with guarded_session() as db:
        row = db.session.execute(
            text(
                """
                SELECT TOP 1 doctor.id, doctor.provider_id
                FROM dbo.doctors AS doctor
                WHERE doctor.is_active = 1
                  AND doctor.verification_status = 'verified'
                ORDER BY doctor.provider_id, doctor.id
                """
            )
        ).mappings().first()
    if row is None:
        pytest.skip("No committed active, verified doctor in this audit copy.")
    return SimpleNamespace(id=UUID(str(row["id"])), provider_id=UUID(str(row["provider_id"])))


SLOT_CANDIDATES_SQL = """
SELECT TOP 500
    slot.id, slot.doctor_id, slot.provider_id, slot.branch_id, provider.timezone
FROM dbo.doctor_availability_slots AS slot
JOIN dbo.doctors AS doctor
    ON doctor.id = slot.doctor_id
    AND doctor.provider_id = slot.provider_id
    AND doctor.is_active = 1
    AND doctor.verification_status = 'verified'
JOIN dbo.doctor_branches AS doctor_branch
    ON doctor_branch.doctor_id = slot.doctor_id
    AND doctor_branch.branch_id = slot.branch_id
    AND doctor_branch.provider_id = slot.provider_id
    AND doctor_branch.is_active = 1
JOIN dbo.branches AS branch
    ON branch.id = slot.branch_id
    AND branch.provider_id = slot.provider_id
    AND branch.is_active = 1
    AND branch.mrn_code IS NOT NULL
JOIN dbo.providers AS provider
    ON provider.id = slot.provider_id
WHERE slot.status = 'available'
  AND slot.slot_date >= :min_date
ORDER BY slot.doctor_id, slot.branch_id, slot.slot_date, slot.start_time
"""

DOCTOR_SERVICE_SQL = """
SELECT TOP 1 doctor_service.service_id
FROM dbo.doctor_services AS doctor_service
JOIN dbo.services AS service
    ON service.id = doctor_service.service_id
    AND service.provider_id = :provider_id
    AND service.is_active = 1
WHERE doctor_service.provider_id = :provider_id
  AND doctor_service.doctor_id = :doctor_id
  AND doctor_service.is_active = 1
ORDER BY doctor_service.service_id
"""

# Patients with an existing active branch profile there, so booking never
# creates one (that path serializes on branch_mrn_sequences, unrelated).
BRANCH_PATIENTS_SQL = """
SELECT TOP (:limit) patient.national_id_hash
FROM dbo.patients AS patient
JOIN dbo.patient_provider_profiles AS provider_profile
    ON provider_profile.patient_id = patient.id
    AND provider_profile.provider_id = :provider_id
    AND provider_profile.is_active = 1
JOIN dbo.patient_branch_profiles AS branch_profile
    ON branch_profile.patient_id = patient.id
    AND branch_profile.provider_id = :provider_id
    AND branch_profile.branch_id = :branch_id
    AND branch_profile.is_active = 1
WHERE patient.is_active = 1
  AND patient.national_id_hash IS NOT NULL
ORDER BY patient.id
"""


def _min_slot_date():
    # Two days ahead: clear of PAST_SLOT in any provider time zone.
    return date.today() + timedelta(days=2)


def booking_seed(patients_needed):
    """Committed rows for cross-session booking: one verified doctor's
    future available slots (at least 2) at one branch with an MRN code, a
    service the doctor offers, and `patients_needed` distinct patients with
    active provider and branch profiles there. Skips when none fit."""
    with guarded_session() as db:
        groups = {}
        for row in db.session.execute(text(SLOT_CANDIDATES_SQL), {"min_date": _min_slot_date()}).mappings():
            key = (str(row["doctor_id"]), str(row["provider_id"]), str(row["branch_id"]))
            groups.setdefault(key, {"timezone": row["timezone"], "slot_ids": []})
            groups[key]["slot_ids"].append(UUID(str(row["id"])))

        for (doctor_id, provider_id, branch_id), group in groups.items():
            if len(group["slot_ids"]) < 2:
                continue
            service_id = db.session.execute(
                text(DOCTOR_SERVICE_SQL), {"provider_id": provider_id, "doctor_id": doctor_id},
            ).scalar()
            if service_id is None:
                continue
            hashes = db.session.execute(
                text(BRANCH_PATIENTS_SQL),
                {"limit": 3, "provider_id": provider_id, "branch_id": branch_id},
            ).scalars().all()
            if len(hashes) < patients_needed:
                continue
            return SimpleNamespace(
                doctor=SimpleNamespace(id=UUID(doctor_id), provider_id=UUID(provider_id)),
                provider_timezone=group["timezone"],
                slot_ids=group["slot_ids"],
                service_id=UUID(str(service_id)),
                patient_hashes=list(hashes),
            )

    pytest.skip(
        "No committed seed for the booking flow: a verified doctor with 2+ future "
        f"available slots at one branch with an MRN code, a service, and {patients_needed} "
        "patient(s) with active provider and branch profiles there."
    )


# The rejected-doctor booking stops at the eligibility check, before the
# service check, the branch profile (MRN) step and any write; so it needs
# no branch profile, MRN code or doctor-service link.
REFUSAL_SLOT_SQL = """
SELECT TOP 1 slot.id, slot.doctor_id, slot.provider_id, slot.branch_id, provider.timezone
FROM dbo.doctor_availability_slots AS slot
JOIN dbo.doctors AS doctor
    ON doctor.id = slot.doctor_id
    AND doctor.provider_id = slot.provider_id
    AND doctor.is_active = 1
    AND doctor.verification_status = 'verified'
JOIN dbo.doctor_branches AS doctor_branch
    ON doctor_branch.doctor_id = slot.doctor_id
    AND doctor_branch.branch_id = slot.branch_id
    AND doctor_branch.provider_id = slot.provider_id
    AND doctor_branch.is_active = 1
JOIN dbo.branches AS branch
    ON branch.id = slot.branch_id
    AND branch.provider_id = slot.provider_id
    AND branch.is_active = 1
JOIN dbo.providers AS provider
    ON provider.id = slot.provider_id
WHERE slot.status = 'available'
  AND slot.slot_date >= :min_date
  AND EXISTS (
      SELECT 1 FROM dbo.services AS service
      WHERE service.provider_id = slot.provider_id AND service.is_active = 1
  )
  AND EXISTS (
      SELECT 1
      FROM dbo.patient_provider_profiles AS provider_profile
      JOIN dbo.patients AS patient
          ON patient.id = provider_profile.patient_id
          AND patient.is_active = 1
          AND patient.national_id_hash IS NOT NULL
      WHERE provider_profile.provider_id = slot.provider_id
        AND provider_profile.is_active = 1
  )
ORDER BY slot.slot_date, slot.start_time, slot.id
"""

PROVIDER_PATIENT_SQL = """
SELECT TOP 1 patient.id, patient.national_id_hash
FROM dbo.patients AS patient
JOIN dbo.patient_provider_profiles AS provider_profile
    ON provider_profile.patient_id = patient.id
    AND provider_profile.provider_id = :provider_id
    AND provider_profile.is_active = 1
WHERE patient.is_active = 1
  AND patient.national_id_hash IS NOT NULL
ORDER BY patient.id
"""

PROVIDER_SERVICE_SQL = """
SELECT TOP 1 service.id
FROM dbo.services AS service
WHERE service.provider_id = :provider_id AND service.is_active = 1
ORDER BY CASE WHEN EXISTS (
             SELECT 1 FROM dbo.doctor_services AS doctor_service
             WHERE doctor_service.service_id = service.id
               AND doctor_service.doctor_id = :doctor_id
               AND doctor_service.is_active = 1
         ) THEN 0 ELSE 1 END,
         service.id
"""


def refusal_seed(connection):
    """Committed rows for the single-session refusal test, read on that
    test's own Connection (not its Session, see the test): a verified
    doctor's future available slot, a patient with an active provider
    profile, and an active service."""
    slot = connection.execute(text(REFUSAL_SLOT_SQL), {"min_date": _min_slot_date()}).mappings().first()
    if slot is None:
        pytest.skip(
            "No committed seed: a verified doctor's future available slot at an active "
            "branch of a provider with an active service and an active patient profile."
        )
    patient = connection.execute(text(PROVIDER_PATIENT_SQL), {"provider_id": str(slot["provider_id"])}).mappings().one()
    service_id = connection.execute(
        text(PROVIDER_SERVICE_SQL),
        {"provider_id": str(slot["provider_id"]), "doctor_id": str(slot["doctor_id"])},
    ).scalar_one()
    return SimpleNamespace(
        doctor=SimpleNamespace(id=UUID(str(slot["doctor_id"])), provider_id=UUID(str(slot["provider_id"]))),
        provider_timezone=slot["timezone"],
        slot_id=UUID(str(slot["id"])),
        branch_id=UUID(str(slot["branch_id"])),
        service_id=UUID(str(service_id)),
        patient_id=UUID(str(patient["id"])),
        patient_hash=patient["national_id_hash"],
    )


def reviewer_for(provider_id):
    """A committed, active provider_admin membership of the provider."""
    with guarded_session() as db:
        row = db.session.execute(
            text(
                """
                SELECT TOP 1 membership.id, membership.user_id
                FROM dbo.provider_memberships AS membership
                WHERE membership.provider_id = :provider_id
                  AND membership.role = 'provider_admin'
                  AND membership.is_active = 1
                ORDER BY membership.id
                """
            ),
            {"provider_id": str(provider_id)},
        ).mappings().first()
    if row is None:
        pytest.skip("No committed active provider_admin membership for the seed provider.")
    return StaffContext(
        user_id=UUID(str(row["user_id"])), membership_id=UUID(str(row["id"])),
        provider_id=provider_id, role="provider_admin", doctor_id=None,
    )


class RecordingAppointmentRepository(AppointmentRepository):
    """Records when the doctor-status lock is held (once the read returns)."""

    def __init__(self, session, lock_times):
        super().__init__(session)
        self.lock_times = lock_times

    def doctor_is_verified(self, **kwargs):
        verified = super().doctor_is_verified(**kwargs)
        self.lock_times.append(time.monotonic())
        return verified


def booking_service(session, national_id_hash, repository=None):
    return AppointmentService(
        repository=repository or AppointmentRepository(session),
        patient_repository=PatientRepository(session),
        identity_protector=FixedHashProtector(national_id_hash),
        branch_profile_service=PatientBranchProfileService(
            PatientBranchProfileRepository(session)
        ),
        idempotency_service=None,
    )


def book(service, seed, slot_id):
    return service.create_confirmed_booking(
        provider_id=seed.doctor.provider_id,
        provider_timezone=seed.provider_timezone,
        data=AppointmentCreateRequest(
            national_id=NATIONAL_ID, slot_id=slot_id, service_id=seed.service_id, channel="web",
        ),
    )


def assert_lock_interleaving(bookings, writers, writer_name):
    """The asserted interleaving behind the stress tests' HOLDLOCK claim:
    some writer was issued while a booking held the doctor, and every such
    writer got the row only after that booking's hold."""
    contended = waits_for(bookings, writers)
    assert contended, (
        f"no {writer_name} was issued while a booking held the doctor: this run shows "
        "no contention and proves nothing about HOLDLOCK"
    )
    for booking, writer in contended:
        assert writer.start >= booking.end, f"a {writer_name} got the doctor row during a booking's hold"


# ============================================================ repository level
# doctor_is_verified (WITH HOLDLOCK, ROWLOCK) against the conditional status
# UPDATE. No rows are inserted and enforcement is not needed.


def test_repo_rejection_update_is_not_blocked_without_a_booking(doctor):
    """Control for the next test."""
    with guarded_session() as reviewer:
        update = timed(lambda: update_status(reviewer, doctor, "verified", "rejected"))

    assert update.errors == frozenset()
    assert update.value is True
    assert update.waited < 1.0
    assert committed_status(doctor) == "verified"


def test_repo_booking_status_read_blocks_a_rejection_until_the_booking_ends(doctor):
    """Proves HOLDLOCK: without it the read's shared lock is released at
    once and the rejection's UPDATE would not time out."""
    with guarded_session() as booking:
        assert read_verified(booking, doctor) is True  # shared lock now held

        def reject():
            with guarded_session() as reviewer:
                return timed(lambda: update_status(reviewer, doctor, "verified", "rejected"))

        thread, outcome = run_in_thread(reject, "rejection")
        join(thread)
    # The booking transaction has ended (rolled back): its lock is released.

    blocked = result_of(outcome)
    assert LOCK_TIMEOUT_ERROR in blocked.errors
    assert blocked.waited >= LOCK_TIMEOUT_MS / 1000 * 0.9

    with guarded_session() as reviewer:
        after = timed(lambda: update_status(reviewer, doctor, "verified", "rejected"))
    assert after.errors == frozenset()
    assert after.value is True
    assert after.waited < 1.0
    assert committed_status(doctor) == "verified"


def test_repo_booking_status_read_times_out_on_an_uncommitted_rejection(doctor):
    """The check cannot read the old committed 'verified' past an uncommitted
    rejection. Proves the hint only under READ_COMMITTED_SNAPSHOT: with RCSI
    off a plain read waits too, so this passes with or without HOLDLOCK."""
    with guarded_session() as reviewer:
        assert update_status(reviewer, doctor, "verified", "rejected") is True  # uncommitted

        def check():
            with guarded_session() as booking:
                return timed(lambda: read_verified(booking, doctor))

        thread, outcome = run_in_thread(check, "status-read")
        join(thread)

    read = result_of(outcome)
    assert LOCK_TIMEOUT_ERROR in read.errors
    assert read.waited >= LOCK_TIMEOUT_MS / 1000 * 0.9
    assert committed_status(doctor) == "verified"


def test_repo_booking_status_read_waits_for_the_rejection_then_reads_committed_state(doctor):
    """The rejection is rolled back, never committed: the waiting read then
    returns the committed 'verified'. A read after a real commit of the
    rejection is NOT covered (see the module docstring). Like the previous
    test, proves the hint only under READ_COMMITTED_SNAPSHOT."""
    hold_s = 1.5
    about_to_read = threading.Event()

    with guarded_session() as reviewer:
        assert update_status(reviewer, doctor, "verified", "rejected") is True  # uncommitted

        def check():
            with guarded_session(LONG_LOCK_TIMEOUT_MS) as booking:
                about_to_read.set()
                return timed(lambda: read_verified(booking, doctor))

        thread, outcome = run_in_thread(check, "status-read")
        assert about_to_read.wait(JOIN_TIMEOUT_S), "the reading session did not connect"
        time.sleep(hold_s)
        assert thread.is_alive(), "the status read did not wait for the uncommitted rejection"
    # The rejection ends here (rolled back).

    join(thread)
    read = result_of(outcome)
    assert read.errors == frozenset()
    assert read.value is True
    assert read.waited >= hold_s * 0.9
    assert committed_status(doctor) == "verified"


def test_repo_two_booking_status_reads_of_one_doctor_do_not_block(doctor):
    """Compatibility only: fails with UPDLOCK, passes with or without
    HOLDLOCK."""
    with guarded_session() as first:
        assert read_verified(first, doctor) is True  # shared lock held

        def second():
            with guarded_session() as other:
                return timed(lambda: read_verified(other, doctor))

        thread, outcome = run_in_thread(second, "second-read")
        join(thread)

    read = result_of(outcome)
    assert read.errors == frozenset()
    assert read.value is True
    assert read.waited < 0.5


def test_repo_mixed_reads_and_status_updates_neither_deadlock_nor_overlap(doctor):
    """Booking reads, rejections and resubmission-shaped updates of one
    doctor, all rolled back. Asserts: no deadlock or lock timeout; at least
    one rejection was issued during a booking's hold and waited for it (this
    is what proves HOLDLOCK); booking holds overlapped each other (shared
    locks, no UPDLOCK); and no booking hold overlaps a rejection hold."""
    iterations = 15
    stop = threading.Event()
    guard = threading.Lock()
    bookings, rejections = [], []
    problems = []
    sql_errors = set()

    def problem(message, exc=None):
        with guard:
            problems.append(message)
            if exc is not None:
                sql_errors.update(sql_error_numbers(exc))

    def booking_worker(seed):
        pause = random.Random(seed)
        for _ in range(iterations):
            if stop.is_set():
                return
            try:
                with guarded_session(LONG_LOCK_TIMEOUT_MS) as db:
                    if read_verified(db, doctor) is not True:
                        problem("a booking read did not see the committed 'verified'")
                    start = time.monotonic()
                    time.sleep(pause.uniform(0.05, 0.15))  # hold the shared lock
                    end = time.monotonic()  # before release
                with guard:
                    bookings.append(SimpleNamespace(start=start, end=end))
            except SQLAlchemyError as exc:
                problem(f"booking read: {describe(exc)}", exc)

    def rejection_worker(seed):
        pause = random.Random(seed)
        for _ in range(iterations):
            if stop.is_set():
                return
            try:
                with guarded_session(LONG_LOCK_TIMEOUT_MS) as db:
                    issued = time.monotonic()
                    if update_status(db, doctor, "verified", "rejected") is not True:
                        problem("a rejection did not find the committed 'verified'")
                    start = time.monotonic()
                    time.sleep(pause.uniform(0, 0.03))
                    end = time.monotonic()  # before release
                with guard:
                    rejections.append(SimpleNamespace(issued=issued, start=start, end=end))
            except SQLAlchemyError as exc:
                problem(f"rejection: {describe(exc)}", exc)

    def resubmission_worker():
        # rejected -> pending never matches (no rejection is committed) but
        # still takes its locks while scanning the row.
        for _ in range(iterations):
            if stop.is_set():
                return
            try:
                with guarded_session(LONG_LOCK_TIMEOUT_MS) as db:
                    if update_status(db, doctor, "rejected", "pending") is not False:
                        problem("a resubmission matched an uncommitted rejection")
            except SQLAlchemyError as exc:
                problem(f"resubmission: {describe(exc)}", exc)

    workers = (
        [(f"booking-{s}", lambda s=s: booking_worker(s)) for s in range(4)]
        + [(f"rejection-{s}", lambda s=s: rejection_worker(100 + s)) for s in range(2)]
        + [("resubmission", resubmission_worker)]
    )
    for outcome in run_workers(workers, stop):
        result_of(outcome)

    assert DEADLOCK_ERROR not in sql_errors
    assert LOCK_TIMEOUT_ERROR not in sql_errors
    assert problems == []
    assert len(bookings) == 4 * iterations
    assert len(rejections) == 2 * iterations
    assert overlapping(bookings, rejections) == []
    assert_lock_interleaving(bookings, rejections, "rejection")
    assert overlapping(bookings, bookings), "booking holds never overlapped: no shared-lock concurrency shown"
    assert committed_status(doctor) == "verified"


# ============================================================ service flow
# AppointmentService / AdminCatalogService on committed seed rows, with
# DOCTOR_VERIFICATION_ENFORCED=true in this test process only.


def test_service_booking_of_a_rejected_doctor_is_409_without_writes(enforcement_in_process):
    """One session: the rejection is visible to it uncommitted. The service
    refuses before any write. The only change made, the doctor's status, is
    in the outer transaction and is rolled back; checked afterwards from a
    fresh connection."""
    with guarded_session() as db:
        # With join_transaction_mode="create_savepoint" the Session opens its
        # SAVEPOINT at its first statement, and the service's rollback()
        # after the 409 rolls back to that SAVEPOINT, undoing everything run
        # on this connection since. So the seed is read and the rejection
        # made on the connection BEFORE the Session's first statement: the
        # rejection then sits in the outer transaction only, rolled back on
        # exit.
        seed = refusal_seed(db.connection)
        changed = db.connection.execute(
            text(
                "UPDATE dbo.doctors SET verification_status = 'rejected' "
                "WHERE id = :id AND provider_id = :provider_id AND verification_status = 'verified'"
            ),
            {"id": str(seed.doctor.id), "provider_id": str(seed.doctor.provider_id)},
        ).rowcount
        assert changed == 1
        profiles = text(
            "SELECT COUNT(*) FROM dbo.patient_branch_profiles "
            "WHERE patient_id = :patient_id AND branch_id = :branch_id"
        )
        profile_params = {"patient_id": str(seed.patient_id), "branch_id": str(seed.branch_id)}
        before = slot_state(db.session, seed.slot_id)
        profiles_before = db.session.execute(profiles, profile_params).scalar_one()

        with pytest.raises(HTTPException) as error:
            book(booking_service(db.session, seed.patient_hash), seed, seed.slot_id)

        assert error.value.status_code == 409
        assert error.value.detail["code"] == "DOCTOR_NOT_BOOKABLE"
        assert slot_state(db.session, seed.slot_id) == before == ("available", 0)
        assert db.session.execute(profiles, profile_params).scalar_one() == profiles_before
        assert db.session.execute(
            text("SELECT verification_status FROM dbo.doctors WHERE id = :id"),
            {"id": str(seed.doctor.id)},
        ).scalar_one() == "rejected"

    # Rolled back: seen from a new connection.
    assert committed_status(seed.doctor) == "verified"
    with guarded_session() as check:
        assert slot_state(check.session, seed.slot_id) == ("available", 0)


@pytest.mark.parametrize("enforced", [True, False], ids=["enforced", "control-not-enforced"])
def test_service_bookings_of_one_doctor_on_two_slots_do_not_block(request, enforced):
    """Compatibility only: two open bookings of the same doctor, different
    slots and patients. The not-enforced run (no doctor lock taken) is the
    control: if both runs wait, the wait is not caused by the doctor lock."""
    if enforced:
        request.getfixturevalue("enforcement_in_process")
    seed = booking_seed(patients_needed=2)
    first_slot, second_slot = seed.slot_ids[:2]

    with guarded_session() as first:
        book(booking_service(first.session, seed.patient_hashes[0]), seed, first_slot)  # open

        def second():
            with guarded_session(LONG_LOCK_TIMEOUT_MS) as other:
                service = booking_service(other.session, seed.patient_hashes[1])
                return timed(lambda: book(service, seed, second_slot))

        thread, outcome = run_in_thread(second, "second-booking")
        join(thread)

    booked = result_of(outcome)
    assert LOCK_TIMEOUT_ERROR not in booked.errors
    assert DEADLOCK_ERROR not in booked.errors
    assert booked.errors == frozenset(), f"SQL Server errors {sorted(booked.errors)}"
    assert booked.value.status == "confirmed"
    assert booked.waited < 2.0

    with guarded_session() as check:
        assert slot_state(check.session, first_slot) == ("available", 0)
        assert slot_state(check.session, second_slot) == ("available", 0)


def test_service_bookings_and_a_verification_cycle_neither_deadlock_nor_overlap(enforcement_in_process):
    """Real booking and verification services, all rolled back: rejection,
    resubmission and approval (with their decision and audit rows) against
    concurrent bookings of the same doctor. Asserts: no deadlock or lock
    timeout; every booking sees the committed 'verified'; at least one
    rejection was issued during a booking's hold and waited for it (proves
    HOLDLOCK on the service path); booking holds overlapped each other; and
    no booking hold overlaps a verification hold."""
    seed = booking_seed(patients_needed=2)
    reviewer = reviewer_for(seed.doctor.provider_id)
    bookers = min(len(seed.slot_ids), len(seed.patient_hashes), 3)
    iterations = 8
    stop = threading.Event()
    guard = threading.Lock()
    bookings, verifications = [], []
    problems = []
    sql_errors = set()

    def problem(message, exc=None):
        with guard:
            problems.append(message)
            if exc is not None:
                sql_errors.update(sql_error_numbers(exc))

    def booking_worker(index):
        pause = random.Random(index)
        for _ in range(iterations):
            if stop.is_set():
                return
            lock_times = []
            try:
                with guarded_session(LONG_LOCK_TIMEOUT_MS) as db:
                    repository = RecordingAppointmentRepository(db.session, lock_times)
                    service = booking_service(db.session, seed.patient_hashes[index], repository)
                    book(service, seed, seed.slot_ids[index])
                    time.sleep(pause.uniform(0.05, 0.15))  # keep the booking open
                    end = time.monotonic()  # before release
                with guard:
                    bookings.append(SimpleNamespace(start=lock_times[-1], end=end))
            except HTTPException as exc:
                problem(f"booking refused: {exc.detail}")
            except SQLAlchemyError as exc:
                problem(f"booking: {describe(exc)}", exc)

    def verification_worker():
        pause = random.Random(7)
        for _ in range(iterations):
            if stop.is_set():
                return
            try:
                with guarded_session(LONG_LOCK_TIMEOUT_MS) as db:
                    service = AdminCatalogService(AdminCatalogRepository(db.session), idempotency_service=None)
                    audit = StaffAuditService(StaffAuditRepository(db.session))

                    def hook(action):
                        return audit.write_hook(staff=reviewer, action=action, resource_type="doctor")

                    common = {"provider_id": seed.doctor.provider_id, "doctor_id": seed.doctor.id,
                              "reviewer": reviewer}
                    issued = time.monotonic()
                    rejected = service.decide_doctor_verification(
                        decision="rejected", reason=REASON, audit=hook("doctor.reject"), **common,
                    )
                    start = time.monotonic()
                    if rejected.verification_status != "rejected":
                        problem("the rejection did not apply")
                    time.sleep(pause.uniform(0, 0.03))
                    service.resubmit_doctor_verification(audit=hook("doctor.resubmit"), **common)
                    approved = service.decide_doctor_verification(
                        decision="verified", reason=None, audit=hook("doctor.verify"), **common,
                    )
                    if approved.verification_status != "verified":
                        problem("the re-approval did not apply")
                    end = time.monotonic()  # before release
                with guard:
                    verifications.append(SimpleNamespace(issued=issued, start=start, end=end))
            except HTTPException as exc:
                problem(f"verification refused: {exc.detail}")
            except SQLAlchemyError as exc:
                problem(f"verification: {describe(exc)}", exc)

    workers = [(f"booking-{i}", lambda i=i: booking_worker(i)) for i in range(bookers)]
    workers.append(("verification", verification_worker))
    for outcome in run_workers(workers, stop):
        result_of(outcome)

    assert DEADLOCK_ERROR not in sql_errors
    assert LOCK_TIMEOUT_ERROR not in sql_errors
    assert problems == []
    assert len(bookings) == bookers * iterations
    assert len(verifications) == iterations
    assert overlapping(bookings, verifications) == []
    assert_lock_interleaving(bookings, verifications, "rejection")
    assert overlapping(bookings, bookings), "booking holds never overlapped: no shared-lock concurrency shown"
    assert committed_status(seed.doctor) == "verified"
    with guarded_session() as check:
        for slot_id in seed.slot_ids[:bookers]:
            assert slot_state(check.session, slot_id) == ("available", 0)
