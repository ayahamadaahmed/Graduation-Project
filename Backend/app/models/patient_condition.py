"""SQLAlchemy mapping for a patient's recorded medical conditions."""

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


class PatientCondition(Base):
    """A medical condition recorded for a patient by one provider.

    The composite foreign keys guarantee that the patient is registered at the
    provider, that the encounter (when set) belongs to the same provider and
    patient, and that the recording doctor belongs to the same provider.
    """

    __tablename__ = "patient_conditions"

    __table_args__ = (
        ForeignKeyConstraint(
            ["patient_id", "provider_id"],
            ["patient_provider_profiles.patient_id", "patient_provider_profiles.provider_id"],
            name="FK_patient_conditions_profile",
        ),
        ForeignKeyConstraint(
            ["encounter_id", "provider_id", "patient_id"],
            ["ehr_encounters.id", "ehr_encounters.provider_id", "ehr_encounters.patient_id"],
            name="FK_patient_conditions_encounter",
        ),
        ForeignKeyConstraint(
            ["recorded_by_doctor_id", "provider_id"],
            ["doctors.id", "doctors.provider_id"],
            name="FK_patient_conditions_doctor",
        ),
        CheckConstraint(
            "clinical_status IN ('active','resolved','inactive')",
            name="CK_patient_conditions_status",
        ),
        CheckConstraint(
            "severity IS NULL OR severity IN ('mild','moderate','severe')",
            name="CK_patient_conditions_severity",
        ),
        CheckConstraint(
            "resolved_date IS NULL OR onset_date IS NULL OR resolved_date >= onset_date",
            name="CK_patient_conditions_dates",
        ),
        CheckConstraint(
            "clinical_status <> 'resolved' OR resolved_date IS NOT NULL",
            name="CK_patient_conditions_resolved",
        ),
        Index("IX_patient_conditions_patient", "provider_id", "patient_id", "clinical_status"),
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
    condition_name: Mapped[str] = mapped_column(
        Unicode(200),
    )
    icd10_code: Mapped[str | None] = mapped_column(
        String(10),
    )
    # active / resolved / inactive
    clinical_status: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'active'"),
    )
    # mild / moderate / severe
    severity: Mapped[str | None] = mapped_column(
        String(20),
    )
    onset_date: Mapped[date | None] = mapped_column(
        Date,
    )
    resolved_date: Mapped[date | None] = mapped_column(
        Date,
    )
    notes: Mapped[str | None] = mapped_column(
        Unicode(1000),
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
