"""SQLAlchemy mapping for a patient's medication list."""

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


class PatientMedication(Base):
    """A medication recorded or prescribed for a patient by one provider."""

    __tablename__ = "patient_medications"

    __table_args__ = (
        ForeignKeyConstraint(
            ["patient_id", "provider_id"],
            ["patient_provider_profiles.patient_id", "patient_provider_profiles.provider_id"],
            name="FK_patient_medications_profile",
        ),
        ForeignKeyConstraint(
            ["encounter_id", "provider_id", "patient_id"],
            ["ehr_encounters.id", "ehr_encounters.provider_id", "ehr_encounters.patient_id"],
            name="FK_patient_medications_encounter",
        ),
        ForeignKeyConstraint(
            ["prescribed_by_doctor_id", "provider_id"],
            ["doctors.id", "doctors.provider_id"],
            name="FK_patient_medications_doctor",
        ),
        CheckConstraint(
            "status IN ('active','completed','stopped')",
            name="CK_patient_medications_status",
        ),
        CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="CK_patient_medications_dates",
        ),
        Index("IX_patient_medications_patient", "provider_id", "patient_id", "status"),
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
    prescribed_by_doctor_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
    )
    medication_name: Mapped[str] = mapped_column(
        Unicode(200),
    )
    dosage: Mapped[str | None] = mapped_column(
        Unicode(100),
    )
    frequency: Mapped[str | None] = mapped_column(
        Unicode(100),
    )
    route: Mapped[str | None] = mapped_column(
        String(30),
    )
    start_date: Mapped[date | None] = mapped_column(
        Date,
    )
    end_date: Mapped[date | None] = mapped_column(
        Date,
    )
    # active / completed / stopped
    status: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'active'"),
    )
    notes: Mapped[str | None] = mapped_column(
        Unicode(500),
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
