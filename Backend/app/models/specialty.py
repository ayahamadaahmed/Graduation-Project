"""SQLAlchemy mappings for the existing MedMind_Booking_DB tables."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Unicode,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Specialty(Base):
    """A medical specialty offered by a provider."""

    __tablename__ = "specialties"

    __table_args__ = (
        UniqueConstraint("provider_id", "code", name="UQ_specialties_provider_code"),
        # Lets child tables prove they use a specialty of the same provider (composite foreign keys).
        UniqueConstraint("id", "provider_id", name="UQ_specialties_id_provider"),
        Index("IX_specialties_provider_active", "provider_id", "is_active"),
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
        String(100),
    )
    name_ar: Mapped[str] = mapped_column(
        Unicode(150),
    )
    name_en: Mapped[str] = mapped_column(
        Unicode(150),
    )
    description_ar: Mapped[str | None] = mapped_column(
        Unicode(1000),
    )
    description_en: Mapped[str | None] = mapped_column(
        Unicode(1000),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.sysutcdatetime(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.sysutcdatetime(),
    )
