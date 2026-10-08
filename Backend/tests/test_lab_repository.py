from decimal import Decimal
from uuid import uuid4

from app.models.lab_report import (
    LabReport,
)

from app.repositories.lab_repository import (
    LabRepository,
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


def make_report() -> LabReport:

    return LabReport(
        id=uuid4(),
        patient_id=None,
        provider_id=uuid4(),
        encounter_id=None,
        diagnostic_attachment_id=uuid4(),
        document_type="cbc",
        unreadable_fields_json=None,
        status="pending",
    )


def test_create_report():

    session = FakeSession()

    repository = LabRepository(
        session
    )

    provider_id = uuid4()
    attachment_id = uuid4()

    report = repository.create_report(
        provider_id=provider_id,
        diagnostic_attachment_id=(
            attachment_id
        ),
        document_type="cbc",
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

    assert report.patient_id is None

    assert report.status == "pending"


def test_create_result():

    session = FakeSession()

    repository = LabRepository(
        session
    )

    report_id = uuid4()

    result = repository.create_result(
        lab_report_id=report_id,
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
    )

    assert session.added == [
        result
    ]

    assert session.flush_count == 1

    assert (
        result.lab_report_id
        == report_id
    )

    assert (
        result.raw_name
        == "HGB"
    )

    assert (
        result.canonical_name
        == "hemoglobin"
    )

    assert (
        result.value
        == Decimal("9.6")
    )

    assert result.flag == "low"


def test_get_report_returns_scalar_result():

    session = FakeSession()

    expected = make_report()

    session.scalar_result = (
        expected
    )

    repository = LabRepository(
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

    repository = LabRepository(
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

    repository = LabRepository(
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

    repository = LabRepository(
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