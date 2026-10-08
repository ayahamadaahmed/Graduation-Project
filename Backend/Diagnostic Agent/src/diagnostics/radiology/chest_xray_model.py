from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError

from .chest_xray_types import (
    ChestXrayClassification,
    ChestXrayResult,
)


IMAGE_SIZE = (384, 384)

DEFAULT_MODEL_PATH = Path(
    "model_review/mediscan_hf_space/x-ray.keras"
)

MODEL_NAME = "mediscan-efficientnetb3-pneumonia"
MODEL_VERSION = "x-ray.keras"


class ChestXrayInputError(ValueError):
    """Raised when the supplied Chest X-Ray image cannot be processed."""


class ChestXrayModelError(RuntimeError):
    """Raised when the Chest X-Ray model cannot be loaded or executed."""


class ChestXrayModel:
    """
    MedMind wrapper around the MediScan EfficientNetB3 Chest X-Ray model.

    Input:
        image path

    Processing:
        image
        -> RGB
        -> resize 384x384
        -> float32 raw pixel values 0-255
        -> model inference

    Output:
        ChestXrayResult

    This engine produces a model classification / screening result.
    It does not provide an autonomous clinical diagnosis.
    """

    def __init__(
        self,
        model_path: str | Path = DEFAULT_MODEL_PATH,
        model: Any | None = None,
    ) -> None:
        self.model_path = Path(model_path)

        # Allows dependency injection in unit tests so the real
        # TensorFlow model does not need to be loaded.
        self._model = model

    def _load_model(self) -> None:
        if self._model is not None:
            return

        if not self.model_path.exists():
            raise ChestXrayModelError(
                f"Chest X-Ray model artifact not found: {self.model_path}"
            )

        if not self.model_path.is_file():
            raise ChestXrayModelError(
                f"Chest X-Ray model path is not a file: {self.model_path}"
            )

        try:
            import tensorflow as tf

            self._model = tf.keras.models.load_model(
                str(self.model_path)
            )

        except Exception as exc:
            raise ChestXrayModelError(
                f"Failed to load Chest X-Ray model: {self.model_path}"
            ) from exc

    @staticmethod
    def _prepare_image(image_path: str | Path) -> np.ndarray:
        path = Path(image_path)

        if not path.exists():
            raise ChestXrayInputError(
                f"Chest X-Ray image not found: {path}"
            )

        if not path.is_file():
            raise ChestXrayInputError(
                f"Chest X-Ray image path is not a file: {path}"
            )

        try:
            with Image.open(path) as image:
                image = image.convert("RGB")
                image = image.resize(IMAGE_SIZE)

                array = np.asarray(
                    image,
                    dtype=np.float32,
                )

        except (UnidentifiedImageError, OSError) as exc:
            raise ChestXrayInputError(
                f"Invalid or unreadable image: {path}"
            ) from exc

        expected_shape = (
            IMAGE_SIZE[1],
            IMAGE_SIZE[0],
            3,
        )

        if array.shape != expected_shape:
            raise ChestXrayInputError(
                "Unexpected image shape after preprocessing: "
                f"{array.shape}. Expected {expected_shape}."
            )

        # IMPORTANT:
        # Do NOT divide by 255.
        # Do NOT call EfficientNet preprocess_input.
        #
        # The exported model already contains its preprocessing.
        return np.expand_dims(array, axis=0)

    @staticmethod
    def _as_probability(raw_value: float) -> float:
        """
        Convert the model output to a probability.

        The verified artifact normally returns a sigmoid probability.
        This fallback safely handles a raw logit if an exported model
        unexpectedly returns one.
        """

        value = float(raw_value)

        if not np.isfinite(value):
            raise ChestXrayModelError(
                "Chest X-Ray model returned a non-finite prediction."
            )

        if 0.0 <= value <= 1.0:
            return value

        # Numerically stable sigmoid fallback.
        if value >= 0:
            return float(
                1.0 / (1.0 + np.exp(-value))
            )

        exp_value = np.exp(value)

        return float(
            exp_value / (1.0 + exp_value)
        )

    def _predict_probability(
        self,
        batch: np.ndarray,
    ) -> tuple[float, float]:
        self._load_model()

        try:
            start = perf_counter()

            prediction = self._model.predict(
                batch,
                verbose=0,
            )

            latency_ms = (
                perf_counter() - start
            ) * 1000.0

        except Exception as exc:
            raise ChestXrayModelError(
                "Chest X-Ray model inference failed."
            ) from exc

        prediction_array = np.asarray(
            prediction,
            dtype=np.float64,
        ).reshape(-1)

        if prediction_array.size != 1:
            raise ChestXrayModelError(
                "Unexpected Chest X-Ray model output shape. "
                f"Expected one sigmoid value, received "
                f"{np.asarray(prediction).shape}."
            )

        pneumonia_probability = self._as_probability(
            prediction_array[0]
        )

        return pneumonia_probability, latency_ms

    def warm_up(self) -> float:
        """
        Load and warm the model before serving real requests.

        The synthetic input is used only to initialize the inference
        runtime. Its prediction is discarded and is never exposed as
        a clinical/model result.

        Returns:
            Warm-up inference latency in milliseconds.
        """

        self._load_model()

        batch = np.zeros(
            (
                1,
                IMAGE_SIZE[1],
                IMAGE_SIZE[0],
                3,
            ),
            dtype=np.float32,
        )

        try:
            start = perf_counter()

            self._model.predict(
                batch,
                verbose=0,
            )

            latency_ms = (
                perf_counter() - start
            ) * 1000.0

        except Exception as exc:
            raise ChestXrayModelError(
                "Chest X-Ray model warm-up failed."
            ) from exc

        return latency_ms    

    def predict(
        self,
        image_path: str | Path,
    ) -> ChestXrayResult:
        batch = self._prepare_image(image_path)

        pneumonia_probability, latency_ms = (
            self._predict_probability(batch)
        )

        normal_probability = (
            1.0 - pneumonia_probability
        )

        if pneumonia_probability > 0.5:
            classification = (
                ChestXrayClassification.PNEUMONIA
            )
        else:
            classification = (
                ChestXrayClassification.NORMAL
            )

        confidence = max(
            normal_probability,
            pneumonia_probability,
        )

        return ChestXrayResult(
            classification=classification,
            normal_probability=normal_probability,
            pneumonia_probability=pneumonia_probability,
            confidence=confidence,
            inference_latency_ms=latency_ms,
            model_name=MODEL_NAME,
            model_version=MODEL_VERSION,
        )