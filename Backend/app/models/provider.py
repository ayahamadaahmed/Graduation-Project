"""SQLAlchemy mappings for the existing MedMind_Booking_DB tables."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    String,
    Unicode,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Provider(Base):
    """A healthcare organisation (tenant)."""

    __tablename__ = "providers"

    __table_args__ = (
        UniqueConstraint("slug", name="UQ_providers_slug"),
        UniqueConstraint("tenant_key", name="UQ_providers_tenant_key"),
        CheckConstraint("default_language='en' OR default_language='ar'", name="CK_providers_default_language"),
        CheckConstraint((
            "org_type='pharmacy' "
            "OR org_type='diagnostic_lab' "
            "OR org_type='hospital' "
            "OR org_type='clinic'"
        ), name="CK_providers_org_type"),
        CheckConstraint((
            "verification_status='rejected' "
            "OR verification_status='pending' "
            "OR verification_status='verified'"
        ), name="CK_providers_verification_status"),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        primary_key=True,
        server_default=func.newid(),
    )
    tenant_key: Mapped[str] = mapped_column(
        String(100),
    )
    name: Mapped[str] = mapped_column(
        Unicode(200),
    )
    slug: Mapped[str] = mapped_column(
        String(150),
    )
    org_type: Mapped[str] = mapped_column(
        String(30),
        server_default=text("'clinic'"),
    )
    verification_status: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'pending'"),
    )
    default_language: Mapped[str] = mapped_column(
        String(5),
        server_default=text("'ar'"),
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        server_default=text("'Africa/Cairo'"),
    )
    currency_code: Mapped[str] = mapped_column(
        String(3),
        server_default=text("'EGP'"),
    )
    phone: Mapped[str | None] = mapped_column(
        String(30),
    )
    email: Mapped[str | None] = mapped_column(
        String(254),
    )
    address: Mapped[str | None] = mapped_column(
        Unicode(500),
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
