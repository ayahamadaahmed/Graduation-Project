from __future__ import annotations

from pathlib import Path
from time import perf_counter

import numpy as np
import tensorflow as tf
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]

MODEL_PATH = (
    ROOT
    / "model_review"
    / "mediscan_hf_space"
    / "x-ray.keras"
)

SAMPLES = [
    (
        ROOT
        / "model_review"
        / "xray_smoke_samples"
        / "TestImages"
        / "IM-0001-0001.jpeg",
        "NORMAL",
    ),
    (
        ROOT
        / "model_review"
        / "xray_smoke_samples"
        / "TestImages"
        / "person15_virus_46.jpeg",
        "PNEUMONIA",
    ),
]


def prepare_image(path: Path) -> np.ndarray:
    image = Image.open(path).convert("RGB")
    image = image.resize((384, 384))

    # IMPORTANT:
    # Keep pixels in 0-255 range.
    # EfficientNet preprocessing is already inside the model.
    array = np.asarray(
        image,
        dtype=np.float32,
    )

    return np.expand_dims(
        array,
        axis=0,
    )


def predict(
    model: tf.keras.Model,
    image_path: Path,
):
    batch = prepare_image(image_path)

    start = perf_counter()

    raw = model.predict(
        batch,
        verbose=0,
    )

    elapsed_ms = (
        perf_counter() - start
    ) * 1000

    pneumonia_probability = float(
        raw[0][0]
    )

    normal_probability = (
        1.0 - pneumonia_probability
    )

    if pneumonia_probability > 0.5:
        predicted = "PNEUMONIA"
        confidence = pneumonia_probability
    else:
        predicted = "NORMAL"
        confidence = normal_probability

    return {
        "predicted": predicted,
        "confidence": confidence,
        "normal_probability": normal_probability,
        "pneumonia_probability": pneumonia_probability,
        "latency_ms": elapsed_ms,
    }


def main():
    print("=" * 65)
    print("MEDISCAN X-RAY SMOKE TEST")
    print("=" * 65)

    print("\nLoading model...")

    start = perf_counter()

    model = tf.keras.models.load_model(
        MODEL_PATH
    )

    load_ms = (
        perf_counter() - start
    ) * 1000

    print(
        f"Model load: {load_ms:.2f} ms"
    )

    # Warm-up inference.
    warmup = prepare_image(
        SAMPLES[0][0]
    )

    model.predict(
        warmup,
        verbose=0,
    )

    print("Warm-up complete.\n")

    for image_path, expected in SAMPLES:
        result = predict(
            model,
            image_path,
        )

        correct = (
            result["predicted"]
            == expected
        )

        print("-" * 65)
        print(
            f"Image: {image_path.name}"
        )
        print(
            f"Expected: {expected}"
        )
        print(
            f"Predicted: "
            f"{result['predicted']}"
        )
        print(
            f"Confidence: "
            f"{result['confidence']:.4f}"
        )
        print(
            f"NORMAL probability: "
            f"{result['normal_probability']:.4f}"
        )
        print(
            f"PNEUMONIA probability: "
            f"{result['pneumonia_probability']:.4f}"
        )
        print(
            f"CPU inference: "
            f"{result['latency_ms']:.2f} ms"
        )
        print(
            f"Smoke result: "
            f"{'PASS ✅' if correct else 'FAIL ❌'}"
        )


if __name__ == "__main__":
    main()