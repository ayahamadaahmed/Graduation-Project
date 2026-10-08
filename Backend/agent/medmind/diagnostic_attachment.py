from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(
    frozen=True,
    slots=True,
)
class TrustedDiagnosticAttachment:
    attachment_id: str

    provider_id: UUID

    session_id: str

    original_filename: str

    content_type: str

    data: bytes

    patient_id: UUID | None = None

    encounter_id: UUID | None = None