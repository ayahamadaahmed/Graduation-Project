from __future__ import annotations

import hashlib

from pathlib import Path
from uuid import UUID, uuid4

from app.models.diagnostic_attachment import (
    DiagnosticAttachment,
)

from app.repositories.diagnostic_attachment_repository import (
    DiagnosticAttachmentRepository,
)


# ============================================================
# CONSTANTS
# ============================================================

_ALLOWED_CONTENT_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "application/pdf",
    }
)


# ============================================================
# ERRORS
# ============================================================

class DiagnosticAttachmentError(
    RuntimeError
):
    pass


class InvalidDiagnosticAttachmentError(
    DiagnosticAttachmentError
):
    pass


class UnsupportedDiagnosticFileTypeError(
    DiagnosticAttachmentError
):
    pass


class DiagnosticFileTooLargeError(
    DiagnosticAttachmentError
):
    pass


class DiagnosticAttachmentNotFoundError(
    DiagnosticAttachmentError
):
    pass


# ============================================================
# SERVICE
# ============================================================

class DiagnosticAttachmentService:

    def __init__(
        self,
        *,
        repository: DiagnosticAttachmentRepository,
        storage_dir: Path,
        max_upload_bytes: int,
    ) -> None:

        if max_upload_bytes <= 0:
            raise ValueError(
                "max_upload_bytes must be greater than zero."
            )

        self.repository = repository

        self.storage_dir = Path(
            storage_dir
        )

        self.max_upload_bytes = (
            max_upload_bytes
        )

    # ========================================================
    # STORE
    # ========================================================

    def store(
        self,
        *,
        provider_id: UUID,
        session_id: str,
        original_filename: str,
        content_type: str,
        data: bytes,
        patient_id: UUID | None = None,
        encounter_id: UUID | None = None,
    ) -> DiagnosticAttachment:

        session_id = (
            session_id.strip()
        )

        original_filename = (
            Path(
                original_filename.strip()
            )
            .name
        )

        declared_content_type = (
            content_type
            .split(
                ";",
                maxsplit=1,
            )[0]
            .strip()
            .lower()
        )

        # ----------------------------------------------------
        # Validation
        # ----------------------------------------------------

        if not session_id:
            raise InvalidDiagnosticAttachmentError(
                "session_id cannot be empty."
            )

        if len(session_id) > 128:
            raise InvalidDiagnosticAttachmentError(
                "session_id exceeds the allowed length."
            )

        if not original_filename:
            raise InvalidDiagnosticAttachmentError(
                "original_filename cannot be empty."
            )

        if len(original_filename) > 255:
            raise InvalidDiagnosticAttachmentError(
                "original_filename exceeds the allowed length."
            )

        if not data:
            raise InvalidDiagnosticAttachmentError(
                "Diagnostic attachment cannot be empty."
            )

        if len(data) > self.max_upload_bytes:
            raise DiagnosticFileTooLargeError(
                "Diagnostic attachment exceeds "
                "the configured size limit."
            )

        if (
            declared_content_type
            not in _ALLOWED_CONTENT_TYPES
        ):
            raise UnsupportedDiagnosticFileTypeError(
                "Only JPEG, PNG, and PDF diagnostic files "
                "are currently supported."
            )

        # ----------------------------------------------------
        # Verify real content type.
        # ----------------------------------------------------

        detected_content_type = self._detect_content_type(data)

        if detected_content_type is None:
            raise UnsupportedDiagnosticFileTypeError(
                "Uploaded content is not a supported JPEG, PNG, or PDF file."
            )

        if (
            detected_content_type
            != declared_content_type
        ):
            raise InvalidDiagnosticAttachmentError(
                "Declared content type does not match "
                "the uploaded file content."
            )

        # ----------------------------------------------------
        # Canonical extension
        # ----------------------------------------------------

        extension = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "application/pdf": ".pdf",
        }[detected_content_type]

        # ----------------------------------------------------
        # Attachment identity
        # ----------------------------------------------------

        attachment_id = (
            uuid4().hex
        )

        stored_filename = (
            f"{attachment_id}{extension}"
        )

        # Use immutable provider UUID instead of raw
        # tenant_key as the storage namespace.
        provider_storage_key = str(
            provider_id
        )

        storage_key = (
            f"{provider_storage_key}/"
            f"{stored_filename}"
        )

        provider_directory = (
            self.storage_dir
            / provider_storage_key
        )

        provider_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        file_path = (
            provider_directory
            / stored_filename
        )

        temporary_file_path = (
            provider_directory
            / f".{attachment_id}.upload.tmp"
        )

        digest = hashlib.sha256(
            data
        ).hexdigest()

        # ----------------------------------------------------
        # 1. Store file first.
        # ----------------------------------------------------

        try:

            temporary_file_path.write_bytes(
                data
            )

            temporary_file_path.replace(
                file_path
            )

        except Exception as exc:

            temporary_file_path.unlink(
                missing_ok=True
            )

            file_path.unlink(
                missing_ok=True
            )

            raise DiagnosticAttachmentError(
                "Failed to store diagnostic attachment."
            ) from exc

        # ----------------------------------------------------
        # 2. Create DB record.
        #
        # Repository only add/flushes.
        # Service owns commit/rollback.
        # ----------------------------------------------------

        try:

            attachment = (
                self.repository.create(
                    attachment_id=attachment_id,
                    provider_id=provider_id,
                    patient_id=patient_id,
                    encounter_id=encounter_id,
                    session_id=session_id,
                    original_filename=(
                        original_filename
                    ),
                    content_type=(
                        detected_content_type
                    ),
                    size_bytes=len(
                        data
                    ),
                    sha256=digest,
                    storage_key=storage_key,
                    status="stored",
                )
            )

            self.repository.session.commit()

        except Exception as exc:

            self.repository.session.rollback()

            # DB failed, so remove the file.
            # This prevents orphaned storage objects.
            file_path.unlink(
                missing_ok=True
            )

            temporary_file_path.unlink(
                missing_ok=True
            )

            raise DiagnosticAttachmentError(
                "Failed to persist diagnostic "
                "attachment metadata."
            ) from exc

        return attachment

    # ========================================================
    # GET
    # ========================================================

    def get(
        self,
        *,
        provider_id: UUID,
        attachment_id: str,
    ) -> DiagnosticAttachment:

        attachment_id = (
            attachment_id.strip()
        )

        if not self._valid_attachment_id(
            attachment_id
        ):
            raise InvalidDiagnosticAttachmentError(
                "Invalid attachment_id."
            )

        attachment = (
            self.repository
            .get_by_attachment_id(
                provider_id=provider_id,
                attachment_id=attachment_id,
            )
        )

        if attachment is None:
            raise DiagnosticAttachmentNotFoundError(
                "Diagnostic attachment was not found."
            )

        return attachment

    # ========================================================
    # RESOLVE TRUSTED PATH
    # ========================================================

    def resolve_path(
        self,
        *,
        provider_id: UUID,
        attachment_id: str,
    ) -> Path:

        attachment = self.get(
            provider_id=provider_id,
            attachment_id=attachment_id,
        )

        provider_directory = (
            self.storage_dir
            / str(provider_id)
        ).resolve()

        candidate_path = (
            self.storage_dir
            / Path(
                attachment.storage_key
            )
        ).resolve()

        # ----------------------------------------------------
        # DB metadata must never escape provider storage.
        # ----------------------------------------------------

        if (
            candidate_path.parent
            != provider_directory
        ):
            raise DiagnosticAttachmentError(
                "Invalid diagnostic attachment "
                "storage location."
            )

        if not candidate_path.is_file():
            raise DiagnosticAttachmentNotFoundError(
                "Diagnostic attachment file was not found."
            )

        return candidate_path

    # ========================================================
    # REMOVE STORED FILE
    # ========================================================

    def remove_file(
        self,
        *,
        provider_id: UUID,
        attachment_id: str,
    ) -> None:

        attachment = self.get(
            provider_id=provider_id,
            attachment_id=attachment_id,
        )

        provider_directory = (
            self.storage_dir
            / str(provider_id)
        ).resolve()

        candidate_path = (
            self.storage_dir
            / Path(
                attachment.storage_key
            )
        ).resolve()

        if (
            candidate_path.parent
            != provider_directory
        ):
            raise DiagnosticAttachmentError(
                "Invalid diagnostic attachment "
                "storage location."
            )

        candidate_path.unlink(
            missing_ok=True
        )

    # ========================================================
    # FILE SIGNATURE
    # ========================================================

    @staticmethod
    def _detect_image_content_type(
        data: bytes,
    ) -> str | None:

        if data.startswith(
            b"\x89PNG\r\n\x1a\n"
        ):
            return "image/png"

        if (
            len(data) >= 3
            and data[:3]
            == b"\xff\xd8\xff"
        ):
            return "image/jpeg"

        return None

    @staticmethod
    def _detect_content_type(data: bytes) -> str | None:
        image_type = DiagnosticAttachmentService._detect_image_content_type(data)
        if image_type:
            return image_type
        if data.startswith(b"%PDF-"):
            return "application/pdf"
        return None

    # ========================================================
    # ATTACHMENT ID
    # ========================================================

    @staticmethod
    def _valid_attachment_id(
        value: str,
    ) -> bool:

        if len(value) != 32:
            return False

        try:
            int(
                value,
                16,
            )

        except ValueError:
            return False

        return True
