from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isclose, isfinite


class KidneyCtClassification(str, Enum):
    CYST = "cyst"
    NORMAL = "normal"
    STONE = "stone"
    TUMOR = "tumor"


class KidneyCtResultStatus(str, Enum):
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class KidneyCtResult:
    """
    Structured output produced by the MedMind Kidney CT model engine.

    This represents a model classification / decision-support result.
    It must not be treated as an autonomous clinical diagnosis.
    """

    classification: KidneyCtClassification

    cyst_probability: float
    normal_probability: float
    stone_probability: float
    tumor_probability: float

    confidence: float

    inference_latency_ms: float

    model_name: str
    model_version: str

    modality: str = "kidney_ct"
    status: KidneyCtResultStatus = KidneyCtResultStatus.COMPLETED

    limitations: tuple[str, ...] = (
        "AI model classification for educational and decision-support use only.",
        "The result is not a clinical diagnosis.",
        "Evaluation was performed on an image-level held-out split.",
        "Patient identifiers were unavailable, so patient-level split independence could not be verified.",
        "Model performance may vary across image sources and patient populations.",
    )

    def __post_init__(self) -> None:
        probabilities = (
            self.cyst_probability,
            self.normal_probability,
            self.stone_probability,
            self.tumor_probability,
        )

        if not all(
            isfinite(value)
            for value in probabilities
        ):
            raise ValueError(
                "Class probabilities must be finite."
            )

        for name, value in (
            ("cyst_probability", self.cyst_probability),
            ("normal_probability", self.normal_probability),
            ("stone_probability", self.stone_probability),
            ("tumor_probability", self.tumor_probability),
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
                "Kidney CT class probabilities must sum to 1.0."
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
            KidneyCtClassification.CYST.value:
                self.cyst_probability,

            KidneyCtClassification.NORMAL.value:
                self.normal_probability,

            KidneyCtClassification.STONE.value:
                self.stone_probability,

            KidneyCtClassification.TUMOR.value:
                self.tumor_probability,
        }