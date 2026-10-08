from __future__ import annotations

from uuid import UUID

from app.models.radiology_report import (
    RadiologyReport,
)

from app.schemas.radiology_persistence import (
    RadiologyPersistenceRequest,
)

from app.services.diagnostic_attachment_service import (
    DiagnosticAttachmentService,
)

from app.services.radiology_persistence_service import (
    RadiologyAssessmentPersistenceInput,
    RadiologyPersistenceService,
)


class RadiologyPersistenceAdapterError(
    RuntimeError
):
    pass


class DuplicateRadiologyPersistenceError(
    RadiologyPersistenceAdapterError
):
    pass


class RadiologyPersistenceAdapter:

    def __init__(
        self,
        *,
        attachment_service:
            DiagnosticAttachmentService,
        radiology_persistence_service:
            RadiologyPersistenceService,
    ) -> None:

        self.attachment_service = (
            attachment_service
        )

        self.radiology_persistence_service = (
            radiology_persistence_service
        )

    def persist(
        self,
        *,
        provider_id: UUID,
        request: RadiologyPersistenceRequest,
    ) -> RadiologyReport:

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
        # radiology_reports has a UNIQUE constraint on
        # diagnostic_attachment_id.
        # ====================================================

        existing = (
            self.radiology_persistence_service
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
                DuplicateRadiologyPersistenceError(
                    "A radiology report already exists "
                    "for this diagnostic attachment."
                )
            )

        # ====================================================
        # 3. Convert validated API contract into the internal
        #    RadiologyPersistenceService input contract.
        #
        # No classification calculation.
        # No probability recalculation.
        # No diagnosis.
        # ====================================================

        assessment = (
            RadiologyAssessmentPersistenceInput(
                classification=(
                    request.classification
                ),
                probabilities=(
                    request.probabilities
                ),
                confidence=(
                    request.confidence
                ),
                inference_latency_ms=(
                    request
                    .inference_latency_ms
                ),
                model_name=(
                    request.model_name
                ),
                model_version=(
                    request.model_version
                ),
                limitations=(
                    request.limitations
                ),
            )
        )

        # ====================================================
        # 4. Persist using identity already bound to the
        #    attachment.
        #
        # Caller cannot inject:
        # - provider_id
        # - patient_id
        # - encounter_id
        # ====================================================

        return (
            self.radiology_persistence_service
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
                modality=(
                    request.modality
                ),
                assessment=assessment,
            )
        )