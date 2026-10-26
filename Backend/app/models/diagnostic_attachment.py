"""SQLAlchemy mappings for the existing MedMind_Booking_DB tables."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Unicode,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DiagnosticAttachment(Base):
    """An uploaded diagnostic file (metadata only; bytes live in storage)."""

    __tablename__ = "diagnostic_attachments"

    __table_args__ = (
        UniqueConstraint("attachment_id", name="UQ_diagnostic_attachments_attachment_id"),
        ForeignKeyConstraint(
            ["encounter_id", "provider_id", "patient_id"],
            ["ehr_encounters.id", "ehr_encounters.provider_id", "ehr_encounters.patient_id"],
            name="FK_diagnostic_attachments_encounter_provider_patient",
        ),
        Index("IX_diagnostic_attachments_patient_created", "patient_id", "created_at"),
        Index("IX_diagnostic_attachments_provider_session", "provider_id", "session_id"),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        primary_key=True,
        server_default=func.newid(),
    )
    attachment_id: Mapped[str] = mapped_column(
        String(32),
    )
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("providers.id", name="FK_diagnostic_attachments_provider"),
    )
    patient_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("patients.id", name="FK_diagnostic_attachments_patient"),
    )
    encounter_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("ehr_encounters.id", name="FK_diagnostic_attachments_encounter"),
    )
    session_id: Mapped[str] = mapped_column(
        String(128),
    )
    original_filename: Mapped[str] = mapped_column(
        Unicode(255),
    )
    content_type: Mapped[str] = mapped_column(
        String(100),
    )
    size_bytes: Mapped[int] = mapped_column(
        BigInteger,
    )
    sha256: Mapped[str] = mapped_column(
        String(64),
    )
    storage_key: Mapped[str] = mapped_column(
        Unicode(500),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'stored'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
