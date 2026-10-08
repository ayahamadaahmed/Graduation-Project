from decimal import Decimal
from uuid import uuid4

from app.models.radiology_report import (
    RadiologyReport,
)
from app.repositories.radiology_repository import (
    RadiologyRepository,
)


class FakeSession:

    def __init__(self) -> None:
        self.added = []
        self.flush_count = 0
        self.scalar_result = None

    def add(
        self,
        value,
    ) -> None:

        self.added.append(
            value
        )

    def flush(
        self,
    ) -> None:

        self.flush_count += 1

    def scalar(
        self,
        statement,
    ):

        return self.scalar_result


def make_report() -> RadiologyReport:

    return RadiologyReport(
        id=uuid4(),
        patient_id=None,
        provider_id=uuid4(),
        encounter_id=None,
        diagnostic_attachment_id=uuid4(),
        modality="chest_xray",
        status="pending",
    )


def test_create_report():

    session = FakeSession()

    repository = RadiologyRepository(
        session
    )

    provider_id = uuid4()
    attachment_id = uuid4()

    report = repository.create_report(
        provider_id=provider_id,
        diagnostic_attachment_id=(
            attachment_id
        ),
        modality="chest_xray",
    )

    assert session.added == [
        report
    ]

    assert session.flush_count == 1

    assert (
        report.provider_id
        == provider_id
    )

    assert (
        report.diagnostic_attachment_id
        == attachment_id
    )

    assert (
        report.modality
        == "chest_xray"
    )

    assert report.status == "pending"


def test_create_assessment():

    session = FakeSession()

    repository = RadiologyRepository(
        session
    )

    report_id = uuid4()

    assessment = (
        repository.create_assessment(
            radiology_report_id=(
                report_id
            ),
            classification="normal",
            probabilities_json=(
                '{"normal": 0.8, '
                '"pneumonia": 0.2}'
            ),
            confidence=Decimal(
                "0.8"
            ),
            inference_latency_ms=Decimal(
                "271.4"
            ),
            model_name=(
                "medmind_chest_xray"
            ),
            model_version="1.0",
            limitations_json=(
                '["Decision-support only."]'
            ),
        )
    )

    assert session.added == [
        assessment
    ]

    assert session.flush_count == 1

    assert (
        assessment.radiology_report_id
        == report_id
    )

    assert (
        assessment.classification
        == "normal"
    )

    assert (
        assessment.confidence
        == Decimal("0.8")
    )


def test_get_report_returns_scalar_result():

    session = FakeSession()

    expected = make_report()

    session.scalar_result = (
        expected
    )

    repository = RadiologyRepository(
        session
    )

    result = (
        repository
        .get_report_by_attachment(
            provider_id=(
                expected.provider_id
            ),
            diagnostic_attachment_id=(
                expected
                .diagnostic_attachment_id
            ),
        )
    )

    assert result is expected


def test_bind_report_to_patient():

    session = FakeSession()

    repository = RadiologyRepository(
        session
    )

    report = make_report()

    patient_id = uuid4()

    result = (
        repository
        .bind_report_to_patient(
            report=report,
            patient_id=patient_id,
        )
    )

    assert (
        result.patient_id
        == patient_id
    )

    assert session.flush_count == 1


def test_bind_report_to_encounter():

    session = FakeSession()

    repository = RadiologyRepository(
        session
    )

    report = make_report()

    encounter_id = uuid4()

    result = (
        repository
        .bind_report_to_encounter(
            report=report,
            encounter_id=encounter_id,
        )
    )

    assert (
        result.encounter_id
        == encounter_id
    )

    assert session.flush_count == 1


def test_set_report_status():

    session = FakeSession()

    repository = RadiologyRepository(
        session
    )

    report = make_report()

    result = (
        repository
        .set_report_status(
            report=report,
            status="processed",
        )
    )

    assert (
        result.status
        == "processed"
    )

    assert session.flush_count == 1