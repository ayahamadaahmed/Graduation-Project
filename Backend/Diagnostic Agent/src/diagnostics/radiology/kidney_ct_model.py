from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError

from .kidney_ct_types import (
    KidneyCtClassification,
    KidneyCtResult,
)


IMAGE_SIZE = (224, 224)

DEFAULT_MODEL_PATH = Path(
    "models/radiology/medmind_kidney_ct_model.keras"
)

MODEL_NAME = "medmind-kidney-ct-efficientnetb0"
MODEL_VERSION = "medmind_kidney_ct_model.keras"


CLASS_ORDER = (
    KidneyCtClassification.CYST,
    KidneyCtClassification.NORMAL,
    KidneyCtClassification.STONE,
    KidneyCtClassification.TUMOR,
)


class KidneyCtInputError(ValueError):
    """Raised when the supplied Kidney CT image cannot be processed."""


class KidneyCtModelError(RuntimeError):
    """Raised when the Kidney CT model cannot be loaded or executed."""


class KidneyCtModel:
    """
    MedMind wrapper around the MedMind EfficientNetB0 Kidney CT model.

    Input:
        image path

    Processing:
        image
        -> RGB
        -> resize 224x224
        -> float32 raw pixel values 0-255
        -> model inference

    Output:
        KidneyCtResult

    This engine produces a model classification / decision-support result.
    It does not provide an autonomous clinical diagnosis.
    """

    def __init__(
        self,
        model_path: str | Path = DEFAULT_MODEL_PATH,
        model: Any | None = None,
    ) -> None:
        self.model_path = Path(model_path)

        # Dependency injection allows unit tests to use a fake model
        # without loading TensorFlow or the real model artifact.
        self._model = model

    def _load_model(self) -> None:
        if self._model is not None:
            return

        if not self.model_path.exists():
            raise KidneyCtModelError(
                f"Kidney CT model artifact not found: {self.model_path}"
            )

        if not self.model_path.is_file():
            raise KidneyCtModelError(
                f"Kidney CT model path is not a file: {self.model_path}"
            )

        try:
            import tensorflow as tf

            self._model = tf.keras.models.load_model(
                str(self.model_path),
                compile=False,
            )

        except Exception as exc:
            raise KidneyCtModelError(
                f"Failed to load Kidney CT model: {self.model_path}"
            ) from exc

    @staticmethod
    def _prepare_image(
        image_path: str | Path,
    ) -> np.ndarray:
        path = Path(image_path)

        if not path.exists():
            raise KidneyCtInputError(
                f"Kidney CT image not found: {path}"
            )

        if not path.is_file():
            raise KidneyCtInputError(
                f"Kidney CT image path is not a file: {path}"
            )

        try:
            with Image.open(path) as image:
                image = image.convert("RGB")

                image = image.resize(
                    IMAGE_SIZE,
                    resample=Image.Resampling.NEAREST,
                )

                array = np.asarray(
                    image,
                    dtype=np.float32,
                )

        except (UnidentifiedImageError, OSError) as exc:
            raise KidneyCtInputError(
                f"Invalid or unreadable image: {path}"
            ) from exc

        expected_shape = (
            IMAGE_SIZE[1],
            IMAGE_SIZE[0],
            3,
        )

        if array.shape != expected_shape:
            raise KidneyCtInputError(
                "Unexpected image shape after preprocessing: "
                f"{array.shape}. Expected {expected_shape}."
            )

        # IMPORTANT:
        # Keep raw pixel values in the 0-255 range.
        #
        # Do NOT divide by 255.
        # Do NOT call EfficientNet preprocess_input.
        #
        # The trained EfficientNetB0 artifact contains its
        # preprocessing layers internally.
        return np.expand_dims(
            array,
            axis=0,
        )

    @staticmethod
    def _validate_probabilities(
        prediction: Any,
    ) -> np.ndarray:
        probabilities = np.asarray(
            prediction,
            dtype=np.float64,
        ).reshape(-1)

        if probabilities.size != len(CLASS_ORDER):
            raise KidneyCtModelError(
                "Unexpected Kidney CT model output shape. "
                f"Expected {len(CLASS_ORDER)} probabilities, "
                f"received {np.asarray(prediction).shape}."
            )

        if not np.all(
            np.isfinite(probabilities)
        ):
            raise KidneyCtModelError(
                "Kidney CT model returned non-finite probabilities."
            )

        if np.any(probabilities < 0.0) or np.any(
            probabilities > 1.0
        ):
            raise KidneyCtModelError(
                "Kidney CT model returned probabilities "
                "outside the 0-1 range."
            )

        probability_sum = float(
            probabilities.sum()
        )

        if not np.isclose(
            probability_sum,
            1.0,
            atol=1e-4,
        ):
            raise KidneyCtModelError(
                "Kidney CT model probabilities must sum to 1.0. "
                f"Received sum={probability_sum:.6f}."
            )

        return probabilities

    def _predict_probabilities(
        self,
        batch: np.ndarray,
    ) -> tuple[np.ndarray, float]:
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
            raise KidneyCtModelError(
                "Kidney CT model inference failed."
            ) from exc

        probabilities = self._validate_probabilities(
            prediction
        )

        return probabilities, latency_ms

    def warm_up(self) -> float:
        """
        Load and warm the model before serving real requests.

        The synthetic input is only used to initialize the
        inference runtime. Its output is discarded.

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
            raise KidneyCtModelError(
                "Kidney CT model warm-up failed."
            ) from exc

        return latency_ms

    def predict(
        self,
        image_path: str | Path,
    ) -> KidneyCtResult:
        batch = self._prepare_image(
            image_path
        )

        probabilities, latency_ms = (
            self._predict_probabilities(
                batch
            )
        )

        predicted_index = int(
            np.argmax(probabilities)
        )

        classification = CLASS_ORDER[
            predicted_index
        ]

        confidence = float(
            probabilities[predicted_index]
        )

        return KidneyCtResult(
            classification=classification,

            cyst_probability=float(
                probabilities[0]
            ),

            normal_probability=float(
                probabilities[1]
            ),

            stone_probability=float(
                probabilities[2]
            ),

            tumor_probability=float(
                probabilities[3]
            ),

            confidence=confidence,
            inference_latency_ms=latency_ms,

            model_name=MODEL_NAME,
            model_version=MODEL_VERSION,
        )