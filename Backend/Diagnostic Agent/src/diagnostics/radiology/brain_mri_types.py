from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isclose, isfinite


class BrainMriClassification(str, Enum):
    GLIOMA = "glioma"
    MENINGIOMA = "meningioma"
    NO_TUMOR = "notumor"
    PITUITARY = "pituitary"


class BrainMriResultStatus(str, Enum):
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class BrainMriResult:
    """
    Structured output produced by the MedMind Brain MRI model engine.

    This represents a model classification / screening result.
    It must not be treated as an autonomous clinical diagnosis.
    """

    classification: BrainMriClassification

    glioma_probability: float
    meningioma_probability: float
    notumor_probability: float
    pituitary_probability: float

    confidence: float

    inference_latency_ms: float

    model_name: str
    model_version: str

    modality: str = "brain_mri"
    status: BrainMriResultStatus = BrainMriResultStatus.COMPLETED

    limitations: tuple[str, ...] = (
        "AI model classification for educational and decision-support use only.",
        "The result is not a clinical diagnosis.",
        "Class performance is not uniform and results require qualified clinical review.",
        "Model performance may vary across image sources and patient populations.",
    )

    def __post_init__(self) -> None:
        probabilities = (
            self.glioma_probability,
            self.meningioma_probability,
            self.notumor_probability,
            self.pituitary_probability,
        )

        if not all(
            isfinite(value)
            for value in probabilities
        ):
            raise ValueError(
                "Class probabilities must be finite."
            )

        for name, value in (
            ("glioma_probability", self.glioma_probability),
            ("meningioma_probability", self.meningioma_probability),
            ("notumor_probability", self.notumor_probability),
            ("pituitary_probability", self.pituitary_probability),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(
                    f"{name} must be between 0.0 and 1.0."
                )

        if not isfinite(self.confidence):
            raise ValueError(
                "confidence must be finite."
            )

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "confidence must be between 0.0 and 1.0."
            )

        if not isclose(
            sum(probabilities),
            1.0,
            abs_tol=1e-6,
        ):
            raise ValueError(
                "Brain MRI class probabilities must sum to 1.0."
            )

        probability_map = self.probabilities

        expected_confidence = max(
            probability_map.values()
        )

        if not isclose(
            self.confidence,
            expected_confidence,
            abs_tol=1e-6,
        ):
            raise ValueError(
                "confidence must equal the highest class probability."
            )

        expected_classification = max(
            probability_map,
            key=probability_map.get,
        )

        if self.classification.value != expected_classification:
            raise ValueError(
                "classification must match the class "
                "with the highest probability."
            )

        if (
            not isfinite(self.inference_latency_ms)
            or self.inference_latency_ms < 0.0
        ):
            raise ValueError(
                "inference_latency_ms must be a finite non-negative value."
            )

        if not self.model_name.strip():
            raise ValueError(
                "model_name must not be empty."
            )

        if not self.model_version.strip():
            raise ValueError(
                "model_version must not be empty."
            )

    @property
    def probabilities(self) -> dict[str, float]:
        return {
            BrainMriClassification.GLIOMA.value:
                self.glioma_probability,

            BrainMriClassification.MENINGIOMA.value:
                self.meningioma_probability,

            BrainMriClassification.NO_TUMOR.value:
                self.notumor_probability,

            BrainMriClassification.PITUITARY.value:
                self.pituitary_probability,
        }