"""SQLAlchemy mappings for the existing MedMind_Booking_DB tables."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PatientBranchProfile(Base):
    """Per-branch medical record number of a patient."""

    __tablename__ = "patient_branch_profiles"

    __table_args__ = (
        Index("UX_patient_branch_profiles_mrn", "provider_id", "branch_id", "medical_record_number", unique=True),
        Index("UX_patient_branch_profiles_patient", "provider_id", "branch_id", "patient_id", unique=True),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        primary_key=True,
        server_default=func.newid(),
    )
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("providers.id", name="FK_patient_branch_profiles_provider"),
    )
    branch_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("branches.id", name="FK_patient_branch_profiles_branch"),
    )
    patient_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("patients.id", name="FK_patient_branch_profiles_patient"),
    )
    medical_record_number: Mapped[str] = mapped_column(
        String(20),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
