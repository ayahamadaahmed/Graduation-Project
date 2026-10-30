from __future__ import annotations

from dataclasses import dataclass

from .radiology_processor import (
    RadiologyModality,
    RadiologyProcessorResult,
)


@dataclass(frozen=True, slots=True)
class RadiologyAssessment:
    """
    Unified deterministic assessment produced from one
    modality-specific radiology model result.

    No diagnosis.
    No LLM interpretation.
    """

    modality: RadiologyModality

    classification: str
    probabilities: dict[str, float]
    confidence: float

    inference_latency_ms: float

    model_name: str
    model_version: str

    limitations: tuple[str, ...]


class RadiologyAssessmentError(RuntimeError):
    """Raised when a radiology processor result is inconsistent."""


class RadiologyAssessmentBuilder:
    """
    Converts heterogeneous radiology model outputs into
    one stable MedMind radiology schema.

    Responsibilities:
    - preserve the routed modality
    - normalize classification to a string
    - preserve all class probabilities
    - preserve confidence and latency
    - preserve model metadata and limitations

    This builder does NOT:
    - infer a diagnosis
    - reinterpret model probabilities
    - call an LLM
    - choose a different modality
    """

    def build(
        self,
        processing: RadiologyProcessorResult,
    ) -> RadiologyAssessment:

        model_result = processing.result

        model_modality = str(
            model_result.modality
        ).strip().lower()

        processor_modality = (
            processing.modality.value
        )

        if model_modality != processor_modality:
            raise RadiologyAssessmentError(
                "Radiology processor modality does not match "
                "the model result modality. "
                f"Processor={processor_modality!r}, "
                f"model={model_modality!r}."
            )

        return RadiologyAssessment(
            modality=processing.modality,

            classification=(
                getattr(model_result.classification, "value", model_result.classification)
            ),

            probabilities=dict(
                model_result.probabilities
            ),

            confidence=float(
                model_result.confidence
            ),

            inference_latency_ms=float(
                model_result.inference_latency_ms
            ),

            model_name=model_result.model_name,
            model_version=model_result.model_version,

            limitations=tuple(
                model_result.limitations
            ),
        )
