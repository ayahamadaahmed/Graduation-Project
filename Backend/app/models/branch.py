"""SQLAlchemy mappings for the existing MedMind_Booking_DB tables."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Unicode,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Branch(Base):
    """A physical branch of a provider."""

    __tablename__ = "branches"

    __table_args__ = (
        UniqueConstraint("provider_id", "code", name="UQ_branches_provider_code"),
        # Lets child tables prove they use a branch of the same provider (composite foreign keys).
        UniqueConstraint("id", "provider_id", name="UQ_branches_id_provider"),
        CheckConstraint('latitude>=(-90) AND latitude<=(90) OR latitude IS NULL', name="CK_branches_latitude"),
        CheckConstraint('longitude>=(-180) AND longitude<=(180) OR longitude IS NULL', name="CK_branches_longitude"),
        Index("IX_branches_provider_active", "provider_id", "is_active"),
        Index("UX_branches_provider_mrn_code", "provider_id", "mrn_code", unique=True, mssql_where=text("mrn_code IS NOT NULL")),
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
        Unicode(200),
    )
    name_en: Mapped[str] = mapped_column(
        Unicode(200),
    )
    address_ar: Mapped[str | None] = mapped_column(
        Unicode(500),
    )
    address_en: Mapped[str | None] = mapped_column(
        Unicode(500),
    )
    governorate: Mapped[str | None] = mapped_column(
        Unicode(100),
    )
    latitude: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6),
    )
    longitude: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6),
    )
    phone: Mapped[str | None] = mapped_column(
        String(30),
    )
    whatsapp: Mapped[str | None] = mapped_column(
        String(30),
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        server_default=text("'Africa/Cairo'"),
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
    mrn_code: Mapped[str | None] = mapped_column(
        CHAR(3),
    )
