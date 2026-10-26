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


class UserAccount(Base):
    """A staff login account."""

    __tablename__ = "user_accounts"

    __table_args__ = (
        UniqueConstraint("email", name="uq_user_accounts_email"),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        primary_key=True,
        server_default=func.newid(),
    )
    email: Mapped[str] = mapped_column(
        String(254),
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=text("TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00')"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=text("TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00')"),
    )


class ProviderMembership(Base):
    """A staff user's role within a provider."""

    __tablename__ = "provider_memberships"

    __table_args__ = (
        UniqueConstraint("user_id", "provider_id", name="uq_provider_memberships_user_provider"),
        CheckConstraint((
            "role='doctor' "
            'AND doctor_id IS NOT NULL '
            "OR role<>'doctor' "
            'AND doctor_id IS NULL'
        ), name="ck_provider_memberships_doctor_role"),
        CheckConstraint((
            "role='lab_staff' "
            "OR role='receptionist' "
            "OR role='doctor' "
            "OR role='provider_admin'"
        ), name="ck_provider_memberships_role"),
        Index("ix_provider_memberships_provider", "provider_id", "is_active"),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        primary_key=True,
        server_default=func.newid(),
    )
    user_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("user_accounts.id", name="fk_provider_memberships_user_account"),
    )
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("providers.id", name="fk_provider_memberships_provider"),
    )
    role: Mapped[str] = mapped_column(
        String(30),
    )
    doctor_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("doctors.id", name="fk_provider_memberships_doctor"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=text("TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00')"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=text("TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00')"),
    )
