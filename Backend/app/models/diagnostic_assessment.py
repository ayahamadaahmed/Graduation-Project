"""SQLAlchemy mappings for the existing MedMind_Booking_DB tables."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Unicode,
    UnicodeText,
    func,
    text,
)
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DiagnosticAssessment(Base):
    """A model assessment attached to a radiology report."""

    __tablename__ = "diagnostic_assessments"

    __table_args__ = (
        CheckConstraint('confidence>=(0) AND confidence<=(1)', name="CK_diagnostic_assessments_confidence"),
        CheckConstraint('inference_latency_ms>=(0)', name="CK_diagnostic_assessments_latency"),
        Index("IX_diagnostic_assessments_model", "model_name", "model_version"),
        Index("IX_diagnostic_assessments_report_created", "radiology_report_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        primary_key=True,
        server_default=func.newid(),
    )
    radiology_report_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("radiology_reports.id", name="FK_diagnostic_assessments_radiology_report"),
    )
    assessment_type: Mapped[str] = mapped_column(
        String(30),
        server_default=text("'radiology_model'"),
    )
    classification: Mapped[str] = mapped_column(
        String(100),
    )
    probabilities_json: Mapped[str] = mapped_column(
        UnicodeText(),
    )
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(9, 8),
    )
    inference_latency_ms: Mapped[Decimal] = mapped_column(
        Numeric(12, 3),
    )
    model_name: Mapped[str] = mapped_column(
        Unicode(150),
    )
    model_version: Mapped[str] = mapped_column(
        Unicode(100),
    )
    limitations_json: Mapped[str] = mapped_column(
        UnicodeText(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
