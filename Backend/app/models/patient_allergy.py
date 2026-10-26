"""SQLAlchemy mapping for a patient's recorded allergies."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Index,
    String,
    Unicode,
    func,
    text,
)
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PatientAllergy(Base):
    """An allergy recorded for a patient by one provider."""

    __tablename__ = "patient_allergies"

    __table_args__ = (
        ForeignKeyConstraint(
            ["patient_id", "provider_id"],
            ["patient_provider_profiles.patient_id", "patient_provider_profiles.provider_id"],
            name="FK_patient_allergies_profile",
        ),
        ForeignKeyConstraint(
            ["encounter_id", "provider_id", "patient_id"],
            ["ehr_encounters.id", "ehr_encounters.provider_id", "ehr_encounters.patient_id"],
            name="FK_patient_allergies_encounter",
        ),
        ForeignKeyConstraint(
            ["recorded_by_doctor_id", "provider_id"],
            ["doctors.id", "doctors.provider_id"],
            name="FK_patient_allergies_doctor",
        ),
        CheckConstraint(
            "allergen_type IN ('drug','food','environmental','other')",
            name="CK_patient_allergies_type",
        ),
        CheckConstraint(
            "severity IN ('mild','moderate','severe','life_threatening')",
            name="CK_patient_allergies_severity",
        ),
        CheckConstraint(
            "status IN ('active','inactive','resolved')",
            name="CK_patient_allergies_status",
        ),
        Index("IX_patient_allergies_patient", "provider_id", "patient_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        primary_key=True,
        server_default=func.newid(),
    )
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
    )
    patient_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
    )
    encounter_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
    )
    recorded_by_doctor_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
    )
    allergen: Mapped[str] = mapped_column(
        Unicode(200),
    )
    # drug / food / environmental / other
    allergen_type: Mapped[str] = mapped_column(
        String(20),
    )
    reaction: Mapped[str | None] = mapped_column(
        Unicode(300),
    )
    # mild / moderate / severe / life_threatening
    severity: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'mild'"),
    )
    # active / inactive / resolved
    status: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'active'"),
    )
    noted_date: Mapped[date | None] = mapped_column(
        Date,
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
