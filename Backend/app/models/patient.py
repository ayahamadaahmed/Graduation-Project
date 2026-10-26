"""SQLAlchemy mappings for the existing MedMind_Booking_DB tables."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Index,
    LargeBinary,
    String,
    Unicode,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Patient(Base):
    """A patient (shared across providers; national id stored hashed and encrypted)."""

    __tablename__ = "patients"

    __table_args__ = (
        UniqueConstraint("national_id_hash", name="UQ_patients_national_id_hash"),
        UniqueConstraint("patient_code", name="UQ_patients_patient_code"),
        CheckConstraint((
            'digital_literacy_flag IS NULL '
            "OR (digital_literacy_flag='app_capable' "
            "OR digital_literacy_flag='phone_only')"
        ), name="CK_patients_digital_literacy"),
        CheckConstraint("gender IS NULL OR (gender='female' OR gender='male')", name="CK_patients_gender"),
        CheckConstraint('len(national_id_hash)=(64)', name="CK_patients_national_id_hash"),
        CheckConstraint("len(national_id_last4)=(4) AND NOT national_id_last4 like '%[^0-9]%'", name="CK_patients_national_id_last4"),
        CheckConstraint("len(patient_code)>=(7) AND NOT patient_code like '%[^0-9]%'", name="CK_patients_patient_code"),
        CheckConstraint("preferred_language='en' OR preferred_language='ar'", name="CK_patients_preferred_language"),
        Index("IX_patients_active", "is_active"),
        Index("IX_patients_last4", "national_id_last4"),
        Index("IX_patients_phone", "phone"),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        primary_key=True,
        server_default=func.newid(),
    )
    date_of_birth: Mapped[date | None] = mapped_column(
        Date,
    )
    gender: Mapped[str | None] = mapped_column(
        String(10),
    )
    phone: Mapped[str] = mapped_column(
        String(30),
    )
    email: Mapped[str | None] = mapped_column(
        String(254),
    )
    preferred_language: Mapped[str] = mapped_column(
        String(10),
        server_default=text("'ar'"),
    )
    location: Mapped[str | None] = mapped_column(
        Unicode(150),
    )
    digital_literacy_flag: Mapped[str | None] = mapped_column(
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
    patient_code: Mapped[str] = mapped_column(
        String(20),
    )
    national_id_hash: Mapped[str] = mapped_column(
        String(64),
    )
    national_id_encrypted: Mapped[bytes] = mapped_column(
        LargeBinary,
    )
    national_id_last4: Mapped[str] = mapped_column(
        String(4),
    )
    full_name_ar: Mapped[str] = mapped_column(
        Unicode(200),
    )
    full_name_en: Mapped[str | None] = mapped_column(
        Unicode(200),
    )

    @property
    def masked_national_id(self) -> str:
        """Display-safe national ID: only the stored last 4 digits."""

        return "*" * 10 + (self.national_id_last4 or "")
