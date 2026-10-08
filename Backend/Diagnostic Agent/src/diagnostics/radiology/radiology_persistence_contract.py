from __future__ import annotations

from dataclasses import dataclass

from .radiology_assessment import (
    RadiologyAssessment,
)


class RadiologyPersistenceContractError(
    RuntimeError
):
    pass


@dataclass(frozen=True)
class RadiologyPersistenceResult:
    schema_version: str

    modality: str

    classification: str

    probabilities: dict[str, float]

    confidence: float

    inference_latency_ms: float

    model_name: str

    model_version: str

    limitations: list[str]


class RadiologyPersistenceContractBuilder:
    """
    Converts trusted deterministic radiology assessment
    output into a JSON-safe persistence contract.

    Responsibilities:
    - preserve explicitly routed modality
    - preserve model classification
    - preserve all model probabilities
    - preserve model confidence
    - preserve inference latency
    - preserve model metadata
    - preserve limitations
    - do NOT rerun the model
    - do NOT infer modality
    - do NOT recalculate probabilities
    - do NOT reinterpret classification
    - do NOT diagnose
    """

    SCHEMA_VERSION = "1.0"

    def build(
        self,
        *,
        assessment: RadiologyAssessment,
    ) -> RadiologyPersistenceResult:

        classification = (
            assessment.classification.strip()
        )

        if not classification:
            raise RadiologyPersistenceContractError(
                "Radiology classification "
                "cannot be empty."
            )

        probabilities = dict(
            assessment.probabilities
        )

        if not probabilities:
            raise RadiologyPersistenceContractError(
                "Radiology probabilities "
                "cannot be empty."
            )

        if (
            classification
            not in probabilities
        ):
            raise RadiologyPersistenceContractError(
                "Radiology classification "
                "is missing from probabilities."
            )

        return RadiologyPersistenceResult(
            schema_version=(
                self.SCHEMA_VERSION
            ),

            modality=(
                assessment.modality.value
            ),

            classification=(
                classification
            ),

            probabilities=probabilities,

            confidence=float(
                assessment.confidence
            ),

            inference_latency_ms=float(
                assessment.inference_latency_ms
            ),

            model_name=(
                assessment.model_name
            ),

            model_version=(
                assessment.model_version
            ),

            limitations=list(
                assessment.limitations
            ),
        )