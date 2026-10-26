"""SQLAlchemy mappings for the existing MedMind_Booking_DB tables."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EHREncounter(Base):
    """A clinical encounter."""

    __tablename__ = "ehr_encounters"

    __table_args__ = (
        # Child records (reports, notes, conditions...) reference this key so that their
        # provider and patient are guaranteed to match the encounter's.
        UniqueConstraint("id", "provider_id", "patient_id", name="UQ_ehr_encounters_id_provider_patient"),
        ForeignKeyConstraint(
            ["doctor_id", "provider_id"],
            ["doctors.id", "doctors.provider_id"],
            name="FK_ehr_encounters_doctor_provider",
        ),
        ForeignKeyConstraint(
            ["branch_id", "provider_id"],
            ["branches.id", "branches.provider_id"],
            name="FK_ehr_encounters_branch_provider",
        ),
        ForeignKeyConstraint(
            ["appointment_id", "provider_id"],
            ["appointments.id", "appointments.provider_id"],
            name="FK_ehr_encounters_appointment_provider",
        ),
        Index("IX_ehr_encounters_patient_started", "patient_id", "started_at"),
        Index("IX_ehr_encounters_provider_started", "provider_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        primary_key=True,
        server_default=func.newid(),
    )
    patient_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("patients.id", name="FK_ehr_encounters_patient"),
    )
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("providers.id", name="FK_ehr_encounters_provider"),
    )
    doctor_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("doctors.id", name="FK_ehr_encounters_doctor"),
    )
    branch_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("branches.id", name="FK_ehr_encounters_branch"),
    )
    appointment_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
    )
    encounter_type: Mapped[str] = mapped_column(
        String(30),
    )
    status: Mapped[str] = mapped_column(
        String(20),
    )
    started_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DATETIMEOFFSET,
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
