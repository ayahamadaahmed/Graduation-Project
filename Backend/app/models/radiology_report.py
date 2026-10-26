"""SQLAlchemy mappings for the existing MedMind_Booking_DB tables."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RadiologyReport(Base):
    """A persisted radiology report for an attachment."""

    __tablename__ = "radiology_reports"

    __table_args__ = (
        UniqueConstraint("diagnostic_attachment_id", name="UQ_radiology_reports_diagnostic_attachment"),
        ForeignKeyConstraint(
            ["encounter_id", "provider_id", "patient_id"],
            ["ehr_encounters.id", "ehr_encounters.provider_id", "ehr_encounters.patient_id"],
            name="FK_radiology_reports_encounter_provider_patient",
        ),
        Index("IX_radiology_reports_patient_created", "patient_id", "created_at"),
        Index("IX_radiology_reports_provider_created", "provider_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        primary_key=True,
        server_default=func.newid(),
    )
    patient_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("patients.id", name="FK_radiology_reports_patient"),
    )
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("providers.id", name="FK_radiology_reports_provider"),
    )
    encounter_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("ehr_encounters.id", name="FK_radiology_reports_encounter"),
    )
    diagnostic_attachment_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("diagnostic_attachments.id", name="FK_radiology_reports_diagnostic_attachment"),
    )
    modality: Mapped[str] = mapped_column(
        String(30),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'pending'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
