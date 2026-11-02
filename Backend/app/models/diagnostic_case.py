"""Persisted diagnostic chat case and its structured clinical summary."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, Unicode, UniqueConstraint, func, text
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DiagnosticCase(Base):
    __tablename__ = "diagnostic_cases"
    __table_args__ = (
        UniqueConstraint("provider_id", "session_id", name="UQ_diagnostic_cases_provider_session"),
        Index("IX_diagnostic_cases_patient_created", "patient_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, server_default=func.newid())
    provider_id: Mapped[UUID] = mapped_column(UNIQUEIDENTIFIER, ForeignKey("providers.id", name="FK_diagnostic_cases_provider"))
    patient_id: Mapped[UUID | None] = mapped_column(UNIQUEIDENTIFIER, ForeignKey("patients.id", name="FK_diagnostic_cases_patient"))
    encounter_id: Mapped[UUID | None] = mapped_column(UNIQUEIDENTIFIER, ForeignKey("ehr_encounters.id", name="FK_diagnostic_cases_encounter"))
    session_id: Mapped[str] = mapped_column(String(128))
    complaint: Mapped[str] = mapped_column(Unicode(4000), default="", server_default=text("''"))
    answers_json: Mapped[str] = mapped_column(Unicode, default="{}", server_default=text("'{}'"))
    summary_json: Mapped[str | None] = mapped_column(Unicode)
    status: Mapped[str] = mapped_column(String(20), default="in_progress", server_default=text("'in_progress'"))
    created_at: Mapped[datetime] = mapped_column(DATETIMEOFFSET, server_default=func.sysutcdatetime())
    updated_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
        onupdate=func.sysutcdatetime(),
    )
