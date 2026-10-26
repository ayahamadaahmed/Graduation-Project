"""SQLAlchemy mappings for the existing MedMind_Booking_DB tables."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    SmallInteger,
    func,
    text,
)
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BranchMRNSequence(Base):
    """Per-branch, per-year medical record number counter."""

    __tablename__ = "branch_mrn_sequences"

    __table_args__ = (
        CheckConstraint('last_number>=(0) AND last_number<=(999)', name="CK_branch_mrn_sequences_number"),
    )

    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("providers.id", name="FK_branch_mrn_sequences_provider"),
        primary_key=True,
    )
    branch_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("branches.id", name="FK_branch_mrn_sequences_branch"),
        primary_key=True,
    )
    sequence_year: Mapped[int] = mapped_column(
        SmallInteger,
        primary_key=True,
    )
    last_number: Mapped[int] = mapped_column(
        Integer,
        server_default=text("0"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )


class PatientNumberSequence(Base):
    """Per-year patient code counter."""

    __tablename__ = "patient_number_sequences"

    year: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )
    last_number: Mapped[int] = mapped_column(
        Integer,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
