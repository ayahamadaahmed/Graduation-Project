from uuid import uuid4

from app.models.ehr_encounter import (
    EHREncounter,
)

from app.repositories.ehr_encounter_repository import (
    EHREncounterRepository,
)


class FakeSession:

    def __init__(self) -> None:
        self.scalar_result = None
        self.scalar_statement = None

    def scalar(
        self,
        statement,
    ):
        self.scalar_statement = statement
        return self.scalar_result


def make_encounter() -> EHREncounter:

    return EHREncounter(
        id=uuid4(),
        patient_id=uuid4(),
        provider_id=uuid4(),
        doctor_id=None,
        branch_id=None,
        appointment_id=None,
        encounter_type="radiology",
        status="completed",
    )


def test_get_for_patient_provider_returns_match():

    session = FakeSession()

    expected = make_encounter()

    session.scalar_result = expected

    repository = (
        EHREncounterRepository(
            session
        )
    )

    result = (
        repository
        .get_for_patient_provider(
            encounter_id=expected.id,
            patient_id=expected.patient_id,
            provider_id=expected.provider_id,
        )
    )

    assert result is expected

    assert (
        session.scalar_statement
        is not None
    )


def test_query_is_scoped_to_encounter_patient_provider():

    session = FakeSession()

    repository = (
        EHREncounterRepository(
            session
        )
    )

    encounter_id = uuid4()
    patient_id = uuid4()
    provider_id = uuid4()

    repository.get_for_patient_provider(
        encounter_id=encounter_id,
        patient_id=patient_id,
        provider_id=provider_id,
    )

    statement = (
        session.scalar_statement
    )

    compiled = statement.compile()

    sql = str(
        compiled
    ).lower()

    params = set(
        compiled.params.values()
    )

    assert "ehr_encounters.id" in sql

    assert (
        "ehr_encounters.patient_id"
        in sql
    )

    assert (
        "ehr_encounters.provider_id"
        in sql
    )

    assert encounter_id in params
    assert patient_id in params
    assert provider_id in params


def test_get_for_patient_provider_returns_none():

    session = FakeSession()

    repository = (
        EHREncounterRepository(
            session
        )
    )

    result = (
        repository
        .get_for_patient_provider(
            encounter_id=uuid4(),
            patient_id=uuid4(),
            provider_id=uuid4(),
        )
    )

    assert result is None