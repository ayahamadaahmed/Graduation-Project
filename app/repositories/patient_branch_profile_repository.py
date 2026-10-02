from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session


class PatientBranchProfileRepository:
    def __init__(
        self,
        session: Session,
    ) -> None:
        self.session = session

    def get_existing_profile(
        self,
        *,
        provider_id: UUID,
        branch_id: UUID,
        patient_id: UUID,
    ) -> dict[str, Any] | None:
        statement = text(
            """
            SELECT
                id,
                provider_id,
                branch_id,
                patient_id,
                medical_record_number,
                is_active,
                created_at,
                updated_at
            FROM dbo.patient_branch_profiles
            WITH (
                UPDLOCK,
                HOLDLOCK,
                ROWLOCK
            )
            WHERE
                provider_id = :provider_id
                AND branch_id = :branch_id
                AND patient_id = :patient_id;
            """
        )

        row = self.session.execute(
            statement,
            {
                "provider_id": str(provider_id),
                "branch_id": str(branch_id),
                "patient_id": str(patient_id),
            },
        ).mappings().first()

        return dict(row) if row else None

    def get_branch_code(
        self,
        *,
        provider_id: UUID,
        branch_id: UUID,
    ) -> str | None:
        statement = text(
            """
            SELECT
                UPPER(RTRIM(mrn_code))
            FROM dbo.branches
            WHERE
                id = :branch_id
                AND provider_id = :provider_id
                AND is_active = 1;
            """
        )

        value = self.session.execute(
            statement,
            {
                "provider_id": str(provider_id),
                "branch_id": str(branch_id),
            },
        ).scalar_one_or_none()

        if value is None:
            return None

        return str(value)

    def next_number(
        self,
        *,
        provider_id: UUID,
        branch_id: UUID,
        year: int,
    ) -> int:
        statement = text(
            """
            MERGE dbo.branch_mrn_sequences
                WITH (HOLDLOCK) AS target

            USING (
                SELECT
                    CAST(
                        :provider_id
                        AS UNIQUEIDENTIFIER
                    ) AS provider_id,
                    CAST(
                        :branch_id
                        AS UNIQUEIDENTIFIER
                    ) AS branch_id,
                    CAST(
                        :year
                        AS SMALLINT
                    ) AS sequence_year
            ) AS source

            ON
                target.provider_id =
                    source.provider_id
                AND target.branch_id =
                    source.branch_id
                AND target.sequence_year =
                    source.sequence_year

            WHEN MATCHED THEN
                UPDATE SET
                    last_number =
                        target.last_number + 1,
                    updated_at =
                        SYSUTCDATETIME()

            WHEN NOT MATCHED THEN
                INSERT (
                    provider_id,
                    branch_id,
                    sequence_year,
                    last_number,
                    updated_at
                )
                VALUES (
                    source.provider_id,
                    source.branch_id,
                    source.sequence_year,
                    1,
                    SYSUTCDATETIME()
                )

            OUTPUT inserted.last_number;
            """
        )

        number = self.session.execute(
            statement,
            {
                "provider_id": str(provider_id),
                "branch_id": str(branch_id),
                "year": year,
            },
        ).scalar_one()

        return int(number)

    def create_profile(
        self,
        *,
        provider_id: UUID,
        branch_id: UUID,
        patient_id: UUID,
        medical_record_number: str,
    ) -> UUID:
        profile_id = uuid4()

        statement = text(
            """
            INSERT INTO dbo.patient_branch_profiles (
                id,
                provider_id,
                branch_id,
                patient_id,
                medical_record_number,
                is_active,
                created_at,
                updated_at
            )
            VALUES (
                :id,
                :provider_id,
                :branch_id,
                :patient_id,
                :medical_record_number,
                1,
                SYSUTCDATETIME(),
                SYSUTCDATETIME()
            );
            """
        )

        self.session.execute(
            statement,
            {
                "id": str(profile_id),
                "provider_id": str(provider_id),
                "branch_id": str(branch_id),
                "patient_id": str(patient_id),
                "medical_record_number": (
                    medical_record_number
                ),
            },
        )

        return profile_id