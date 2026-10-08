from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.patient import Patient
from app.models.patient_provider_profile import (
    PatientProviderProfile,
)


class PatientRepository:
    def __init__(
        self,
        session: Session,
    ) -> None:
        self.session = session

    def get_by_national_id_hash(
        self,
        national_id_hash: str,
    ) -> Patient | None:
        statement = select(Patient).where(
            Patient.national_id_hash
            == national_id_hash
        )

        return self.session.scalar(statement)

    def get_active_by_national_id_hash(
        self,
        national_id_hash: str,
    ) -> Patient | None:
        statement = select(Patient).where(
            Patient.national_id_hash
            == national_id_hash,
            Patient.is_active == 1,
        )

        return self.session.scalar(statement)

    def get_provider_profile(
        self,
        *,
        patient_id: UUID,
        provider_id: UUID,
    ) -> PatientProviderProfile | None:
        statement = select(
            PatientProviderProfile
        ).where(
            PatientProviderProfile.patient_id
            == patient_id,
            PatientProviderProfile.provider_id
            == provider_id,
        )

        return self.session.scalar(statement)

    def generate_patient_code(
        self,
        year: int,
    ) -> str:
        statement = text(
            """
            MERGE dbo.patient_number_sequences
            WITH (HOLDLOCK) AS target

            USING (
                SELECT CAST(:year AS INT) AS [year]
            ) AS source

            ON target.[year] = source.[year]

            WHEN MATCHED THEN
                UPDATE SET
                    last_number =
                        target.last_number + 1,
                    updated_at =
                        SYSUTCDATETIME()

            WHEN NOT MATCHED THEN
                INSERT (
                    [year],
                    last_number,
                    updated_at
                )
                VALUES (
                    source.[year],
                    1,
                    SYSUTCDATETIME()
                )

            OUTPUT inserted.last_number;
            """
        )

        number = self.session.execute(
            statement,
            {
                "year": year,
            },
        ).scalar_one()

        return f"{year}{number:03d}"

    def create_patient(
        self,
        *,
        patient_code: str,
        national_id_hash: str,
        national_id_encrypted: bytes,
        national_id_last4: str,
        full_name_ar: str,
        full_name_en: str | None,
        phone: str,
        preferred_language: str,
    ) -> Patient:
        patient = Patient(
            id=uuid4(),
            patient_code=patient_code,
            national_id_hash=national_id_hash,
            national_id_encrypted=(
                national_id_encrypted
            ),
            national_id_last4=(
                national_id_last4
            ),
            full_name_ar=full_name_ar,
            full_name_en=full_name_en,
            date_of_birth=None,
            gender=None,
            phone=phone,
            email=None,
            preferred_language=(
                preferred_language
            ),
            location=None,
            digital_literacy_flag=(
                "phone_only"
            ),
            is_active=True,
        )

        self.session.add(patient)
        self.session.flush()

        return patient

    def create_provider_profile(
        self,
        *,
        patient_id: UUID,
        provider_id: UUID,
        preferred_channel: str,
    ) -> PatientProviderProfile:
        profile = PatientProviderProfile(
            id=uuid4(),
            patient_id=patient_id,
            provider_id=provider_id,
            medical_record_number=None,
            preferred_channel=(
                preferred_channel
            ),
            consent_status="pending",
            consent_timestamp=None,
            is_active=True,
        )

        self.session.add(profile)
        self.session.flush()

        return profile


    def get_active_by_id(
    self,
    patient_id: UUID,
) -> Patient | None:

        statement = (
            select(
                Patient
            )
            .where(
                Patient.id
                == patient_id,

                Patient.is_active
                == 1,
            )
        )

        return self.session.scalar(
            statement
        )