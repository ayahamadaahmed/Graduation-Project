from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .brain_mri_model import BrainMriModel
from .brain_mri_types import BrainMriResult

from .chest_xray_model import ChestXrayModel
from .chest_xray_types import ChestXrayResult

from .kidney_ct_model import KidneyCtModel
from .kidney_ct_types import KidneyCtResult


class RadiologyModality(str, Enum):
    CHEST_XRAY = "chest_xray"
    BRAIN_MRI = "brain_mri"
    KIDNEY_CT = "kidney_ct"


RadiologyModelResult = (
    ChestXrayResult
    | BrainMriResult
    | KidneyCtResult
)


@dataclass(frozen=True, slots=True)
class RadiologyProcessorResult:
    """
    Structured result returned by the deterministic
    MedMind Radiology Processor.

    The processor routes one radiology image to exactly
    one modality-specific model engine.
    """

    modality: RadiologyModality
    result: RadiologyModelResult


class RadiologyProcessorError(RuntimeError):
    """Base error raised by the Radiology Processor."""


class UnsupportedRadiologyModalityError(
    RadiologyProcessorError
):
    """Raised when an unsupported radiology modality is supplied."""


class RadiologyProcessor:
    """
    Deterministic radiology routing layer.

    Responsibilities:
    - accept one image path
    - accept an explicitly selected modality
    - route the image to exactly one model engine
    - return the structured model result

    This processor does NOT:
    - infer the modality from the image
    - run all models and compare confidence
    - provide an autonomous diagnosis
    - act as the conversational Radiology Agent
    """

    def __init__(
        self,
        chest_xray_model: Any | None = None,
        brain_mri_model: Any | None = None,
        kidney_ct_model: Any | None = None,
    ) -> None:
        self.chest_xray_model = (
            chest_xray_model
            if chest_xray_model is not None
            else ChestXrayModel()
        )

        self.brain_mri_model = (
            brain_mri_model
            if brain_mri_model is not None
            else BrainMriModel()
        )

        self.kidney_ct_model = (
            kidney_ct_model
            if kidney_ct_model is not None
            else KidneyCtModel()
        )

    @staticmethod
    def _normalize_modality(
        modality: RadiologyModality | str,
    ) -> RadiologyModality:
        if isinstance(
            modality,
            RadiologyModality,
        ):
            return modality

        try:
            return RadiologyModality(
                str(modality).strip().lower()
            )

        except ValueError as exc:
            raise UnsupportedRadiologyModalityError(
                f"Unsupported radiology modality: {modality!r}"
            ) from exc

    def warm_up(
        self,
    ) -> dict[str, float]:
        """
        Warm all configured radiology model engines.

        Returns per-modality warm-up inference latency
        in milliseconds.

        This method does not produce or expose any
        clinical/model classification.
        """

        timings = {
            RadiologyModality.CHEST_XRAY.value:
                float(
                    self.chest_xray_model
                    .warm_up()
                ),

            RadiologyModality.BRAIN_MRI.value:
                float(
                    self.brain_mri_model
                    .warm_up()
                ),

            RadiologyModality.KIDNEY_CT.value:
                float(
                    self.kidney_ct_model
                    .warm_up()
                ),
        }

        return timings
    
    def process(
        self,
        image_path: str | Path,
        modality: RadiologyModality | str,
    ) -> RadiologyProcessorResult:

        normalized_modality = (
            self._normalize_modality(
                modality
            )
        )

        if (
            normalized_modality
            == RadiologyModality.CHEST_XRAY
        ):
            model_result = (
                self.chest_xray_model.predict(
                    image_path
                )
            )

        elif (
            normalized_modality
            == RadiologyModality.BRAIN_MRI
        ):
            model_result = (
                self.brain_mri_model.predict(
                    image_path
                )
            )

        elif (
            normalized_modality
            == RadiologyModality.KIDNEY_CT
        ):
            model_result = (
                self.kidney_ct_model.predict(
                    image_path
                )
            )

        else:
            # Defensive fallback in case the enum
            # is extended without updating routing.
            raise UnsupportedRadiologyModalityError(
                "Radiology modality has no configured model: "
                f"{normalized_modality.value}"
            )

        return RadiologyProcessorResult(
            modality=normalized_modality,
            result=model_result,
        )
