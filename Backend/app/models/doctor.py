"""SQLAlchemy mappings for the existing MedMind_Booking_DB tables."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Unicode,
    UnicodeText,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Doctor(Base):
    """A doctor working for a provider."""

    __tablename__ = "doctors"

    __table_args__ = (
        # Lets child tables prove they use a doctor of the same provider (composite foreign keys).
        UniqueConstraint("id", "provider_id", name="UQ_doctors_id_provider"),
        CheckConstraint('consultation_fee IS NULL OR consultation_fee>=(0)', name="CK_doctors_consultation_fee"),
        CheckConstraint('experience_years IS NULL OR experience_years>=(0)', name="CK_doctors_experience_years"),
        CheckConstraint("gender IS NULL OR (gender='female' OR gender='male')", name="CK_doctors_gender"),
        CheckConstraint('rating_avg IS NULL OR rating_avg>=(0) AND rating_avg<=(5)', name="CK_doctors_rating_avg"),
        CheckConstraint('review_count>=(0)', name="CK_doctors_review_count"),
        CheckConstraint('teleconsultation_fee IS NULL OR teleconsultation_fee>=(0)', name="CK_doctors_teleconsultation_fee"),
        CheckConstraint((
            "verification_status='rejected' "
            "OR verification_status='verified' "
            "OR verification_status='pending'"
        ), name="CK_doctors_verification_status"),
        Index("IX_doctors_provider_active", "provider_id", "is_active"),
        Index("IX_doctors_provider_specialty", "provider_id", "specialty_id"),
        Index("UX_doctors_provider_license", "provider_id", "license_number", unique=True, mssql_where=text("license_number IS NOT NULL")),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        primary_key=True,
        server_default=func.newid(),
    )
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("providers.id"),
    )
    specialty_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("specialties.id"),
    )
    full_name_ar: Mapped[str] = mapped_column(
        Unicode(200),
    )
    full_name_en: Mapped[str] = mapped_column(
        Unicode(200),
    )
    license_number: Mapped[str | None] = mapped_column(
        String(100),
    )
    bio_ar: Mapped[str | None] = mapped_column(
        UnicodeText(),
    )
    bio_en: Mapped[str | None] = mapped_column(
        UnicodeText(),
    )
    consultation_fee: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
    )
    teleconsultation_fee: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
    )
    experience_years: Mapped[int | None] = mapped_column(
        Integer,
    )
    gender: Mapped[str | None] = mapped_column(
        String(10),
    )
    photo_url: Mapped[str | None] = mapped_column(
        String(500),
    )
    rating_avg: Mapped[Decimal | None] = mapped_column(
        Numeric(3, 2),
    )
    review_count: Mapped[int] = mapped_column(
        Integer,
        server_default=text("0"),
    )
    accepting_new_patients: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("1"),
    )
    verification_status: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'pending'"),
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


class DoctorBranch(Base):
    """Link between a doctor and a branch."""

    __tablename__ = "doctor_branches"

    __table_args__ = (
        UniqueConstraint("doctor_id", "branch_id", name="UQ_doctor_branches_doctor_branch"),
        Index("IX_doctor_branches_doctor_active", "doctor_id", "is_active"),
        Index("IX_doctor_branches_provider_active", "provider_id", "is_active"),
        Index("UX_doctor_branches_primary", "doctor_id", unique=True, mssql_where=text("is_primary=(1) AND is_active=(1)")),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        primary_key=True,
        server_default=func.newid(),
    )
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("providers.id"),
    )
    doctor_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("doctors.id"),
    )
    branch_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("branches.id"),
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("0"),
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


class DoctorService(Base):
    """Link between a doctor and a service, with optional overrides."""

    __tablename__ = "doctor_services"

    __table_args__ = (
        UniqueConstraint("doctor_id", "service_id", name="UQ_doctor_services_doctor_service"),
        CheckConstraint('duration_override_minutes IS NULL OR duration_override_minutes>(0)', name="CK_doctor_services_duration_override"),
        CheckConstraint('fee_override IS NULL OR fee_override>=(0)', name="CK_doctor_services_fee_override"),
        Index("IX_doctor_services_doctor_active", "doctor_id", "is_active"),
        Index("IX_doctor_services_provider_active", "provider_id", "is_active"),
        Index("IX_doctor_services_service_active", "service_id", "is_active"),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        primary_key=True,
        server_default=func.newid(),
    )
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("providers.id"),
    )
    doctor_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("doctors.id"),
    )
    service_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("services.id"),
    )
    fee_override: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
    )
    duration_override_minutes: Mapped[int | None] = mapped_column(
        Integer,
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
