from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.diagnostic_attachment_binding_service import (
    DiagnosticAttachmentBindingService,
    DiagnosticEncounterNotFoundError,
    DiagnosticEncounterRequiresPatientError,
    DiagnosticPatientNotFoundError,
    DiagnosticPatientProviderMismatchError,
)


class FakePatientRepository:

    def __init__(self):
        self.patient = None
        self.profile = None

    def get_active_by_id(
        self,
        patient_id,
    ):
        return self.patient

    def get_provider_profile(
        self,
        *,
        patient_id,
        provider_id,
    ):
        return self.profile


class FakeEncounterRepository:

    def __init__(self):
        self.encounter = None
        self.calls = []

    def get_for_patient_provider(
        self,
        *,
        encounter_id,
        patient_id,
        provider_id,
    ):
        self.calls.append(
            {
                "encounter_id":
                    encounter_id,
                "patient_id":
                    patient_id,
                "provider_id":
                    provider_id,
            }
        )

        return self.encounter


def make_service():

    patient_repository = (
        FakePatientRepository()
    )

    encounter_repository = (
        FakeEncounterRepository()
    )

    service = (
        DiagnosticAttachmentBindingService(
            patient_repository=(
                patient_repository
            ),
            encounter_repository=(
                encounter_repository
            ),
        )
    )

    return (
        service,
        patient_repository,
        encounter_repository,
    )


def test_unbound_attachment_is_allowed():

    (
        service,
        _,
        _,
    ) = make_service()

    result = service.resolve(
        provider_id=uuid4(),
    )

    assert result.patient_id is None
    assert result.encounter_id is None


def test_encounter_requires_patient():

    (
        service,
        _,
        _,
    ) = make_service()

    with pytest.raises(
        DiagnosticEncounterRequiresPatientError
    ):

        service.resolve(
            provider_id=uuid4(),
            encounter_id=uuid4(),
        )


def test_patient_must_be_active():

    (
        service,
        patient_repository,
        _,
    ) = make_service()

    patient_repository.patient = None

    with pytest.raises(
        DiagnosticPatientNotFoundError
    ):

        service.resolve(
            provider_id=uuid4(),
            patient_id=uuid4(),
        )


def test_patient_must_belong_to_provider():

    (
        service,
        patient_repository,
        _,
    ) = make_service()

    patient_repository.patient = (
        SimpleNamespace(
            id=uuid4()
        )
    )

    patient_repository.profile = None

    with pytest.raises(
        DiagnosticPatientProviderMismatchError
    ):

        service.resolve(
            provider_id=uuid4(),
            patient_id=uuid4(),
        )


def test_provider_profile_must_be_active():

    (
        service,
        patient_repository,
        _,
    ) = make_service()

    patient_repository.patient = (
        SimpleNamespace(
            id=uuid4()
        )
    )

    patient_repository.profile = (
        SimpleNamespace(
            is_active=False
        )
    )

    with pytest.raises(
        DiagnosticPatientProviderMismatchError
    ):

        service.resolve(
            provider_id=uuid4(),
            patient_id=uuid4(),
        )


def test_valid_patient_binding():

    (
        service,
        patient_repository,
        _,
    ) = make_service()

    patient_id = uuid4()
    provider_id = uuid4()

    patient_repository.patient = (
        SimpleNamespace(
            id=patient_id
        )
    )

    patient_repository.profile = (
        SimpleNamespace(
            is_active=True
        )
    )

    result = service.resolve(
        provider_id=provider_id,
        patient_id=patient_id,
    )

    assert (
        result.patient_id
        == patient_id
    )

    assert result.encounter_id is None


def test_encounter_must_match_patient_and_provider():

    (
        service,
        patient_repository,
        encounter_repository,
    ) = make_service()

    patient_repository.patient = (
        SimpleNamespace(
            id=uuid4()
        )
    )

    patient_repository.profile = (
        SimpleNamespace(
            is_active=True
        )
    )

    encounter_repository.encounter = None

    with pytest.raises(
        DiagnosticEncounterNotFoundError
    ):

        service.resolve(
            provider_id=uuid4(),
            patient_id=uuid4(),
            encounter_id=uuid4(),
        )


def test_valid_patient_and_encounter_binding():

    (
        service,
        patient_repository,
        encounter_repository,
    ) = make_service()

    patient_id = uuid4()
    provider_id = uuid4()
    encounter_id = uuid4()

    patient_repository.patient = (
        SimpleNamespace(
            id=patient_id
        )
    )

    patient_repository.profile = (
        SimpleNamespace(
            is_active=True
        )
    )

    encounter_repository.encounter = (
        SimpleNamespace(
            id=encounter_id
        )
    )

    result = service.resolve(
        provider_id=provider_id,
        patient_id=patient_id,
        encounter_id=encounter_id,
    )

    assert (
        result.patient_id
        == patient_id
    )

    assert (
        result.encounter_id
        == encounter_id
    )

    assert (
        encounter_repository.calls
        == [
            {
                "encounter_id":
                    encounter_id,
                "patient_id":
                    patient_id,
                "provider_id":
                    provider_id,
            }
        ]
    )