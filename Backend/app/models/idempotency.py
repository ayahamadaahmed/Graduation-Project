"""SQLAlchemy mappings for the existing MedMind_Booking_DB tables."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Index,
    String,
    UnicodeText,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mssql import DATETIMEOFFSET
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IdempotencyRequest(Base):
    """Stored result of an idempotent write request."""

    __tablename__ = "idempotency_requests"

    __table_args__ = (
        UniqueConstraint("tenant_id", "operation", "idempotency_key", name="uq_idempotency_tenant_operation_key"),
        Index("ix_idempotency_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(100),
    )
    operation: Mapped[str] = mapped_column(
        String(50),
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(128),
    )
    request_hash: Mapped[str] = mapped_column(
        String(64),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'pending'"),
    )
    response_body: Mapped[str | None] = mapped_column(
        UnicodeText(),
    )
    error_code: Mapped[str | None] = mapped_column(
        String(100),
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=text("TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00')"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DATETIMEOFFSET,
    )
