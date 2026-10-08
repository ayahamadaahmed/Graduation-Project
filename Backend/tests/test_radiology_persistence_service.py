import json

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.radiology_persistence_service import (
    RadiologyAssessmentPersistenceInput,
    RadiologyPersistenceError,
    RadiologyPersistenceService,
)


class FakeSession:

    def __init__(
        self,
    ) -> None:

        self.commit_count = 0
        self.rollback_count = 0

    def commit(
        self,
    ) -> None:

        self.commit_count += 1

    def rollback(
        self,
    ) -> None:

        self.rollback_count += 1


class FakeRepository:

    def __init__(
        self,
    ) -> None:

        self.session = FakeSession()

        self.create_report_calls = []
        self.create_assessment_calls = []
        self.set_status_calls = []

        self.fail_assessment = False

    def create_report(
        self,
        **kwargs,
    ):

        self.create_report_calls.append(
            kwargs
        )

        return SimpleNamespace(
            id=uuid4(),
            status=kwargs["status"],
        )

    def create_assessment(
        self,
        **kwargs,
    ):

        if self.fail_assessment:
            raise RuntimeError(
                "simulated assessment failure"
            )

        self.create_assessment_calls.append(
            kwargs
        )

        return SimpleNamespace(
            id=uuid4(),
        )

    def set_report_status(
        self,
        *,
        report,
        status,
    ):

        self.set_status_calls.append(
            {
                "report": report,
                "status": status,
            }
        )

        report.status = status

        return report


def make_assessment():
    return RadiologyAssessmentPersistenceInput(
        classification="normal",
        probabilities={
            "normal": Decimal(
                "0.7836"
            ),
            "pneumonia": Decimal(
                "0.2164"
            ),
        },
        confidence=Decimal(
            "0.7836"
        ),
        inference_latency_ms=Decimal(
            "271.400"
        ),
        model_name=(
            "medmind_chest_xray"
        ),
        model_version="1.0",
        limitations=[
            (
                "Decision-support "
                "classification only."
            ),
        ],
    )


def test_save_processed_report():

    repository = FakeRepository()

    service = (
        RadiologyPersistenceService(
            repository
        )
    )

    provider_id = uuid4()
    attachment_id = uuid4()

    report = (
        service.save_processed_report(
            provider_id=provider_id,
            diagnostic_attachment_id=(
                attachment_id
            ),
            modality="chest_xray",
            assessment=make_assessment(),
        )
    )

    assert report.status == "processed"

    assert (
        repository.session.commit_count
        == 1
    )

    assert (
        repository.session.rollback_count
        == 0
    )

    assert len(
        repository.create_report_calls
    ) == 1

    assert len(
        repository.create_assessment_calls
    ) == 1

    report_call = (
        repository
        .create_report_calls[0]
    )

    assert (
        report_call["provider_id"]
        == provider_id
    )

    assert (
        report_call[
            "diagnostic_attachment_id"
        ]
        == attachment_id
    )

    assert (
        report_call["modality"]
        == "chest_xray"
    )

    assert (
        report_call["status"]
        == "processing"
    )

    assessment_call = (
        repository
        .create_assessment_calls[0]
    )

    probabilities = json.loads(
        assessment_call[
            "probabilities_json"
        ]
    )

    limitations = json.loads(
        assessment_call[
            "limitations_json"
        ]
    )

    assert probabilities == {
        "normal": 0.7836,
        "pneumonia": 0.2164,
    }

    assert limitations == [
        (
            "Decision-support "
            "classification only."
        )
    ]


def test_rejects_unsupported_modality():

    repository = FakeRepository()

    service = (
        RadiologyPersistenceService(
            repository
        )
    )

    with pytest.raises(
        RadiologyPersistenceError
    ):
        service.save_processed_report(
            provider_id=uuid4(),
            diagnostic_attachment_id=uuid4(),
            modality="unknown_scan",
            assessment=make_assessment(),
        )

    assert (
        repository.create_report_calls
        == []
    )

    assert (
        repository.session.commit_count
        == 0
    )


def test_rejects_classification_missing_from_probabilities():

    repository = FakeRepository()

    service = (
        RadiologyPersistenceService(
            repository
        )
    )

    assessment = (
        RadiologyAssessmentPersistenceInput(
            classification="pneumonia",
            probabilities={
                "normal": Decimal(
                    "1.0"
                ),
            },
            confidence=Decimal(
                "1.0"
            ),
            inference_latency_ms=Decimal(
                "100"
            ),
            model_name="model",
            model_version="1",
            limitations=[],
        )
    )

    with pytest.raises(
        RadiologyPersistenceError
    ):
        service.save_processed_report(
            provider_id=uuid4(),
            diagnostic_attachment_id=uuid4(),
            modality="chest_xray",
            assessment=assessment,
        )

    assert (
        repository.create_report_calls
        == []
    )


def test_rejects_probability_out_of_range():

    repository = FakeRepository()

    service = (
        RadiologyPersistenceService(
            repository
        )
    )

    assessment = (
        RadiologyAssessmentPersistenceInput(
            classification="normal",
            probabilities={
                "normal": Decimal(
                    "1.2"
                ),
            },
            confidence=Decimal(
                "0.9"
            ),
            inference_latency_ms=Decimal(
                "100"
            ),
            model_name="model",
            model_version="1",
            limitations=[],
        )
    )

    with pytest.raises(
        RadiologyPersistenceError
    ):
        service.save_processed_report(
            provider_id=uuid4(),
            diagnostic_attachment_id=uuid4(),
            modality="chest_xray",
            assessment=assessment,
        )

    assert (
        repository.create_report_calls
        == []
    )


def test_rejects_invalid_confidence():

    repository = FakeRepository()

    service = (
        RadiologyPersistenceService(
            repository
        )
    )

    assessment = make_assessment()

    invalid = (
        RadiologyAssessmentPersistenceInput(
            classification=(
                assessment.classification
            ),
            probabilities=(
                assessment.probabilities
            ),
            confidence=Decimal(
                "1.1"
            ),
            inference_latency_ms=(
                assessment
                .inference_latency_ms
            ),
            model_name=(
                assessment.model_name
            ),
            model_version=(
                assessment.model_version
            ),
            limitations=(
                assessment.limitations
            ),
        )
    )

    with pytest.raises(
        RadiologyPersistenceError
    ):
        service.save_processed_report(
            provider_id=uuid4(),
            diagnostic_attachment_id=uuid4(),
            modality="chest_xray",
            assessment=invalid,
        )

    assert (
        repository.create_report_calls
        == []
    )


def test_rejects_negative_latency():

    repository = FakeRepository()

    service = (
        RadiologyPersistenceService(
            repository
        )
    )

    assessment = make_assessment()

    invalid = (
        RadiologyAssessmentPersistenceInput(
            classification=(
                assessment.classification
            ),
            probabilities=(
                assessment.probabilities
            ),
            confidence=(
                assessment.confidence
            ),
            inference_latency_ms=Decimal(
                "-1"
            ),
            model_name=(
                assessment.model_name
            ),
            model_version=(
                assessment.model_version
            ),
            limitations=(
                assessment.limitations
            ),
        )
    )

    with pytest.raises(
        RadiologyPersistenceError
    ):
        service.save_processed_report(
            provider_id=uuid4(),
            diagnostic_attachment_id=uuid4(),
            modality="chest_xray",
            assessment=invalid,
        )

    assert (
        repository.create_report_calls
        == []
    )


def test_rolls_back_on_repository_failure():

    repository = FakeRepository()

    repository.fail_assessment = True

    service = (
        RadiologyPersistenceService(
            repository
        )
    )

    with pytest.raises(
        RadiologyPersistenceError
    ):
        service.save_processed_report(
            provider_id=uuid4(),
            diagnostic_attachment_id=uuid4(),
            modality="chest_xray",
            assessment=make_assessment(),
        )

    assert (
        repository.session.commit_count
        == 0
    )

    assert (
        repository.session.rollback_count
        == 1
    )