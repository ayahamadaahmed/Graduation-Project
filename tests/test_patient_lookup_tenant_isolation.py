from types import SimpleNamespace
from uuid import uuid4

from app.services.patient_service import (
    PatientService,
)


# ============================================================
# FAKES
# ============================================================


class FakeIdentityProtector:

    def hash_national_id(
        self,
        national_id: str,
    ) -> str:

        return f"hash:{national_id}"


class FakeRepository:

    def __init__(
        self,
        *,
        patient,
        provider_profile,
    ) -> None:

        self.patient = patient

        self.provider_profile = (
            provider_profile
        )

        self.provider_profile_calls = []

    def get_active_by_national_id_hash(
        self,
        national_id_hash: str,
    ):

        return self.patient

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


def make_patient():

    return SimpleNamespace(
        id=uuid4(),
        patient_code="PAT-TEST-001",
        full_name_ar="مريض اختبار",
        full_name_en="Test Patient",
        masked_national_id="**********3456",
        phone="01000000000",
    )


def make_service(
    repository,
) -> PatientService:

    return PatientService(
        repository=repository,
        identity_protector=(
            FakeIdentityProtector()
        ),
    )


# ============================================================
# SAME PROVIDER
# ============================================================


def test_lookup_returns_patient_for_active_provider_profile():

    patient = make_patient()

    provider_id = uuid4()

    repository = FakeRepository(
        patient=patient,
        provider_profile=SimpleNamespace(
            is_active=True,
        ),
    )

    service = make_service(
        repository
    )

    result = service.lookup(
        provider_id=provider_id,
        national_id="12345678913456",
        language="en",
    )

    assert result is not None

    assert (
        result.patient_id
        == patient.id
    )

    assert (
        result.display_name
        == "Test Patient"
    )

    assert (
        repository
        .provider_profile_calls
        == [
            {
                "patient_id":
                    patient.id,

                "provider_id":
                    provider_id,
            }
        ]
    )


# ============================================================
# DIFFERENT / UNRELATED PROVIDER
# ============================================================


def test_lookup_hides_patient_without_provider_profile():

    patient = make_patient()

    provider_id = uuid4()

    repository = FakeRepository(
        patient=patient,
        provider_profile=None,
    )

    service = make_service(
        repository
    )

    result = service.lookup(
        provider_id=provider_id,
        national_id="12345678913456",
        language="ar",
    )

    assert result is None


# ============================================================
# INACTIVE PROVIDER PROFILE
# ============================================================


def test_lookup_hides_patient_with_inactive_provider_profile():

    patient = make_patient()

    provider_id = uuid4()

    repository = FakeRepository(
        patient=patient,
        provider_profile=SimpleNamespace(
            is_active=False,
        ),
    )

    service = make_service(
        repository
    )

    result = service.lookup(
        provider_id=provider_id,
        national_id="12345678913456",
        language="ar",
    )

    assert result is None