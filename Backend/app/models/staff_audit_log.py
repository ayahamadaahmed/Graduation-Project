"""SQLAlchemy mappings for the existing MedMind_Booking_DB tables."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StaffAuditLog(Base):
    """Privacy-safe audit log of staff actions (no PII, no foreign keys)."""

    __tablename__ = "staff_audit_logs"

    __table_args__ = (
        CheckConstraint((
            "outcome='error' "
            "OR outcome='denied' "
            "OR outcome='not_found' "
            "OR outcome='success'"
        ), name="ck_staff_audit_logs_outcome"),
        Index("ix_staff_audit_logs_patient_created", "patient_id", "created_at"),
        Index("ix_staff_audit_logs_provider_created", "provider_id", "created_at"),
        Index("ix_staff_audit_logs_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        primary_key=True,
        server_default=func.newid(),
    )
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
    )
    user_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
    )
    membership_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
    )
    patient_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
    )
    action: Mapped[str] = mapped_column(
        String(100),
    )
    resource_type: Mapped[str] = mapped_column(
        String(50),
    )
    resource_id: Mapped[str | None] = mapped_column(
        String(100),
    )
    outcome: Mapped[str] = mapped_column(
        String(30),
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=text("TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00')"),
    )
