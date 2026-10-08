from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isclose, isfinite


class ChestXrayClassification(str, Enum):
    NORMAL = "normal"
    PNEUMONIA = "pneumonia"


class ChestXrayResultStatus(str, Enum):
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class ChestXrayResult:
    """
    Structured output produced by the MedMind Chest X-Ray model engine.

    This represents a model classification / screening result.
    It must not be treated as an autonomous clinical diagnosis.
    """

    classification: ChestXrayClassification

    normal_probability: float
    pneumonia_probability: float
    confidence: float

    inference_latency_ms: float

    model_name: str
    model_version: str

    modality: str = "chest_xray"
    status: ChestXrayResultStatus = ChestXrayResultStatus.COMPLETED

    limitations: tuple[str, ...] = (
        "AI model classification for educational and decision-support use only.",
        "The result is not a clinical diagnosis.",
        "Model performance may vary across image sources and patient populations.",
    )

    def __post_init__(self) -> None:
        probabilities = (
            self.normal_probability,
            self.pneumonia_probability,
            self.confidence,
        )

        if not all(isfinite(value) for value in probabilities):
            raise ValueError("Probabilities and confidence must be finite.")

        if not 0.0 <= self.normal_probability <= 1.0:
            raise ValueError(
                "normal_probability must be between 0.0 and 1.0."
            )

        if not 0.0 <= self.pneumonia_probability <= 1.0:
            raise ValueError(
                "pneumonia_probability must be between 0.0 and 1.0."
            )

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "confidence must be between 0.0 and 1.0."
            )

        if not isclose(
            self.normal_probability + self.pneumonia_probability,
            1.0,
            abs_tol=1e-6,
        ):
            raise ValueError(
                "Normal and pneumonia probabilities must sum to 1.0."
            )

        expected_confidence = max(
            self.normal_probability,
            self.pneumonia_probability,
        )

        if not isclose(
            self.confidence,
            expected_confidence,
            abs_tol=1e-6,
        ):
            raise ValueError(
                "confidence must equal the highest class probability."
            )

        if (
            not isfinite(self.inference_latency_ms)
            or self.inference_latency_ms < 0.0
        ):
            raise ValueError(
                "inference_latency_ms must be a finite non-negative value."
            )

        if not self.model_name.strip():
            raise ValueError("model_name must not be empty.")

        if not self.model_version.strip():
            raise ValueError("model_version must not be empty.")

    @property
    def probabilities(self) -> dict[str, float]:
        return {
            ChestXrayClassification.NORMAL.value: self.normal_probability,
            ChestXrayClassification.PNEUMONIA.value: self.pneumonia_probability,
        }