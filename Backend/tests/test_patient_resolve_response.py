"""
Regression: POST /patients/resolve returned 500 because PatientRead
expects `masked_national_id`, which the Patient ORM model did not expose.
Uses a REAL Patient model instance (not a SimpleNamespace fake).
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from cryptography.fernet import Fernet

from app.core.patient_identity import PatientIdentityProtector
from app.models.patient import Patient
from app.services.patient_service import PatientService


NATIONAL_ID = "29001011234567"


class FakeSession:
    def commit(self):
        pass

    def rollback(self):
        pass

    def refresh(self, _instance):
        pass


class FakeRepository:
    """Creates real Patient ORM objects; never touches a database."""

    def __init__(self, existing=None):
        self.session = FakeSession()
        self.existing = existing

    def get_by_national_id_hash(self, national_id_hash):
        return self.existing

    def generate_patient_code(self, year):
        return f"P-{year}-000001"

    def create_patient(self, **fields):
        now = datetime.now(timezone.utc)
        return Patient(
            id=uuid4(),
            is_active=True,
            created_at=now,
            updated_at=now,
            **fields,
        )

    def get_provider_profile(self, *, patient_id, provider_id):
        return None

    def create_provider_profile(self, *, patient_id, provider_id, preferred_channel):
        return SimpleNamespace(id=uuid4())


def make_service(repository):
    return PatientService(
        repository=repository,
        identity_protector=PatientIdentityProtector(
            hash_key="test-only-hash-key-" + "x" * 32,
            encryption_key=Fernet.generate_key().decode(),
        ),
    )


def test_masked_national_id_shows_only_last4():
    patient = Patient(national_id_last4="4567")

    assert patient.masked_national_id == "**********4567"


def test_resolve_new_patient_returns_masked_response():
    service = make_service(FakeRepository())

    result = service.resolve_for_booking(
        provider_id=uuid4(),
        provider_timezone="Africa/Cairo",
        national_id=NATIONAL_ID,
        patient_name="Test Patient",
        phone="01012345678",
        preferred_language="en",
        channel="web",
    )

    assert result.patient_created is True
    assert result.provider_profile_created is True
    assert result.patient.masked_national_id == "**********4567"
    assert result.patient.full_name_en == "Test Patient"

    # The raw national ID never appears in the serialized response.
    assert NATIONAL_ID not in result.model_dump_json()


def test_resolve_existing_patient_returns_masked_response():
    now = datetime.now(timezone.utc)
    existing = Patient(
        id=uuid4(),
        patient_code="P-2026-000002",
        national_id_hash="h" * 64,
        national_id_encrypted=b"x",
        national_id_last4="4567",
        full_name_ar="مريض تجريبي",
        phone="01012345678",
        preferred_language="ar",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    service = make_service(FakeRepository(existing=existing))

    result = service.resolve_for_booking(
        provider_id=uuid4(),
        provider_timezone="Africa/Cairo",
        national_id=NATIONAL_ID,
        patient_name="مريض تجريبي",
        phone="01012345678",
        preferred_language="ar",
        channel="web",
    )

    assert result.patient_created is False
    assert result.patient.masked_national_id == "**********4567"
    assert NATIONAL_ID not in result.model_dump_json()
