"""POST /appointments/{reference}/confirm: state machine, patient ownership
and single commit. No database: the repository is a fake."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.schemas.appointment import AppointmentConfirmRequest
from app.services.appointment_service import AppointmentService

PROVIDER = uuid4()
PATIENT = uuid4()
NOW = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeRepository:
    def __init__(self, status, patient_id=PATIENT, provider_id=PROVIDER):
        self.session = FakeSession()
        self.row = {
            "id": uuid4(), "provider_id": provider_id, "appointment_reference": "APT-1",
            "patient_id": patient_id, "slot_id": uuid4(), "status": status,
            "confirmed_at": None,
        }
        self.history = []

    def lock_appointment_by_reference(self, *, provider_id, appointment_reference):
        if provider_id != self.row["provider_id"] or appointment_reference != "APT-1":
            return None
        return dict(self.row)

    def mark_appointment_confirmed(self, *, provider_id, appointment_id):
        if self.row["status"] != "pending":
            return False
        self.row.update(status="confirmed", confirmed_at=NOW)
        return True

    def insert_confirmation_history(self, **kwargs):
        self.history.append(kwargs)

    def get_confirmation_result(self, *, provider_id, appointment_id):
        return dict(self.row)


def _service(repository):
    service = AppointmentService(
        repository=repository,
        patient_repository=None,
        identity_protector=None,
        branch_profile_service=None,
        idempotency_service=None,
    )
    # Patient identity is resolved from the national ID; here it is fixed.
    service._resolve_patient_by_national_id = lambda **_: SimpleNamespace(id=PATIENT)
    return service


def _confirm(service, reference="apt-1 ", provider_id=PROVIDER):
    return service.confirm_booking(
        provider_id=provider_id,
        appointment_reference=reference,
        data=AppointmentConfirmRequest(national_id="29001011234567", changed_by="patient"),
    )


def test_pending_appointment_is_confirmed_with_history_and_one_commit():
    repository = FakeRepository("pending")

    result = _confirm(_service(repository))

    assert (result.previous_status, result.status) == ("pending", "confirmed")
    assert result.confirmed_at == NOW
    assert len(repository.history) == 1
    assert repository.history[0]["changed_by"] == "patient"
    assert repository.session.commits == 1


def test_confirming_twice_is_a_no_op():
    repository = FakeRepository("confirmed")

    result = _confirm(_service(repository))

    assert (result.previous_status, result.status) == ("confirmed", "confirmed")
    assert repository.history == []


@pytest.mark.parametrize("status", ["cancelled", "completed", "no_show"])
def test_final_states_cannot_be_confirmed(status):
    repository = FakeRepository(status)

    with pytest.raises(HTTPException) as exc_info:
        _confirm(_service(repository))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "APPOINTMENT_NOT_CONFIRMABLE"
    assert repository.session.commits == 0
    assert repository.session.rollbacks == 1


def test_other_patients_appointment_is_reported_as_not_found():
    repository = FakeRepository("pending", patient_id=uuid4())

    with pytest.raises(HTTPException) as exc_info:
        _confirm(_service(repository))

    assert exc_info.value.status_code == 404
    assert repository.row["status"] == "pending"
    assert repository.history == []


def test_other_providers_appointment_is_not_found():
    repository = FakeRepository("pending", provider_id=uuid4())

    with pytest.raises(HTTPException) as exc_info:
        _confirm(_service(repository))

    assert exc_info.value.detail["code"] == "APPOINTMENT_NOT_FOUND"
    assert repository.session.commits == 0
