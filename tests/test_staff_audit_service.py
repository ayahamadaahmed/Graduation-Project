from uuid import uuid4

import pytest

from app.services.staff_audit_service import (
    StaffAuditService,
)


class FakeSession:

    def __init__(self):

        self.commits = 0
        self.rollbacks = 0
        self.refreshes = []

    def commit(self):

        self.commits += 1

    def rollback(self):

        self.rollbacks += 1

    def refresh(
        self,
        value,
    ):

        self.refreshes.append(
            value
        )


class FakeRepository:

    def __init__(
        self,
        *,
        fail=False,
    ):

        self.session = FakeSession()

        self.fail = fail

        self.added = []

    def add(
        self,
        audit_log,
    ):

        if self.fail:

            raise RuntimeError(
                "audit write failed"
            )

        self.added.append(
            audit_log
        )

        return audit_log


def test_record_successful_patient_lookup():

    repository = FakeRepository()

    service = StaffAuditService(
        repository
    )

    provider_id = uuid4()
    user_id = uuid4()
    membership_id = uuid4()
    patient_id = uuid4()

    audit = service.record(
        provider_id=provider_id,
        user_id=user_id,
        membership_id=membership_id,
        patient_id=patient_id,
        action="patient.lookup",
        resource_type="patient",
        outcome="success",
    )

    assert (
        audit.provider_id
        == provider_id
    )

    assert (
        audit.user_id
        == user_id
    )

    assert (
        audit.membership_id
        == membership_id
    )

    assert (
        audit.patient_id
        == patient_id
    )

    assert (
        audit.action
        == "patient.lookup"
    )

    assert (
        audit.resource_type
        == "patient"
    )

    assert (
        audit.outcome
        == "success"
    )

    assert (
        repository.session.commits
        == 1
    )

    assert (
        repository.session.rollbacks
        == 0
    )


def test_record_not_found_without_patient():

    repository = FakeRepository()

    service = StaffAuditService(
        repository
    )

    audit = service.record(
        provider_id=uuid4(),
        user_id=uuid4(),
        membership_id=uuid4(),
        action="patient.lookup",
        resource_type="patient",
        outcome="not_found",
    )

    assert audit.patient_id is None

    assert (
        audit.outcome
        == "not_found"
    )

    assert (
        repository.session.commits
        == 1
    )


def test_invalid_outcome_rejected():

    repository = FakeRepository()

    service = StaffAuditService(
        repository
    )

    with pytest.raises(
        ValueError
    ):

        service.record(
            provider_id=uuid4(),
            user_id=uuid4(),
            membership_id=uuid4(),
            action="patient.lookup",
            resource_type="patient",
            outcome="maybe",
        )

    assert (
        repository.session.commits
        == 0
    )


def test_repository_failure_rolls_back():

    repository = FakeRepository(
        fail=True
    )

    service = StaffAuditService(
        repository
    )

    with pytest.raises(
        RuntimeError
    ):

        service.record(
            provider_id=uuid4(),
            user_id=uuid4(),
            membership_id=uuid4(),
            action="patient.lookup",
            resource_type="patient",
            outcome="success",
        )

    assert (
        repository.session.commits
        == 0
    )

    assert (
        repository.session.rollbacks
        == 1
    )