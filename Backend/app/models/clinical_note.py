"""SQLAlchemy mapping for clinical notes written by doctors."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Unicode,
    UnicodeText,
    func,
    text,
)
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ClinicalNote(Base):
    """A note written by a doctor about one encounter.

    Signed notes are immutable: the database trigger
    ``TR_clinical_notes_protect_signed`` rejects any change or delete.
    Corrections are new notes of type ``addendum`` pointing at the original
    through ``addendum_to_note_id``.
    """

    __tablename__ = "clinical_notes"

    __table_args__ = (
        ForeignKeyConstraint(
            ["patient_id", "provider_id"],
            ["patient_provider_profiles.patient_id", "patient_provider_profiles.provider_id"],
            name="FK_clinical_notes_profile",
        ),
        ForeignKeyConstraint(
            ["encounter_id", "provider_id", "patient_id"],
            ["ehr_encounters.id", "ehr_encounters.provider_id", "ehr_encounters.patient_id"],
            name="FK_clinical_notes_encounter",
        ),
        ForeignKeyConstraint(
            ["doctor_id", "provider_id"],
            ["doctors.id", "doctors.provider_id"],
            name="FK_clinical_notes_doctor",
        ),
        CheckConstraint(
            "note_type IN ('progress','consultation','soap','discharge','addendum')",
            name="CK_clinical_notes_type",
        ),
        CheckConstraint(
            "status IN ('draft','signed')",
            name="CK_clinical_notes_status",
        ),
        CheckConstraint(
            "(status = 'signed' AND signed_at IS NOT NULL) OR (status = 'draft' AND signed_at IS NULL)",
            name="CK_clinical_notes_signed",
        ),
        CheckConstraint(
            "note_type <> 'addendum' OR addendum_to_note_id IS NOT NULL",
            name="CK_clinical_notes_addendum",
        ),
        # The database index is created as (provider_id, patient_id, created_at DESC).
        # Sort order is not tracked by Alembic, so the plain column list is declared here.
        Index("IX_clinical_notes_patient", "provider_id", "patient_id", "created_at"),
        Index("IX_clinical_notes_encounter", "encounter_id"),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        primary_key=True,
        server_default=func.newid(),
    )
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
    )
    patient_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
    )
    # Every note belongs to a visit.
    encounter_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
    )
    # The author.
    doctor_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
    )
    # progress / consultation / soap / discharge / addendum
    note_type: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'progress'"),
    )
    title: Mapped[str | None] = mapped_column(
        Unicode(200),
    )
    note_text: Mapped[str] = mapped_column(
        UnicodeText,
    )
    # draft / signed
    status: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'draft'"),
    )
    signed_at: Mapped[datetime | None] = mapped_column(
        DATETIMEOFFSET,
    )
    addendum_to_note_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("clinical_notes.id", name="FK_clinical_notes_addendum"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
