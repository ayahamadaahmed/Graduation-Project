from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, Integer, Numeric, String, Text
from sqlalchemy.dialects.mssql import NVARCHAR, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        primary_key=True,
    )
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        nullable=False,
    )
    specialty_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        nullable=False,
    )
    full_name_ar: Mapped[str] = mapped_column(NVARCHAR(400), nullable=False)
    full_name_en: Mapped[str] = mapped_column(NVARCHAR(400), nullable=False)
    license_number: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    bio_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    bio_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    consultation_fee: Mapped[Decimal | None] = mapped_column(
        Numeric,
        nullable=True,
    )
    teleconsultation_fee: Mapped[Decimal | None] = mapped_column(
        Numeric,
        nullable=True,
    )
    experience_years: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rating_avg: Mapped[Decimal | None] = mapped_column(
        Numeric,
        nullable=True,
    )
    review_count: Mapped[int] = mapped_column(Integer, nullable=False)
    accepting_new_patients: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    verification_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)


class DoctorBranch(Base):
    __tablename__ = "doctor_branches"

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        primary_key=True,
    )
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        nullable=False,
    )
    doctor_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        nullable=False,
    )
    branch_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        nullable=False,
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)


class DoctorService(Base):
    __tablename__ = "doctor_services"

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        primary_key=True,
    )
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        nullable=False,
    )
    doctor_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        nullable=False,
    )
    service_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        nullable=False,
    )
    fee_override: Mapped[Decimal | None] = mapped_column(
        Numeric,
        nullable=True,
    )
    duration_override_minutes: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
