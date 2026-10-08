from __future__ import annotations

import json

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.models.radiology_report import (
    RadiologyReport,
)

from app.repositories.radiology_repository import (
    RadiologyRepository,
)


# ============================================================
# CONSTANTS
# ============================================================

_SUPPORTED_RADIOLOGY_MODALITIES = {
    "chest_xray",
    "brain_mri",
    "kidney_ct",
}


# ============================================================
# INPUT CONTRACT
# ============================================================

@dataclass(
    frozen=True,
    slots=True,
)
class RadiologyAssessmentPersistenceInput:

    classification: str

    probabilities: dict[
        str,
        Decimal,
    ]

    confidence: Decimal

    inference_latency_ms: Decimal

    model_name: str

    model_version: str

    limitations: list[str]


# ============================================================
# ERRORS
# ============================================================

class RadiologyPersistenceError(
    RuntimeError
):
    pass


# ============================================================
# SERVICE
# ============================================================

class RadiologyPersistenceService:

    def __init__(
        self,
        repository: RadiologyRepository,
    ) -> None:

        self.repository = repository

    # ========================================================
    # SAVE PROCESSED RADIOLOGY REPORT
    # ========================================================

    def save_processed_report(
        self,
        *,
        provider_id: UUID,
        diagnostic_attachment_id: UUID,
        modality: str,
        assessment: RadiologyAssessmentPersistenceInput,
        patient_id: UUID | None = None,
        encounter_id: UUID | None = None,
    ) -> RadiologyReport:

        # ----------------------------------------------------
        # Validation before touching DB.
        # ----------------------------------------------------

        normalized_modality = (
            modality.strip().lower()
        )

        if (
            normalized_modality
            not in _SUPPORTED_RADIOLOGY_MODALITIES
        ):
            raise RadiologyPersistenceError(
                "Unsupported radiology modality."
            )

        classification = (
            assessment.classification.strip()
        )

        if not classification:
            raise RadiologyPersistenceError(
                "classification cannot be empty."
            )

        if not assessment.probabilities:
            raise RadiologyPersistenceError(
                "Radiology probabilities cannot be empty."
            )

        normalized_probabilities: dict[
            str,
            Decimal,
        ] = {}

        for raw_name, probability in (
            assessment.probabilities.items()
        ):

            name = str(
                raw_name
            ).strip()

            if not name:
                raise RadiologyPersistenceError(
                    "Probability class name cannot be empty."
                )

            if not probability.is_finite():
                raise RadiologyPersistenceError(
                    "Probability must be finite."
                )

            if (
                probability < 0
                or probability > 1
            ):
                raise RadiologyPersistenceError(
                    "Probability must be between 0 and 1."
                )

            normalized_probabilities[
                name
            ] = probability

        if (
            classification
            not in normalized_probabilities
        ):
            raise RadiologyPersistenceError(
                "classification must exist in probabilities."
            )

        if not assessment.confidence.is_finite():
            raise RadiologyPersistenceError(
                "confidence must be finite."
            )

        if (
            assessment.confidence < 0
            or assessment.confidence > 1
        ):
            raise RadiologyPersistenceError(
                "confidence must be between 0 and 1."
            )

        if (
            not assessment
            .inference_latency_ms
            .is_finite()
        ):
            raise RadiologyPersistenceError(
                "inference_latency_ms must be finite."
            )

        if (
            assessment.inference_latency_ms
            < 0
        ):
            raise RadiologyPersistenceError(
                "inference_latency_ms cannot be negative."
            )

        model_name = (
            assessment.model_name.strip()
        )

        if not model_name:
            raise RadiologyPersistenceError(
                "model_name cannot be empty."
            )

        model_version = (
            assessment.model_version.strip()
        )

        if not model_version:
            raise RadiologyPersistenceError(
                "model_version cannot be empty."
            )

        if not all(
            isinstance(
                limitation,
                str,
            )
            for limitation
            in assessment.limitations
        ):
            raise RadiologyPersistenceError(
                "Every limitation must be a string."
            )

        # ----------------------------------------------------
        # Serialize trusted model output.
        #
        # No probability recalculation.
        # No classification reinterpretation.
        # ----------------------------------------------------

        probabilities_json = json.dumps(
            {
                name: float(
                    probability
                )
                for name, probability
                in normalized_probabilities.items()
            },
            ensure_ascii=False,
        )

        limitations_json = json.dumps(
            assessment.limitations,
            ensure_ascii=False,
        )

        # ----------------------------------------------------
        # One DB transaction:
        #
        # radiology report
        # + model assessment
        # + final report status
        # ----------------------------------------------------

        try:

            report = (
                self.repository
                .create_report(
                    provider_id=provider_id,
                    diagnostic_attachment_id=(
                        diagnostic_attachment_id
                    ),
                    patient_id=patient_id,
                    encounter_id=encounter_id,
                    modality=(
                        normalized_modality
                    ),
                    status="processing",
                )
            )

            self.repository.create_assessment(
                radiology_report_id=report.id,
                classification=(
                    classification
                ),
                probabilities_json=(
                    probabilities_json
                ),
                confidence=(
                    assessment.confidence
                ),
                inference_latency_ms=(
                    assessment.inference_latency_ms
                ),
                model_name=model_name,
                model_version=model_version,
                limitations_json=(
                    limitations_json
                ),
                assessment_type=(
                    "radiology_model"
                ),
            )

            self.repository.set_report_status(
                report=report,
                status="processed",
            )

            self.repository.session.commit()

        except Exception as exc:

            self.repository.session.rollback()

            raise RadiologyPersistenceError(
                "Failed to persist processed "
                "radiology report."
            ) from exc

        return report