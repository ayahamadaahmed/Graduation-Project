from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.patient_service import (
    PatientService,
)


# ============================================================
# FAKE DATABASE SESSION
# ============================================================

class FakeSession:

    def __init__(
        self,
    ) -> None:

        self.flush_called = False
        self.commit_called = False
        self.rollback_called = False
        self.refresh_called = False

    def flush(
        self,
    ) -> None:

        self.flush_called = True

    def commit(
        self,
    ) -> None:

        self.commit_called = True

    def rollback(
        self,
    ) -> None:

        self.rollback_called = True

    def refresh(
        self,
        instance,
    ) -> None:

        self.refresh_called = True


# ============================================================
# FAKE PATIENT REPOSITORY
# ============================================================

class FakePatientRepository:

    def __init__(
        self,
        *,
        patient=None,
        provider_profile=None,
    ) -> None:

        self.patient = patient

        self.provider_profile = (
            provider_profile
        )

        self.session = (
            FakeSession()
        )

        self.patient_lookup_calls = []
        self.provider_profile_calls = []

    def get_active_by_id(
        self,
        patient_id,
    ):

        self.patient_lookup_calls.append(
            patient_id
        )

        if (
            self.patient is not None
            and
            self.patient.id == patient_id
        ):

            return self.patient

        return None

    def get_provider_profile(
        self,
        *,
        patient_id,
        provider_id,
    ):

        self.provider_profile_calls.append(
            {
                "patient_id":
                    patient_id,

                "provider_id":
                    provider_id,
            }
        )

        return self.provider_profile


# ============================================================
# HELPERS
# ============================================================

def make_patient():

    return SimpleNamespace(
        id=
            uuid4(),

        full_name_ar=
            "آية أحمد",

        full_name_en=
            "Aya Ahmed",

        phone=
            "01023456789",

        is_active=
            1,
    )


def make_provider_profile(
    *,
    patient_id,
    provider_id,
):

    return SimpleNamespace(
        patient_id=
            patient_id,

        provider_id=
            provider_id,
    )


def make_service(
    repository,
) -> PatientService:

    # We deliberately bypass __init__ here so this
    # unit test doesn't depend on constructor wiring.
    service = (
        PatientService.__new__(
            PatientService
        )
    )

    service.repository = (
        repository
    )

    return service


# ============================================================
# TEST 1
#
# UPDATE NAME ONLY
# ============================================================

def test_update_patient_name_only():

    patient = (
        make_patient()
    )

    provider_id = (
        uuid4()
    )

    repository = (
        FakePatientRepository(
            patient=
                patient,

            provider_profile=
                make_provider_profile(
                    patient_id=
                        patient.id,

                    provider_id=
                        provider_id,
                ),
        )
    )

    service = (
        make_service(
            repository
        )
    )

    result = (
        service.update_profile(
            provider_id=
                provider_id,

            patient_id=
                patient.id,

            patient_name=
                "آية محمد",

            phone=
                None,

            language=
                "ar",

            channel=
                "voice",
        )
    )

    assert (
        patient.full_name_ar
        == "آية محمد"
    )

    assert (
        patient.phone
        == "01023456789"
    )

    assert (
        "patient_name"
        in result.updated_fields
    )

    assert (
        "phone"
        not in result.updated_fields
    )

    assert (
        result.display_name
        == "آية محمد"
    )

    assert (
        repository
        .session
        .commit_called
        is True
    )


# ============================================================
# TEST 2
#
# UPDATE PHONE ONLY
# ============================================================

def test_update_patient_phone_only():

    patient = (
        make_patient()
    )

    provider_id = (
        uuid4()
    )

    repository = (
        FakePatientRepository(
            patient=
                patient,

            provider_profile=
                make_provider_profile(
                    patient_id=
                        patient.id,

                    provider_id=
                        provider_id,
                ),
        )
    )

    service = (
        make_service(
            repository
        )
    )

    result = (
        service.update_profile(
            provider_id=
                provider_id,

            patient_id=
                patient.id,

            patient_name=
                None,

            phone=
                "01123456789",

            language=
                "ar",

            channel=
                "voice",
        )
    )

    assert (
        patient.phone
        == "01123456789"
    )

    assert (
        patient.full_name_ar
        == "آية أحمد"
    )

    assert (
        "phone"
        in result.updated_fields
    )

    assert (
        "patient_name"
        not in result.updated_fields
    )

    assert (
        result.phone
        == "01123456789"
    )

    assert (
        repository
        .session
        .commit_called
        is True
    )


# ============================================================
# TEST 3
#
# UPDATE NAME + PHONE
# ============================================================

def test_update_patient_name_and_phone():

    patient = (
        make_patient()
    )

    provider_id = (
        uuid4()
    )

    repository = (
        FakePatientRepository(
            patient=
                patient,

            provider_profile=
                make_provider_profile(
                    patient_id=
                        patient.id,

                    provider_id=
                        provider_id,
                ),
        )
    )

    service = (
        make_service(
            repository
        )
    )

    result = (
        service.update_profile(
            provider_id=
                provider_id,

            patient_id=
                patient.id,

            patient_name=
                "آية محمد",

            phone=
                "01234567890",

            language=
                "ar",

            channel=
                "voice",
        )
    )

    assert (
        patient.full_name_ar
        == "آية محمد"
    )

    assert (
        patient.phone
        == "01234567890"
    )

    assert set(
        result.updated_fields
    ) == {
        "patient_name",
        "phone",
    }

    assert (
        repository
        .session
        .commit_called
        is True
    )


# ============================================================
# TEST 4
#
# INVALID EGYPTIAN MOBILE
# ============================================================

def test_update_patient_rejects_invalid_phone():

    patient = (
        make_patient()
    )

    provider_id = (
        uuid4()
    )

    repository = (
        FakePatientRepository(
            patient=
                patient,

            provider_profile=
                make_provider_profile(
                    patient_id=
                        patient.id,

                    provider_id=
                        provider_id,
                ),
        )
    )

    service = (
        make_service(
            repository
        )
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:

        service.update_profile(
            provider_id=
                provider_id,

            patient_id=
                patient.id,

            patient_name=
                None,

            phone=
                "018892",

            language=
                "ar",

            channel=
                "voice",
        )

    assert (
        exc_info.value.status_code
        == 422
    )

    # Original phone must remain untouched.
    assert (
        patient.phone
        == "01023456789"
    )

    assert (
        repository
        .session
        .commit_called
        is False
    )


# ============================================================
# TEST 5
#
# WRONG PROVIDER MUST NOT UPDATE PATIENT
# ============================================================

def test_provider_cannot_update_unrelated_patient():

    patient = (
        make_patient()
    )

    provider_id = (
        uuid4()
    )

    repository = (
        FakePatientRepository(
            patient=
                patient,

            # No provider profile.
            provider_profile=
                None,
        )
    )

    service = (
        make_service(
            repository
        )
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:

        service.update_profile(
            provider_id=
                provider_id,

            patient_id=
                patient.id,

            patient_name=
                "آية محمد",

            phone=
                None,

            language=
                "ar",

            channel=
                "voice",
        )

    assert (
        exc_info.value.status_code
        == 404
    )

    assert (
        patient.full_name_ar
        == "آية أحمد"
    )

    assert (
        repository
        .session
        .commit_called
        is False
    )


# ============================================================
# TEST 6
#
# UNKNOWN PATIENT
# ============================================================

def test_unknown_patient_cannot_be_updated():

    provider_id = (
        uuid4()
    )

    unknown_patient_id = (
        uuid4()
    )

    repository = (
        FakePatientRepository(
            patient=
                None,

            provider_profile=
                None,
        )
    )

    service = (
        make_service(
            repository
        )
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:

        service.update_profile(
            provider_id=
                provider_id,

            patient_id=
                unknown_patient_id,

            patient_name=
                "آية محمد",

            phone=
                None,

            language=
                "ar",

            channel=
                "voice",
        )

    assert (
        exc_info.value.status_code
        == 404
    )

    assert (
        repository
        .session
        .commit_called
        is False
    )