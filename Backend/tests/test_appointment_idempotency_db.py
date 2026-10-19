"""
Booking idempotency - integration tests against a real database.

Opt-in only: MEDMIND_DB_INTEGRATION=1. The db_session fixture is reused
unchanged from test_lab_booking_without_doctor_db: it refuses anything but
localhost\\SQLEXPRESS / MedMind_Audit_Final2 before and after connecting,
and rolls back its outer transaction at the end, so the appointments AND
the idempotency receipts written here never persist.

Unlike the lab tests, the AppointmentService here uses the real
IdempotencyService (sp_getapplock + idempotency_requests).
"""

import json
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.schemas.appointment import AppointmentCreateRequest
from app.services.idempotency_service import idempotency_service
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
)


pytestmark = pytest.mark.skipif(
    os.getenv("MEDMIND_DB_INTEGRATION") != "1",
    reason="Set MEDMIND_DB_INTEGRATION=1 to run against an audit database.",
)

OPERATION = "create_booking"


# ============================================================
# HELPERS
# ============================================================


def new_key():
    # Unique per test run: never matches a receipt already in the audit copy.
    return f"pytest-idem-{uuid4().hex}"


def lab_setup(session):
    """lab-001 with this test's own 06:00-07:00 slots (rolled back)."""

    lab = provider(session, "lab-001")
    assign_missing_mrn_codes(session, lab.id)

    target_date = future_date(lab.timezone)
    create_lab_slots(session, lab, target_date)

    slots = own_lab_slots(session, lab, target_date)
    assert len(slots) >= 2

    service = appointment_service(session, active_patient_hash(session, lab.id))
    service.idempotency_service = idempotency_service

    return SimpleNamespace(
        lab=lab,
        slots=slots,
        service=service,
        service_id=diagnostic_service_id(session, lab.id),
    )


def booking_request(setup, slot, notes=None):
    return AppointmentCreateRequest(
        national_id=NATIONAL_ID,
        slot_id=slot.id,
        service_id=setup.service_id,
        channel="web",
        notes=notes,
    )


def book(setup, data, key):
    return setup.service.create_confirmed_booking(
        provider_id=setup.lab.id,
        provider_timezone=setup.lab.timezone,
        data=data,
        idempotency_key=key,
    )


def appointment_count(session, slot_id):
    return session.execute(
        text("SELECT COUNT(*) FROM dbo.appointments WHERE slot_id = :id"),
        {"id": str(slot_id)},
    ).scalar_one()


def slot_status(session, slot_id):
    return session.execute(
        text("SELECT status FROM dbo.doctor_availability_slots WHERE id = :id"),
        {"id": str(slot_id)},
    ).scalar_one()


def receipts(session, setup, key):
    # The service scopes receipts by the internal provider id, not tenant_key.
    return session.execute(
        text(
            "SELECT status, request_hash, response_body "
            "FROM dbo.idempotency_requests "
            "WHERE tenant_id = :tenant AND operation = :operation "
            "AND idempotency_key = :key"
        ),
        {"tenant": str(setup.lab.id), "operation": OPERATION, "key": key},
    ).mappings().all()


# ============================================================
# SAME KEY + SAME PAYLOAD -> CACHED RESPONSE
# ============================================================


def test_same_key_same_payload_replays_cached_response(db_session):
    setup = lab_setup(db_session)
    slot = setup.slots[0]
    key = new_key()

    first = book(setup, booking_request(setup, slot), key)
    assert first.status == "confirmed"

    # A fresh but identical request. Without idempotency this would be
    # rejected as SLOT_UNAVAILABLE, because the slot is now booked.
    second = book(setup, booking_request(setup, slot), key)

    assert second.model_dump(mode="json") == first.model_dump(mode="json")
    assert appointment_count(db_session, slot.id) == 1
    assert slot_status(db_session, slot.id) == "booked"

    rows = receipts(db_session, setup, key)
    assert len(rows) == 1
    assert rows[0]["status"] == "completed"
    cached = json.loads(rows[0]["response_body"])
    assert cached["appointment_reference"] == first.appointment_reference


# ============================================================
# SAME KEY + DIFFERENT PAYLOAD -> 409
# ============================================================


@pytest.mark.parametrize("change", ["other_slot", "other_notes"])
def test_same_key_different_payload_is_rejected(db_session, change):
    setup = lab_setup(db_session)
    first_slot, other_slot = setup.slots[0], setup.slots[1]
    key = new_key()

    first = book(setup, booking_request(setup, first_slot), key)
    receipt_before = receipts(db_session, setup, key)
    assert len(receipt_before) == 1

    if change == "other_slot":
        changed = booking_request(setup, other_slot)
    else:
        changed = booking_request(setup, first_slot, notes="different data")

    with pytest.raises(HTTPException) as exc_info:
        book(setup, changed, key)

    assert exc_info.value.status_code == 409
    # Not SLOT_UNAVAILABLE: the key conflict is detected first.
    assert exc_info.value.detail["code"] == "IDEMPOTENCY_CONFLICT"

    assert appointment_count(db_session, first_slot.id) == 1
    assert appointment_count(db_session, other_slot.id) == 0
    assert slot_status(db_session, other_slot.id) == "available"

    receipt_after = receipts(db_session, setup, key)
    assert [dict(r) for r in receipt_after] == [dict(r) for r in receipt_before]
    assert json.loads(receipt_after[0]["response_body"])[
        "appointment_reference"
    ] == first.appointment_reference


# ============================================================
# APPOINTMENT + RECEIPT ARE COMMITTED ATOMICALLY
# ============================================================


def test_appointment_and_completed_receipt_share_one_commit(db_session, monkeypatch):
    setup = lab_setup(db_session)
    slot = setup.slots[0]
    key = new_key()

    real_commit = db_session.commit
    seen_at_commit = []

    def spying_commit():
        # commit() flushes pending ORM changes before committing; do that
        # first so the raw SQL below sees exactly what is about to be committed.
        db_session.flush()
        rows = receipts(db_session, setup, key)
        seen_at_commit.append(
            (appointment_count(db_session, slot.id), [r["status"] for r in rows])
        )
        real_commit()

    monkeypatch.setattr(db_session, "commit", spying_commit)

    created = book(setup, booking_request(setup, slot), key)

    # Exactly one commit, carrying both the appointment and the completed receipt.
    assert seen_at_commit == [(1, ["completed"])]
    assert created.status == "confirmed"


def test_failure_after_insert_leaves_neither_appointment_nor_receipt(db_session, monkeypatch):
    setup = lab_setup(db_session)
    slot = setup.slots[0]
    key = new_key()

    # Fail after the pending receipt, the appointment and the slot update
    # were written, but before the single commit.
    def fail(**kwargs):
        raise RuntimeError("injected failure")

    with monkeypatch.context() as patch:
        patch.setattr(setup.service.repository, "insert_status_history", fail)
        with pytest.raises(RuntimeError, match="injected failure"):
            book(setup, booking_request(setup, slot), key)

    assert appointment_count(db_session, slot.id) == 0
    assert receipts(db_session, setup, key) == []
    assert slot_status(db_session, slot.id) == "available"

    # No half-written receipt is left behind, so the same key still works.
    retried = book(setup, booking_request(setup, slot), key)
    assert retried.status == "confirmed"
    assert appointment_count(db_session, slot.id) == 1
    assert [r["status"] for r in receipts(db_session, setup, key)] == ["completed"]
