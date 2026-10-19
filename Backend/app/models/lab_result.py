"""SQLAlchemy mappings for the existing MedMind_Booking_DB tables."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Unicode,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LabResult(Base):
    """One analyte row of a lab report."""

    __tablename__ = "lab_results"

    __table_args__ = (
        UniqueConstraint("lab_report_id", "result_index", name="UQ_lab_results_report_index"),
        Index("IX_lab_results_canonical_name", "canonical_name"),
        Index("IX_lab_results_report", "lab_report_id"),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        primary_key=True,
        server_default=func.newid(),
    )
    lab_report_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("lab_reports.id", name="FK_lab_results_report"),
    )
    result_index: Mapped[int] = mapped_column(
        Integer,
    )
    panel: Mapped[str | None] = mapped_column(
        String(30),
    )
    raw_name: Mapped[str] = mapped_column(
        Unicode(200),
    )
    canonical_name: Mapped[str | None] = mapped_column(
        String(100),
    )
    value: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6),
    )
    unit: Mapped[str | None] = mapped_column(
        Unicode(50),
    )
    reference_min: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6),
    )
    reference_max: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6),
    )
    reference_text: Mapped[str | None] = mapped_column(
        Unicode(200),
    )
    flag: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'unknown'"),
    )
    mapping_status: Mapped[str] = mapped_column(
        String(20),
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
