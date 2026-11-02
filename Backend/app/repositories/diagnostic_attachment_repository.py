from __future__ import annotations

from uuid import (
    UUID,
    uuid4,
)

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.diagnostic_attachment import (
    DiagnosticAttachment,
)


class DiagnosticAttachmentRepository:

    def __init__(
        self,
        session: Session,
    ) -> None:

        self.session = session

    # ========================================================
    # CREATE
    # ========================================================

    def create(
        self,
        *,
        attachment_id: str,
        provider_id: UUID,
        session_id: str,
        original_filename: str,
        content_type: str,
        size_bytes: int,
        sha256: str,
        storage_key: str,
        patient_id: UUID | None = None,
        encounter_id: UUID | None = None,
        status: str = "stored",
    ) -> DiagnosticAttachment:

        attachment = DiagnosticAttachment(
            id=uuid4(),
            attachment_id=attachment_id,
            provider_id=provider_id,
            patient_id=patient_id,
            encounter_id=encounter_id,
            session_id=session_id,
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
            storage_key=storage_key,
            status=status,
        )

        self.session.add(
            attachment
        )

        self.session.flush()

        return attachment

    # ========================================================
    # TENANT-SCOPED LOOKUP
    # ========================================================

    def get_by_attachment_id(
        self,
        *,
        provider_id: UUID,
        attachment_id: str,
    ) -> DiagnosticAttachment | None:

        statement = (
            select(
                DiagnosticAttachment
            )
            .where(
                DiagnosticAttachment.provider_id
                == provider_id,

                DiagnosticAttachment.attachment_id
                == attachment_id,
            )
        )

        return self.session.scalar(
            statement
        )

    def get_by_sha256(
        self,
        *,
        provider_id: UUID,
        patient_id: UUID | None,
        session_id: str,
        sha256: str,
    ) -> DiagnosticAttachment | None:
        """Find an identical upload within its authorized chat scope."""
        statement = select(DiagnosticAttachment).where(
            DiagnosticAttachment.provider_id == provider_id,
            DiagnosticAttachment.patient_id == patient_id,
            DiagnosticAttachment.sha256 == sha256,
        )
        if patient_id is None:
            statement = statement.where(DiagnosticAttachment.session_id == session_id)
        statement = statement.limit(1)
        return self.session.scalar(statement)

    # ========================================================
    # BIND TO PATIENT
    # ========================================================

    def bind_to_patient(
        self,
        *,
        attachment: DiagnosticAttachment,
        patient_id: UUID,
    ) -> DiagnosticAttachment:

        attachment.patient_id = (
            patient_id
        )

        self.session.flush()

        return attachment

    # ========================================================
    # BIND TO EHR ENCOUNTER
    # ========================================================

    def bind_to_encounter(
        self,
        *,
        attachment: DiagnosticAttachment,
        encounter_id: UUID,
    ) -> DiagnosticAttachment:

        attachment.encounter_id = (
            encounter_id
        )

        self.session.flush()

        return attachment

    # ========================================================
    # DELETE
    # ========================================================

    def delete(
        self,
        attachment: DiagnosticAttachment,
    ) -> None:

        self.session.delete(
            attachment
        )

        self.session.flush()
