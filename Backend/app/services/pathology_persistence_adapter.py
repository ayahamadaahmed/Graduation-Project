from __future__ import annotations

from uuid import UUID

from app.models.lab_report import (
    LabReport,
)

from app.schemas.pathology_persistence import (
    PathologyPersistenceRequest,
)

from app.services.diagnostic_attachment_service import (
    DiagnosticAttachmentService,
)

from app.services.lab_persistence_service import (
    LabPersistenceService,
    LabResultPersistenceInput,
)


class PathologyPersistenceAdapterError(
    RuntimeError
):
    pass


class DuplicatePathologyPersistenceError(
    PathologyPersistenceAdapterError
):
    pass


class PathologyPersistenceAdapter:

    def __init__(
        self,
        *,
        attachment_service:
            DiagnosticAttachmentService,
        lab_persistence_service:
            LabPersistenceService,
    ) -> None:

        self.attachment_service = (
            attachment_service
        )

        self.lab_persistence_service = (
            lab_persistence_service
        )

    def persist(
        self,
        *,
        provider_id: UUID,
        request: PathologyPersistenceRequest,
    ) -> LabReport:

        # ====================================================
        # 1. Resolve tenant-scoped attachment
        # ====================================================

        attachment = (
            self.attachment_service.get(
                provider_id=provider_id,
                attachment_id=(
                    request.attachment_id
                ),
            )
        )

        # ====================================================
        # 2. Idempotency / duplicate protection
        #
        # lab_reports has a UNIQUE constraint on
        # diagnostic_attachment_id. Detect it before insert
        # so retries do not become a DB integrity failure.
        # ====================================================

        existing = (
            self.lab_persistence_service
            .repository
            .get_report_by_attachment(
                provider_id=provider_id,
                diagnostic_attachment_id=(
                    attachment.id
                ),
            )
        )

        if existing is not None:
            raise (
                DuplicatePathologyPersistenceError(
                    "A lab report already exists "
                    "for this diagnostic attachment."
                )
            )

        # ====================================================
        # 3. Convert validated API contract into the internal
        #    LabPersistenceService input contract.
        #
        # No normalization.
        # No flag calculation.
        # No medical interpretation.
        # ====================================================

        results = [
            LabResultPersistenceInput(
                result_index=(
                    item.result_index
                ),
                panel=item.panel,
                raw_name=item.raw_name,
                canonical_name=(
                    item.canonical_name
                ),
                value=item.value,
                unit=item.unit,
                reference_min=(
                    item.reference_min
                ),
                reference_max=(
                    item.reference_max
                ),
                reference_text=(
                    item.reference_text
                ),
                flag=item.flag,
                mapping_status=(
                    item.mapping_status
                ),
            )
            for item in request.results
        ]

        # ====================================================
        # 4. Persist using identity already bound to the
        #    attachment.
        #
        # Caller cannot inject patient_id / encounter_id.
        # ====================================================

        return (
            self.lab_persistence_service
            .save_processed_report(
                provider_id=provider_id,
                diagnostic_attachment_id=(
                    attachment.id
                ),
                patient_id=(
                    attachment.patient_id
                ),
                encounter_id=(
                    attachment.encounter_id
                ),
                document_type=(
                    request.document_type
                ),
                unreadable_fields=(
                    request.unreadable_fields
                ),
                results=results,
            )
        )