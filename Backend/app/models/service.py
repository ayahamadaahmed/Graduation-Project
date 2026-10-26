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


class Service(Base):
    """A bookable service offered by a provider."""

    __tablename__ = "services"

    __table_args__ = (
        UniqueConstraint("provider_id", "code", name="UQ_services_provider_code"),
        CheckConstraint('duration_minutes>(0)', name="CK_services_duration_minutes"),
        CheckConstraint('price IS NULL OR price>=(0)', name="CK_services_price"),
        CheckConstraint((
            "service_type='surgery' "
            "OR service_type='procedure' "
            "OR service_type='diagnostic' "
            "OR service_type='follow_up' "
            "OR service_type='teleconsultation' "
            "OR service_type='consultation'"
        ), name="CK_services_service_type"),
        CheckConstraint('voice_featured_rank IS NULL OR voice_featured_rank>(0)', name="ck_services_voice_featured_rank_positive"),
        Index("IX_services_provider_active", "provider_id", "is_active"),
        Index("IX_services_provider_type", "provider_id", "service_type"),
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
    code: Mapped[str] = mapped_column(
        String(50),
    )
    name_ar: Mapped[str] = mapped_column(
        Unicode(150),
    )
    name_en: Mapped[str] = mapped_column(
        Unicode(150),
    )
    description_ar: Mapped[str | None] = mapped_column(
        UnicodeText(),
    )
    description_en: Mapped[str | None] = mapped_column(
        UnicodeText(),
    )
    duration_minutes: Mapped[int] = mapped_column(
        Integer,
    )
    price: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
    )
    service_type: Mapped[str] = mapped_column(
        String(30),
        server_default=text("'consultation'"),
    )
    requires_preparation: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("0"),
    )
    preparation_instructions_ar: Mapped[str | None] = mapped_column(
        UnicodeText(),
    )
    preparation_instructions_en: Mapped[str | None] = mapped_column(
        UnicodeText(),
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
    voice_label_ar: Mapped[str | None] = mapped_column(
        Unicode(160),
    )
    voice_label_en: Mapped[str | None] = mapped_column(
        Unicode(160),
    )
    voice_featured_rank: Mapped[int | None] = mapped_column(
        Integer,
    )


class ServiceSpecialty(Base):
    """Link between a service and a specialty."""

    __tablename__ = "service_specialties"

    __table_args__ = (
        UniqueConstraint("service_id", "specialty_id", name="UQ_service_specialties_service_specialty"),
        Index("IX_service_specialties_provider", "provider_id"),
        Index("IX_service_specialties_specialty", "specialty_id"),
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
    service_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("services.id"),
    )
    specialty_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("specialties.id"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
