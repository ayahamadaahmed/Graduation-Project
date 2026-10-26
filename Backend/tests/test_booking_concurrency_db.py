"""
Double-booking protection under concurrency - integration tests.

Opt-in only: MEDMIND_DB_INTEGRATION=1. Every connection refuses anything but
localhost\\SQLEXPRESS / MedMind_Audit_Final2 and runs inside one outer
transaction that is rolled back; the services' commit() calls only release a
SAVEPOINT, so nothing persists.

Two protections are checked:
1. lock_slot reads the slot WITH (UPDLOCK, HOLDLOCK, ROWLOCK): while one
   booking transaction is open, a second booker cannot even read the slot
   (it waits; here LOCK_TIMEOUT turns the wait into an error).
2. UX_appointments_active_slot: even if the slot row were wrongly marked
   available again, a second active appointment for the slot is rejected.
"""

import os
import threading
import time
from contextlib import contextmanager
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.repositories.appointment_repository import AppointmentRepository
from app.schemas.appointment import AppointmentCreateRequest
from tests.test_lab_booking_without_doctor_db import (  # noqa: F401  db_session is a fixture
    NATIONAL_ID,
    active_patient_hash,
    appointment_service,
    assign_missing_mrn_codes,
    create_lab_slots,
    db_session,
    diagnostic_service_id,
    future_date,
    own_lab_slots,
    provider,
    unsafe_engine_target,
)


pytestmark = pytest.mark.skipif(
    os.getenv("MEDMIND_DB_INTEGRATION") != "1",
    reason="Set MEDMIND_DB_INTEGRATION=1 to run against an audit database.",
)

LOCK_TIMEOUT_MS = 2000


@contextmanager
def guarded_session():
    """Same safety checks as the db_session fixture, for a second connection."""
    from app.core.config import get_settings
    from app.db.session import engine

    settings = get_settings()
    if (
        settings.db_server != r"localhost\SQLEXPRESS"
        or settings.db_name != "MedMind_Audit_Final2"
        or not settings.db_trusted_connection
    ):
        pytest.fail("SAFETY STOP: unexpected database configuration.")

    # The engine's own target, before connecting (see db_session).
    reason = unsafe_engine_target(engine)
    if reason is not None:
        pytest.fail(f"SAFETY STOP: the engine does not target the approved audit database ({reason}).")

    connection = engine.connect()
    try:
        if connection.execute(text("SELECT DB_NAME()")).scalar_one() != "MedMind_Audit_Final2":
            pytest.fail("SAFETY STOP: unexpected connected database.")
        connection.rollback()

        outer = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            outer.rollback()
    finally:
        connection.close()


def _book(service, lab, slot_id, service_id):
    return service.create_confirmed_booking(
        provider_id=lab.id,
        provider_timezone=lab.timezone,
        data=AppointmentCreateRequest(
            national_id=NATIONAL_ID,
            slot_id=slot_id,
            service_id=service_id,
            channel="web",
        ),
    )


def test_unique_index_rejects_second_active_booking_of_a_slot(db_session):
    lab = provider(db_session, "lab-001")
    assign_missing_mrn_codes(db_session, lab.id)
    target_date = future_date(lab.timezone)
    create_lab_slots(db_session, lab, target_date)
    slot = own_lab_slots(db_session, lab, target_date)[0]
    service_id = diagnostic_service_id(db_session, lab.id)
    service = appointment_service(db_session, active_patient_hash(db_session, lab.id))

    _book(service, lab, slot.id, service_id)

    # Simulate a writer that bypassed the slot lock and flipped the slot back.
    db_session.execute(
        text("UPDATE dbo.doctor_availability_slots SET status = 'available' WHERE id = :id"),
        {"id": str(slot.id)},
    )

    with pytest.raises(HTTPException) as exc_info:
        _book(service, lab, slot.id, service_id)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "BOOKING_CONFLICT"
    active = db_session.execute(
        text(
            "SELECT COUNT(*) FROM dbo.appointments "
            "WHERE slot_id = :id AND status <> 'cancelled'"
        ),
        {"id": str(slot.id)},
    ).scalar_one()
    assert active == 1


def test_second_booker_waits_for_the_open_booking_transaction(db_session):
    lab = provider(db_session, "lab-001")
    tomorrow = future_date(lab.timezone, days=1)

    # A slot that is already committed (visible to both connections).
    slot_id = db_session.execute(
        text(
            """
            SELECT TOP 1 slot.id
            FROM dbo.doctor_availability_slots AS slot
            JOIN dbo.branches AS branch
                ON branch.id = slot.branch_id AND branch.is_active = 1
            WHERE slot.provider_id = :provider_id
              AND slot.doctor_id IS NULL
              AND slot.status = 'available'
              AND slot.slot_date >= :tomorrow
            ORDER BY slot.slot_date, slot.start_time
            """
        ),
        {"provider_id": str(lab.id), "tomorrow": tomorrow},
    ).scalar()
    if slot_id is None:
        pytest.skip("No committed lab-001 slot in the future in this audit copy.")
    slot_id = UUID(str(slot_id))

    assign_missing_mrn_codes(db_session, lab.id)
    service = appointment_service(db_session, active_patient_hash(db_session, lab.id))

    # Booker A: booked, but its transaction is still open.
    _book(service, lab, slot_id, diagnostic_service_id(db_session, lab.id))

    outcome = {}

    def booker_b():
        with guarded_session() as session_b:
            session_b.execute(text(f"SET LOCK_TIMEOUT {LOCK_TIMEOUT_MS}"))
            started = time.monotonic()
            try:
                AppointmentRepository(session_b).lock_slot(
                    provider_id=lab.id, slot_id=slot_id
                )
                outcome["result"] = "acquired"
            except DBAPIError as exc:
                outcome["result"] = "timeout" if "1222" in str(exc.orig) else repr(exc.orig)[:200]
            outcome["waited"] = time.monotonic() - started

    thread = threading.Thread(target=booker_b)
    thread.start()
    thread.join(timeout=30)

    assert not thread.is_alive()
    # B could not read the slot while A's booking was open.
    assert outcome["result"] == "timeout"
    assert outcome["waited"] >= LOCK_TIMEOUT_MS / 1000 * 0.9

    # A sees its own booking; B would see 'booked' once A commits, and
    # mark_slot_booked only updates a slot that is still 'available'.
    status = db_session.execute(
        text("SELECT status FROM dbo.doctor_availability_slots WHERE id = :id"),
        {"id": str(slot_id)},
    ).scalar_one()
    assert status == "booked"


def test_slot_lock_is_released_when_the_booking_rolls_back(db_session):
    """Control: without an open booking, the second connection is not blocked."""
    lab = provider(db_session, "lab-001")
    slot_id = db_session.execute(
        text(
            "SELECT TOP 1 id FROM dbo.doctor_availability_slots "
            "WHERE provider_id = :p AND status = 'available' AND doctor_id IS NULL"
        ),
        {"p": str(lab.id)},
    ).scalar()
    if slot_id is None:
        pytest.skip("No committed lab-001 slot in this audit copy.")

    with guarded_session() as session_b:
        session_b.execute(text(f"SET LOCK_TIMEOUT {LOCK_TIMEOUT_MS}"))
        row = AppointmentRepository(session_b).lock_slot(
            provider_id=lab.id, slot_id=UUID(str(slot_id))
        )

    assert row is not None
    assert row["status"] == "available"
