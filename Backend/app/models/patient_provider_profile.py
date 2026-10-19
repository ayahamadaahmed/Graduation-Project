"""SQLAlchemy mappings for the existing MedMind_Booking_DB tables."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PatientProviderProfile(Base):
    """Per-provider profile and consent state of a patient."""

    __tablename__ = "patient_provider_profiles"

    __table_args__ = (
        UniqueConstraint("patient_id", "provider_id", name="UQ_patient_provider_profiles_patient_provider"),
        CheckConstraint((
            "consent_status='pending' "
            "OR consent_status='withdrawn' "
            "OR consent_status='granted'"
        ), name="CK_patient_provider_profiles_consent_status"),
        CheckConstraint((
            "consent_status='pending' "
            "OR (consent_status='withdrawn' "
            "OR consent_status='granted') "
            'AND consent_timestamp IS NOT NULL'
        ), name="CK_patient_provider_profiles_consent_timestamp"),
        CheckConstraint((
            "preferred_channel='mobile' "
            "OR preferred_channel='web' "
            "OR preferred_channel='whatsapp' "
            "OR preferred_channel='voice'"
        ), name="CK_patient_provider_profiles_preferred_channel"),
        Index("IX_patient_provider_profiles_patient", "patient_id"),
        Index("IX_patient_provider_profiles_provider", "provider_id", "is_active"),
        Index("UX_patient_provider_profiles_mrn", "provider_id", "medical_record_number", unique=True, mssql_where=text("medical_record_number IS NOT NULL")),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        primary_key=True,
        server_default=func.newid(),
    )
    patient_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("patients.id"),
    )
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("providers.id"),
    )
    medical_record_number: Mapped[str | None] = mapped_column(
        String(100),
    )
    preferred_channel: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'whatsapp'"),
    )
    consent_status: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'pending'"),
    )
    consent_timestamp: Mapped[datetime | None] = mapped_column(
        DATETIMEOFFSET,
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
