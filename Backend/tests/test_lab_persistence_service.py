from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.lab_persistence_service import (
    LabPersistenceError,
    LabPersistenceService,
    LabResultPersistenceInput,
)


class FakeSession:

    def __init__(
        self,
        *,
        fail_commit: bool = False,
    ) -> None:

        self.fail_commit = fail_commit
        self.commit_count = 0
        self.rollback_count = 0

    def commit(
        self,
    ) -> None:

        self.commit_count += 1

        if self.fail_commit:
            raise RuntimeError(
                "commit failed"
            )

    def rollback(
        self,
    ) -> None:

        self.rollback_count += 1


class FakeRepository:

    def __init__(
        self,
        *,
        fail_result_index: int | None = None,
        fail_commit: bool = False,
    ) -> None:

        self.session = FakeSession(
            fail_commit=fail_commit
        )

        self.fail_result_index = (
            fail_result_index
        )

        self.created_report_kwargs = None
        self.created_results = []
        self.status_updates = []

    def create_report(
        self,
        **kwargs,
    ):

        self.created_report_kwargs = (
            kwargs
        )

        return SimpleNamespace(
            id=uuid4(),
            status=kwargs["status"],
        )

    def create_result(
        self,
        **kwargs,
    ):

        if (
            self.fail_result_index
            == kwargs["result_index"]
        ):
            raise RuntimeError(
                "result insert failed"
            )

        self.created_results.append(
            kwargs
        )

        return SimpleNamespace(
            **kwargs
        )

    def set_report_status(
        self,
        *,
        report,
        status,
    ):

        report.status = status

        self.status_updates.append(
            status
        )

        return report


def sample_results():

    return [
        LabResultPersistenceInput(
            result_index=0,
            panel="cbc",
            raw_name="HGB",
            canonical_name="hemoglobin",
            value=Decimal("9.6"),
            unit="g/dL",
            reference_min=Decimal("12"),
            reference_max=Decimal("16"),
            reference_text="12 - 16",
            flag="low",
            mapping_status="mapped",
        ),
        LabResultPersistenceInput(
            result_index=1,
            panel="cbc",
            raw_name="WBC",
            canonical_name="wbc",
            value=Decimal("6.7"),
            unit="10^3/uL",
            reference_min=Decimal("4"),
            reference_max=Decimal("11"),
            reference_text="4 - 11",
            flag="normal",
            mapping_status="mapped",
        ),
    ]


def test_save_processed_report_commits_once():

    repository = FakeRepository()

    service = LabPersistenceService(
        repository
    )

    report = service.save_processed_report(
        provider_id=uuid4(),
        diagnostic_attachment_id=uuid4(),
        document_type="cbc",
        results=sample_results(),
        unreadable_fields=[],
    )

    assert (
        repository.session.commit_count
        == 1
    )

    assert (
        repository.session.rollback_count
        == 0
    )

    assert (
        len(
            repository.created_results
        )
        == 2
    )

    assert (
        repository.status_updates
        == ["processed"]
    )

    assert (
        report.status
        == "processed"
    )


def test_result_failure_rolls_back():

    repository = FakeRepository(
        fail_result_index=1
    )

    service = LabPersistenceService(
        repository
    )

    with pytest.raises(
        LabPersistenceError
    ):

        service.save_processed_report(
            provider_id=uuid4(),
            diagnostic_attachment_id=uuid4(),
            document_type="cbc",
            results=sample_results(),
        )

    assert (
        repository.session.commit_count
        == 0
    )

    assert (
        repository.session.rollback_count
        == 1
    )


def test_commit_failure_rolls_back():

    repository = FakeRepository(
        fail_commit=True
    )

    service = LabPersistenceService(
        repository
    )

    with pytest.raises(
        LabPersistenceError
    ):

        service.save_processed_report(
            provider_id=uuid4(),
            diagnostic_attachment_id=uuid4(),
            document_type="cbc",
            results=sample_results(),
        )

    assert (
        repository.session.commit_count
        == 1
    )

    assert (
        repository.session.rollback_count
        == 1
    )


def test_rejects_duplicate_result_index():

    repository = FakeRepository()

    service = LabPersistenceService(
        repository
    )

    results = sample_results()

    results[1] = (
        LabResultPersistenceInput(
            result_index=0,
            panel="cbc",
            raw_name="WBC",
            canonical_name="wbc",
            value=Decimal("6.7"),
            unit="10^3/uL",
            flag="normal",
            mapping_status="mapped",
        )
    )

    with pytest.raises(
        LabPersistenceError
    ):

        service.save_processed_report(
            provider_id=uuid4(),
            diagnostic_attachment_id=uuid4(),
            document_type="cbc",
            results=results,
        )

    assert (
        repository.session.commit_count
        == 0
    )


def test_rejects_invalid_flag():

    repository = FakeRepository()

    service = LabPersistenceService(
        repository
    )

    bad_result = (
        LabResultPersistenceInput(
            result_index=0,
            raw_name="HGB",
            flag="critical",
            mapping_status="mapped",
        )
    )

    with pytest.raises(
        LabPersistenceError
    ):

        service.save_processed_report(
            provider_id=uuid4(),
            diagnostic_attachment_id=uuid4(),
            document_type="cbc",
            results=[
                bad_result
            ],
        )


def test_rejects_empty_results():

    repository = FakeRepository()

    service = LabPersistenceService(
        repository
    )

    with pytest.raises(
        LabPersistenceError
    ):

        service.save_processed_report(
            provider_id=uuid4(),
            diagnostic_attachment_id=uuid4(),
            document_type="cbc",
            results=[],
        )