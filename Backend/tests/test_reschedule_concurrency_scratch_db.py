"""
Cross-session rescheduling concurrency (C1-C4) on a SCRATCH database only.

Opt-in only, with an explicit target (tests/concurrency_target.py; no
default, a missing or mismatched target fails):
  restored   MEDMIND_DB_INTEGRATION=1, MEDMIND_CONCURRENCY_TARGET=restored,
             MEDMIND_SCRATCH_CONCURRENCY=1, MEDMIND_SCRATCH_DB_NAME /
             MEDMIND_SCRATCH_TOKEN; every connection goes through
             tests.scratch_db_guard (scratch marker and token)
  synthetic  MEDMIND_DB_INTEGRATION=1, MEDMIND_CONCURRENCY_TARGET=synthetic,
             MEDMIND_SYNTHETIC_CONCURRENCY=1, MEDMIND_SYNTHETIC_DB_NAME /
             MEDMIND_SYNTHETIC_TOKEN; every connection goes through
             tests.synthetic_db_guard (server, files, level and collation,
             synthetic marker and token, exact schema and fixture counts)
plus the matching DB_SERVER / DB_NAME / DB_TRUSTED_CONNECTION. Both guards
refuse MedMind_Booking_DB, MedMind_Audit_Final2, MedMind_Audit_Final and
every MedMind_Audit* / MedMind_Booking* name. These tests never use the
Final2 guards and can never run on Final2.

They COMMIT fixture rows (test doctors, links, slots, two appointments booked
through the real service) and, in the "commit" cases, real reschedules and
rejections. That is acceptable only because the whole scratch copy is
dropped afterwards (G7, or S6 for the synthetic database); nothing is
retained anywhere real.

Every case uses independent connections. One actor is held open with
scratch_open_transaction (its service commit() only releases a SAVEPOINT, so
its locks stay held until the test commits or rolls it back); the other runs
in a worker thread on its own connection with an explicit LOCK_TIMEOUT.
Threading events order the steps. Nothing here is a same-transaction or
sequential stand-in for cross-session behavior.
"""

import os
import random
import threading
import time
from datetime import date, time as clock, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings, staging_selected
from app.repositories.admin_catalog_repository import AdminCatalogRepository
from app.repositories.staff_audit_repository import StaffAuditRepository
from app.schemas.appointment import AppointmentCreateRequest, AppointmentRescheduleRequest
from app.security.staff_context import StaffContext
from app.services.admin_catalog_service import AdminCatalogService
from app.services.staff_audit_service import StaffAuditService
from tests import concurrency_target

# The guard is chosen explicitly (tests/concurrency_target.py): no default.
# Both guards are imported under the same three names; each keeps all of its
# own checks on every connection.
CONCURRENCY = concurrency_target.select(os.environ)
if CONCURRENCY.failure:
    pytest.fail(f"SAFETY STOP: {CONCURRENCY.failure}.", pytrace=False)
if CONCURRENCY.target == "synthetic":
    from tests.synthetic_db_guard import (
        synthetic_committing_session as scratch_committing_session,
        synthetic_connection as scratch_connection,
        synthetic_open_transaction as scratch_open_transaction,
    )
else:  # "restored", or skipped below
    from tests.scratch_db_guard import (
        scratch_committing_session,
        scratch_connection,
        scratch_open_transaction,
    )
from tests.test_doctor_verification_committed_db import enforcement_in_process
from tests.test_doctor_verification_concurrency_db import (
    DEADLOCK_ERROR,
    LOCK_TIMEOUT_ERROR,
    STOP_GRACE_S,
    RecordingAppointmentRepository,
    _WORKER_THREADS,
    _wait_for,
    booking_service,
    join,
    overlapping,
    result_of,
    run_in_thread,
    run_workers,
    sql_error_numbers,
    waits_for,
)
from tests.test_lab_booking_without_doctor_db import NATIONAL_ID


pytestmark = pytest.mark.skipif(CONCURRENCY.skip is not None, reason=CONCURRENCY.skip or "")

SHORT_TIMEOUT_MS = 2000
WAIT_TIMEOUT_MS = 15000
STRESS_TIMEOUT_MS = 10000
MARKER_PREFIX = "ZZTEST-CC-"


@pytest.fixture(autouse=True)
def scratch_run_safety():
    if not staging_selected():
        pytest.fail("SAFETY STOP: APP_ENV=staging is required.")
    get_settings.cache_clear()
    if get_settings().doctor_verification_enforced:
        pytest.fail("SAFETY STOP: DOCTOR_VERIFICATION_ENFORCED must be false outside test overrides.")
    leftover = _wait_for([t for t in _WORKER_THREADS if t.is_alive()], STOP_GRACE_S)
    if leftover:
        pytest.fail(f"SAFETY STOP: worker threads still running ({', '.join(t.name for t in leftover)}).")
    yield
    get_settings.cache_clear()
    still = _wait_for([t for t in _WORKER_THREADS if t.is_alive()], STOP_GRACE_S)
    _WORKER_THREADS[:] = still
    if still:
        pytest.fail(f"Worker threads still running after the test: {', '.join(t.name for t in still)}.")


# ============================================================ committed fixtures (scratch only)

SEED_SQL = """
SELECT TOP 1
    provider.id AS provider_id, provider.timezone, branch.id AS branch_id,
    (SELECT TOP 1 s.id FROM dbo.specialties AS s
     WHERE s.provider_id = provider.id AND s.is_active = 1 ORDER BY s.id) AS specialty_id,
    (SELECT TOP 1 sv.id FROM dbo.services AS sv
     WHERE sv.provider_id = provider.id AND sv.is_active = 1 ORDER BY sv.id) AS service_id,
    (SELECT TOP 1 p.national_id_hash
     FROM dbo.patients AS p
     JOIN dbo.patient_provider_profiles AS pp
         ON pp.patient_id = p.id AND pp.provider_id = provider.id AND pp.is_active = 1
     JOIN dbo.patient_branch_profiles AS bp
         ON bp.patient_id = p.id AND bp.provider_id = provider.id AND bp.branch_id = branch.id AND bp.is_active = 1
     WHERE p.is_active = 1 AND p.national_id_hash IS NOT NULL ORDER BY p.id) AS patient_hash,
    membership.id AS membership_id, membership.user_id
FROM dbo.providers AS provider
JOIN dbo.branches AS branch
    ON branch.provider_id = provider.id AND branch.is_active = 1 AND branch.mrn_code IS NOT NULL
JOIN dbo.provider_memberships AS membership
    ON membership.provider_id = provider.id AND membership.role = 'provider_admin' AND membership.is_active = 1
WHERE provider.is_active = 1 AND provider.org_type <> 'diagnostic_lab'
ORDER BY provider.tenant_key, branch.id, membership.id
"""

SLOT_NAMES = ("old1", "old2", "n", "x1", "x2", "m")  # m belongs to doctor 2


def _create_world():
    """Commit one isolated world in the scratch copy; returns its ids."""
    run = uuid4().hex[:10]
    with scratch_connection(WAIT_TIMEOUT_MS) as connection:
        row = connection.execute(text(SEED_SQL)).mappings().first()
        connection.rollback()
    if row is None or None in (row["specialty_id"], row["service_id"], row["patient_hash"]):
        pytest.skip("Scratch copy has no suitable provider/branch/service/patient/admin.")
    seed = SimpleNamespace(timezone=row["timezone"], patient_hash=row["patient_hash"])
    for key in ("provider_id", "branch_id", "specialty_id", "service_id", "membership_id", "user_id"):
        setattr(seed, key, UUID(str(row[key])))
    ids = SimpleNamespace(doctor1=uuid4(), doctor2=uuid4(), slots={name: uuid4() for name in SLOT_NAMES},
                          slot_date=date.today() + timedelta(days=45))

    with scratch_committing_session(WAIT_TIMEOUT_MS) as db:
        connection = db.connection
        for index, doctor in ((1, ids.doctor1), (2, ids.doctor2)):
            connection.execute(
                text(
                    "INSERT INTO dbo.doctors (id, provider_id, specialty_id, full_name_ar, full_name_en, "
                    "license_number, verification_status, is_active) "
                    "VALUES (:id, :p, :s, :name, :name, :license, 'verified', 1)"
                ),
                {"id": str(doctor), "p": str(seed.provider_id), "s": str(seed.specialty_id),
                 "name": f"ZZ TEST concurrency {run} d{index}", "license": f"{MARKER_PREFIX}{run}-{index}"},
            )
            connection.execute(
                text("INSERT INTO dbo.doctor_branches (id, provider_id, doctor_id, branch_id, is_primary, is_active) "
                     "VALUES (:id, :p, :d, :b, 1, 1)"),
                {"id": str(uuid4()), "p": str(seed.provider_id), "d": str(doctor), "b": str(seed.branch_id)},
            )
            connection.execute(
                text("INSERT INTO dbo.doctor_services (id, provider_id, doctor_id, service_id, is_active) "
                     "VALUES (:id, :p, :d, :s, 1)"),
                {"id": str(uuid4()), "p": str(seed.provider_id), "d": str(doctor), "s": str(seed.service_id)},
            )
        for position, name in enumerate(SLOT_NAMES):
            start = clock(6 + position // 4, (position % 4) * 15)
            end = clock(start.hour + (start.minute + 15) // 60, (start.minute + 15) % 60)
            connection.execute(
                text("INSERT INTO dbo.doctor_availability_slots "
                     "(id, provider_id, doctor_id, branch_id, slot_date, start_time, end_time, status) "
                     "VALUES (:id, :p, :d, :b, :day, :start, :end, 'available')"),
                {"id": str(ids.slots[name]), "p": str(seed.provider_id),
                 "d": str(ids.doctor2 if name == "m" else ids.doctor1), "b": str(seed.branch_id),
                 "day": ids.slot_date, "start": start, "end": end},
            )
        connection.commit()

        booker = booking_service(db.session, seed.patient_hash)
        ids.first, ids.second = (
            booker.create_confirmed_booking(
                provider_id=seed.provider_id, provider_timezone=seed.timezone,
                data=AppointmentCreateRequest(national_id=NATIONAL_ID, slot_id=ids.slots[slot],
                                              service_id=seed.service_id, channel="web"),
            ).appointment_reference
            for slot in ("old1", "old2")
        )
    return SimpleNamespace(seed=seed, ids=ids, run=run)


@pytest.fixture
def world():
    return _create_world()


# ============================================================ actions and reads


def reschedule(session, world, reference, slot_name, repository=None):
    return booking_service(session, world.seed.patient_hash, repository).reschedule_booking(
        provider_id=world.seed.provider_id, provider_timezone=world.seed.timezone,
        appointment_reference=reference,
        data=AppointmentRescheduleRequest(national_id=NATIONAL_ID, new_slot_id=world.ids.slots[slot_name],
                                          reason="scratch concurrency test"),
    )


def reviewer(world):
    return StaffContext(user_id=world.seed.user_id, membership_id=world.seed.membership_id,
                        provider_id=world.seed.provider_id, role="provider_admin", doctor_id=None)


def decide(session, world, doctor, decision):
    service = AdminCatalogService(AdminCatalogRepository(session), idempotency_service=None)
    audit = StaffAuditService(StaffAuditRepository(session))
    staff = reviewer(world)
    common = {"provider_id": world.seed.provider_id, "doctor_id": doctor, "reviewer": staff}
    if decision == "resubmitted":
        return service.resubmit_doctor_verification(
            audit=audit.write_hook(staff=staff, action="doctor.resubmit", resource_type="doctor"), **common)
    return service.decide_doctor_verification(
        decision=decision, reason="Scratch concurrency test." if decision == "rejected" else None,
        audit=audit.write_hook(staff=staff, action=f"doctor.{'reject' if decision == 'rejected' else 'verify'}",
                               resource_type="doctor"), **common)


def attempt(call):
    """Run one call; record its outcome kind, HTTP code or SQL Server error numbers, and time."""
    started = time.monotonic()
    try:
        value, outcome = call(), ("ok",)
    except HTTPException as exc:
        value, outcome = exc, ("http", exc.status_code, (exc.detail or {}).get("code"))
    except SQLAlchemyError as exc:
        value, outcome = exc, ("sql", sql_error_numbers(exc))
    return SimpleNamespace(value=value, outcome=outcome, waited=time.monotonic() - started)


def committed(world):
    """The committed state of this world, read on a fresh scratch connection."""
    with scratch_connection(SHORT_TIMEOUT_MS) as connection:
        appointments = {
            ref: connection.execute(
                text("SELECT a.slot_id, a.reschedule_count, "
                     "(SELECT COUNT(*) FROM dbo.appointment_status_history AS h WHERE h.appointment_id = a.id) "
                     "FROM dbo.appointments AS a WHERE a.appointment_reference = :ref AND a.provider_id = :p"),
                {"ref": ref, "p": str(world.seed.provider_id)},
            ).one()
            for ref in (world.ids.first, world.ids.second)
        }
        slots = {
            name: connection.execute(
                text("SELECT s.status, (SELECT COUNT(*) FROM dbo.appointments AS a "
                     "WHERE a.slot_id = s.id AND a.status <> 'cancelled') "
                     "FROM dbo.doctor_availability_slots AS s WHERE s.id = :id"),
                {"id": str(slot)},
            ).one()
            for name, slot in world.ids.slots.items()
        }
        doctor2 = connection.execute(
            text("SELECT verification_status, (SELECT COUNT(*) FROM dbo.doctor_verification_decisions "
                 "WHERE doctor_id = :id) FROM dbo.doctors WHERE id = :id"),
            {"id": str(world.ids.doctor2)},
        ).one()
        connection.rollback()
    by_id = {v: k for k, v in world.ids.slots.items()}
    return SimpleNamespace(
        slot_of={ref: by_id[UUID(str(row[0]))] for ref, row in appointments.items()},
        reschedules={ref: row[1] for ref, row in appointments.items()},
        history={ref: row[2] for ref, row in appointments.items()},
        slot_status={name: row[0] for name, row in slots.items()},
        active_on={name: row[1] for name, row in slots.items()},
        doctor2_status=doctor2[0], doctor2_decisions=doctor2[1],
    )


def _waiting_worker(name, timeout_ms, call_factory):
    """A worker on its own committing scratch session: signals just before its
    call, then records the outcome."""
    started = threading.Event()

    def work():
        with scratch_committing_session(timeout_ms) as db:
            started.set()
            return attempt(lambda: call_factory(db.session))

    thread, outcome = run_in_thread(work, name)
    assert started.wait(30), f"{name} did not connect"
    return thread, outcome


# ============================================================ C1: two reschedules, one slot


def test_c1a_second_reschedule_waits_on_the_held_slot_lock(world):
    before = committed(world)
    with scratch_open_transaction(WAIT_TIMEOUT_MS) as a:
        reschedule(a.session, world, world.ids.first, "n")  # A holds slot n (not committed)
        thread, outcome = _waiting_worker(
            "reschedule-b", SHORT_TIMEOUT_MS, lambda s: reschedule(s, world, world.ids.second, "n"))
        join(thread)
        a.rollback()

    b = result_of(outcome)
    assert b.outcome[0] == "sql" and LOCK_TIMEOUT_ERROR in b.outcome[1], b.outcome
    assert b.waited >= SHORT_TIMEOUT_MS / 1000 * 0.9
    after = committed(world)
    assert after.slot_of == before.slot_of and after.history == before.history
    assert after.slot_status["n"] == "available" and after.active_on["n"] == 0


@pytest.mark.parametrize("round_", range(5))
@pytest.mark.parametrize("winner", ["first", "second"])
def test_c1b_committed_winner_leaves_the_loser_409(world, winner, round_):
    win, lose = (world.ids.first, world.ids.second) if winner == "first" else (world.ids.second, world.ids.first)
    before = committed(world)
    with scratch_open_transaction(WAIT_TIMEOUT_MS) as a:
        reschedule(a.session, world, win, "n")
        thread, outcome = _waiting_worker(
            "reschedule-loser", WAIT_TIMEOUT_MS, lambda s: reschedule(s, world, lose, "n"))
        time.sleep(1.0)
        assert thread.is_alive(), "the loser did not wait for the held slot lock"
        a.commit()
    join(thread)

    loser = result_of(outcome)
    assert loser.outcome == ("http", 409, "NEW_SLOT_UNAVAILABLE"), loser.outcome
    assert loser.waited >= 0.9
    after = committed(world)
    assert after.slot_of[win] == "n" and after.slot_of[lose] == before.slot_of[lose]
    assert after.active_on["n"] == 1 and after.slot_status["n"] == "booked"
    assert after.history[win] == before.history[win] + 1 and after.history[lose] == before.history[lose]
    assert after.reschedules[lose] == before.reschedules[lose]


# ============================================================ C2: reschedule vs doctor rejection


def test_c2a_committed_rejection_then_reschedule_is_409(world):
    with scratch_committing_session(WAIT_TIMEOUT_MS) as db:
        decide(db.session, world, world.ids.doctor2, "rejected")  # really committed
    before = committed(world)
    assert before.doctor2_status == "rejected"

    with enforcement_in_process(), scratch_committing_session(WAIT_TIMEOUT_MS) as db:
        result = attempt(lambda: reschedule(db.session, world, world.ids.first, "m"))

    assert result.outcome == ("http", 409, "DOCTOR_NOT_BOOKABLE"), result.outcome
    after = committed(world)
    assert after.slot_of == before.slot_of and after.history == before.history
    assert after.slot_status["m"] == "available"


def test_c2b_open_reschedule_blocks_the_rejection_until_it_commits(world):
    with enforcement_in_process():
        with scratch_open_transaction(WAIT_TIMEOUT_MS) as a:
            reschedule(a.session, world, world.ids.first, "m")  # holds doctor 2's shared lock
            thread, outcome = _waiting_worker(
                "rejection", SHORT_TIMEOUT_MS, lambda s: decide(s, world, world.ids.doctor2, "rejected"))
            join(thread)
            a.commit()
        blocked = result_of(outcome)
        assert blocked.outcome[0] == "sql" and LOCK_TIMEOUT_ERROR in blocked.outcome[1], blocked.outcome

        with scratch_committing_session(WAIT_TIMEOUT_MS) as db:
            retry = attempt(lambda: decide(db.session, world, world.ids.doctor2, "rejected"))
    assert retry.outcome == ("ok",), retry.outcome
    after = committed(world)
    # The reschedule committed first and is kept; the rejection came after it.
    assert after.slot_of[world.ids.first] == "m"
    assert after.doctor2_status == "rejected" and after.doctor2_decisions == 1


@pytest.mark.parametrize("rejection_ends", ["commit", "rollback"])
def test_c2c_reschedule_waits_for_an_open_rejection(world, rejection_ends):
    """With RCSI off a plain read would wait too: this shows the outcome after
    a committed rejection, not the HOLDLOCK hint itself (C2b does)."""
    before = committed(world)
    with enforcement_in_process():
        with scratch_open_transaction(WAIT_TIMEOUT_MS) as b:
            decide(b.session, world, world.ids.doctor2, "rejected")  # holds doctor 2 exclusively
            thread, outcome = _waiting_worker(
                "reschedule", WAIT_TIMEOUT_MS, lambda s: reschedule(s, world, world.ids.first, "m"))
            time.sleep(1.0)
            assert thread.is_alive(), "the reschedule did not wait for the open rejection"
            (b.commit if rejection_ends == "commit" else b.rollback)()
        join(thread)

    result = result_of(outcome)
    after = committed(world)
    if rejection_ends == "commit":
        assert result.outcome == ("http", 409, "DOCTOR_NOT_BOOKABLE"), result.outcome
        assert after.slot_of == before.slot_of and after.doctor2_status == "rejected"
    else:
        assert result.outcome == ("ok",), result.outcome
        assert after.slot_of[world.ids.first] == "m" and after.doctor2_status == "verified"


# ============================================================ C4: two reschedules of the SAME appointment
#
# Expected behavior, established by static review (not yet observed):
# reschedule_booking first locks the appointment row
# (AppointmentRepository.lock_appointment_by_reference: UPDLOCK, HOLDLOCK,
# ROWLOCK), before any slot lock. A second session therefore blocks on its
# first lock request and holds nothing (no deadlock possible). Once the
# first session ends it reads the COMMITTED row (READ_COMMITTED_SNAPSHOT is
# off): after a commit its old slot is the first session's new slot, so the
# guarded update (slot_id = :old_slot_id) matches and it proceeds; a request
# for that same slot is refused with 422 SAME_SLOT before any slot is
# locked. There is no reschedule limit. After a rollback it moves the
# appointment from its original slot.


def test_c4a_a_second_reschedule_of_the_same_appointment_waits(world):
    reference = world.ids.first
    before = committed(world)
    with scratch_open_transaction(WAIT_TIMEOUT_MS) as a:
        reschedule(a.session, world, reference, "x1")  # A holds the appointment (not committed)
        thread, outcome = _waiting_worker(
            "reschedule-same-b", SHORT_TIMEOUT_MS, lambda s: reschedule(s, world, reference, "x2"))
        join(thread)
        a.rollback()

    b = result_of(outcome)
    assert b.outcome[0] == "sql" and LOCK_TIMEOUT_ERROR in b.outcome[1], b.outcome
    assert b.waited >= SHORT_TIMEOUT_MS / 1000 * 0.9
    after = committed(world)
    assert after.slot_of == before.slot_of and after.history == before.history
    assert after.reschedules == before.reschedules
    for name in ("x1", "x2"):
        assert after.slot_status[name] == "available" and after.active_on[name] == 0


@pytest.mark.parametrize("first_ends", ["commit", "rollback"])
@pytest.mark.parametrize("second_target", ["x2", "x1"])
def test_c4b_the_second_reschedule_runs_on_the_first_ones_outcome(world, first_ends, second_target):
    reference = world.ids.first
    before = committed(world)
    with scratch_open_transaction(WAIT_TIMEOUT_MS) as a:
        reschedule(a.session, world, reference, "x1")
        thread, outcome = _waiting_worker(
            "reschedule-same-b", WAIT_TIMEOUT_MS, lambda s: reschedule(s, world, reference, second_target))
        time.sleep(1.0)
        assert thread.is_alive(), "the second reschedule did not wait for the first"
        (a.commit if first_ends == "commit" else a.rollback)()
    join(thread)

    b = result_of(outcome)
    if first_ends == "commit" and second_target == "x1":
        assert b.outcome == ("http", 422, "SAME_SLOT"), b.outcome
        final, moves = "x1", 1
    else:
        assert b.outcome == ("ok",), b.outcome
        final, moves = second_target, 2 if first_ends == "commit" else 1
    assert b.waited >= 0.9
    after = committed(world)
    assert after.slot_of[reference] == final
    assert after.history[reference] == before.history[reference] + moves
    assert after.reschedules[reference] == before.reschedules[reference] + moves
    for name in ("old1", "x1", "x2"):  # exactly one of the appointment's slots is held, by it
        held = name == final
        assert after.slot_status[name] == ("booked" if held else "available"), (name, after.slot_status)
        assert after.active_on[name] == (1 if held else 0), (name, after.active_on)
    assert after.slot_of[world.ids.second] == before.slot_of[world.ids.second]


# ============================================================ C3: stress


class C3TimelineRepository(RecordingAppointmentRepository):
    """C3 diagnostics only: records when each lock-taking read before the
    recorded hold start is called and when it returns, so a wait can be
    placed (appointment lock, slot lock, doctor reads). Calls the real
    methods unchanged; doctor_is_verified still records the hold start
    through the parent class."""

    def __init__(self, session, lock_times, timeline, actor, iteration):
        super().__init__(session, lock_times)
        self.timeline, self.actor, self.iteration = timeline, actor, iteration

    def _timed(self, step, call, **kwargs):
        before = time.monotonic()
        try:
            return call(**kwargs)
        finally:
            self.timeline.append((self.actor, self.iteration, step, before, time.monotonic()))

    def lock_appointment_by_reference(self, **kwargs):
        return self._timed("lock_appointment_by_reference", super().lock_appointment_by_reference, **kwargs)

    def lock_slot(self, **kwargs):
        return self._timed("lock_slot", super().lock_slot, **kwargs)

    def doctor_branch_is_valid(self, **kwargs):
        return self._timed("doctor_branch_is_valid", super().doctor_branch_is_valid, **kwargs)

    def doctor_is_verified(self, **kwargs):
        return self._timed("doctor_is_verified", super().doctor_is_verified, **kwargs)


def _print_c3_timeline(timeline, holds):
    """Prints every recorded event and both hold lists, relative to the
    first event (seconds). Shown by pytest -rA for passing and failing runs."""
    events = sorted(timeline, key=lambda event: event[3])
    origin = events[0][3] if events else 0.0
    print(f"C3 TIMELINE ({len(events)} events; columns: begin end duration actor iteration step)")
    for actor, iteration, step, before, after in events:
        print(f"  {before - origin:9.4f} {after - origin:9.4f} {after - before:8.4f}  {actor:<14} it={iteration}  {step}")
    for kind in ("reschedule", "verification"):
        print(f"C3 {kind.upper()} HOLDS ({len(holds[kind])})")
        for hold in sorted(holds[kind], key=lambda h: h.start):
            issued = f" issued={hold.issued - origin:9.4f}" if hasattr(hold, "issued") else ""
            print(f"  start={hold.start - origin:9.4f} end={hold.end - origin:9.4f}{issued}")


def test_c3_reschedules_and_a_verification_cycle_neither_deadlock_nor_overlap(world):
    """Two reschedulers move their own appointments back and forth on doctor 1
    while a reject/resubmit/verify cycle runs on doctor 1, all on separate
    connections, every step committed. Asserts: no deadlock or lock timeout;
    a rejection was issued during a reschedule's doctor-lock hold and waited
    for it; reschedule holds overlapped each other; no reschedule hold
    overlaps a verification hold; every committed reschedule left exactly one
    history row; each appointment occupies exactly one of its slots.

    Diagnostics: a timeline of every worker's iteration start, transaction
    open, the lock-taking reads before the hold start, verifier decisions and
    commits is printed before the assertions. Recording adds only monotonic
    clock reads and list appends; nothing is synchronized differently."""
    iterations = 6
    stop = threading.Event()
    guard = threading.Lock()
    holds = {"reschedule": [], "verification": []}
    moves = {world.ids.first: 0, world.ids.second: 0}
    problems, sql_errors = [], set()
    timeline = []  # (actor, iteration, step, begin, end); list.append is atomic, no extra lock
    before = committed(world)

    def mark(actor, iteration, step):
        now = time.monotonic()
        timeline.append((actor, iteration, step, now, now))

    def problem(message, exc=None):
        with guard:
            problems.append(message)
            if exc is not None:
                sql_errors.update(sql_error_numbers(exc))

    def rescheduler(reference, slots):
        pause = random.Random(reference)
        actor = threading.current_thread().name
        for index in range(iterations):
            if stop.is_set():
                return
            target = slots[(index + 1) % 2]
            lock_times = []
            mark(actor, index, "iteration_begin")
            try:
                with scratch_open_transaction(STRESS_TIMEOUT_MS) as tx:
                    mark(actor, index, "transaction_open")
                    repository = C3TimelineRepository(tx.session, lock_times, timeline, actor, index)
                    reschedule(tx.session, world, reference, target, repository)
                    time.sleep(pause.uniform(0.05, 0.15))
                    end = time.monotonic()  # before release
                    tx.commit()
                    mark(actor, index, "committed")
                with guard:
                    holds["reschedule"].append(SimpleNamespace(start=lock_times[-1], end=end))
                    moves[reference] += 1
            except HTTPException as exc:
                problem(f"reschedule refused: {exc.detail}")
            except SQLAlchemyError as exc:
                problem(f"reschedule: {sql_error_numbers(exc)}", exc)

    def timed_decide(actor, iteration, session, decision):
        begin = time.monotonic()
        try:
            return decide(session, world, world.ids.doctor1, decision)
        finally:
            timeline.append((actor, iteration, f"decide_{decision}", begin, time.monotonic()))

    def verifier():
        actor = threading.current_thread().name
        for index in range(iterations):
            if stop.is_set():
                return
            mark(actor, index, "iteration_begin")
            try:
                with scratch_open_transaction(STRESS_TIMEOUT_MS) as tx:
                    mark(actor, index, "transaction_open")
                    issued = time.monotonic()
                    timed_decide(actor, index, tx.session, "rejected")
                    start = time.monotonic()
                    time.sleep(0.02)
                    timed_decide(actor, index, tx.session, "resubmitted")
                    timed_decide(actor, index, tx.session, "verified")
                    end = time.monotonic()  # before release
                    tx.commit()
                    mark(actor, index, "committed")
                with guard:
                    holds["verification"].append(SimpleNamespace(issued=issued, start=start, end=end))
            except HTTPException as exc:
                problem(f"verification refused: {exc.detail}")
            except SQLAlchemyError as exc:
                problem(f"verification: {sql_error_numbers(exc)}", exc)

    try:
        with enforcement_in_process():
            workers = [
                ("rescheduler-1", lambda: rescheduler(world.ids.first, ("old1", "x1"))),
                ("rescheduler-2", lambda: rescheduler(world.ids.second, ("old2", "x2"))),
                ("verifier", verifier),
            ]
            for outcome in run_workers(workers, stop):
                result_of(outcome)
    finally:
        _print_c3_timeline(timeline, holds)  # before any assertion, and also if a worker failed

    assert DEADLOCK_ERROR not in sql_errors and LOCK_TIMEOUT_ERROR not in sql_errors
    assert problems == []
    assert len(holds["reschedule"]) == 2 * iterations and len(holds["verification"]) == iterations
    assert overlapping(holds["reschedule"], holds["verification"]) == []
    contended = waits_for(holds["reschedule"], holds["verification"])
    assert contended, "no rejection was issued during a reschedule's hold: no contention shown"
    for hold, verification in contended:
        assert verification.start >= hold.end
    assert overlapping(holds["reschedule"], holds["reschedule"]), "reschedule holds never overlapped"

    after = committed(world)
    for reference, pair in ((world.ids.first, ("old1", "x1")), (world.ids.second, ("old2", "x2"))):
        assert after.history[reference] == before.history[reference] + moves[reference]
        assert after.slot_of[reference] in pair
        other = pair[1] if after.slot_of[reference] == pair[0] else pair[0]
        assert after.slot_status[after.slot_of[reference]] == "booked" and after.active_on[after.slot_of[reference]] == 1
        assert after.slot_status[other] == "available" and after.active_on[other] == 0
