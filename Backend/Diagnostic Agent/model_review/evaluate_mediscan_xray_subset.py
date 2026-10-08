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

DATASET_DIR = (
    ROOT
    / "model_review"
    / "xray_validation"
)

THRESHOLD = 0.5


def prepare_image(path: Path) -> np.ndarray:
    image = Image.open(path).convert("RGB")
    image = image.resize((384, 384))

    # Keep raw 0-255 pixels.
    # EfficientNet preprocessing is inside the model.
    array = np.asarray(
        image,
        dtype=np.float32,
    )

    return np.expand_dims(array, axis=0)


def main():
    print("=" * 72)
    print("MEDISCAN X-RAY SUBSET EVALUATION")
    print("=" * 72)

    print("\nLoading model...")

    model = tf.keras.models.load_model(
        MODEL_PATH
    )

    # Warm-up
    first_image = next(
        (DATASET_DIR / "NORMAL").glob("*")
    )

    model.predict(
        prepare_image(first_image),
        verbose=0,
    )

    print("Warm-up complete.\n")

    tp = 0
    tn = 0
    fp = 0
    fn = 0

    latencies = []

    results = []

    for expected in [
        "NORMAL",
        "PNEUMONIA",
    ]:
        folder = DATASET_DIR / expected

        for image_path in sorted(
            folder.glob("*")
        ):
            batch = prepare_image(
                image_path
            )

            start = perf_counter()

            raw = model.predict(
                batch,
                verbose=0,
            )

            latency_ms = (
                perf_counter() - start
            ) * 1000

            pneumonia_prob = float(
                raw[0][0]
            )

            normal_prob = (
                1.0 - pneumonia_prob
            )

            if pneumonia_prob > THRESHOLD:
                predicted = "PNEUMONIA"
                confidence = pneumonia_prob
            else:
                predicted = "NORMAL"
                confidence = normal_prob

            latencies.append(
                latency_ms
            )

            results.append(
                {
                    "file": image_path.name,
                    "expected": expected,
                    "predicted": predicted,
                    "normal_prob": normal_prob,
                    "pneumonia_prob": pneumonia_prob,
                    "confidence": confidence,
                    "latency_ms": latency_ms,
                }
            )

            if (
                expected == "PNEUMONIA"
                and predicted == "PNEUMONIA"
            ):
                tp += 1

            elif (
                expected == "NORMAL"
                and predicted == "NORMAL"
            ):
                tn += 1

            elif (
                expected == "NORMAL"
                and predicted == "PNEUMONIA"
            ):
                fp += 1

            elif (
                expected == "PNEUMONIA"
                and predicted == "NORMAL"
            ):
                fn += 1

    print("PER-IMAGE RESULTS")
    print("-" * 72)

    for r in results:
        status = (
            "PASS"
            if r["expected"]
            == r["predicted"]
            else "FAIL"
        )

        print(
            f"\n{r['file']}"
        )
        print(
            f"Expected:   {r['expected']}"
        )
        print(
            f"Predicted:  {r['predicted']}"
        )
        print(
            f"Normal:     {r['normal_prob']:.4f}"
        )
        print(
            f"Pneumonia:  {r['pneumonia_prob']:.4f}"
        )
        print(
            f"Confidence: {r['confidence']:.4f}"
        )
        print(
            f"Latency:    {r['latency_ms']:.2f} ms"
        )
        print(
            f"Result:     {status}"
        )

    total = tp + tn + fp + fn

    accuracy = (
        (tp + tn) / total
        if total
        else 0.0
    )

    pneumonia_recall = (
        tp / (tp + fn)
        if (tp + fn)
        else 0.0
    )

    normal_recall = (
        tn / (tn + fp)
        if (tn + fp)
        else 0.0
    )

    pneumonia_precision = (
        tp / (tp + fp)
        if (tp + fp)
        else 0.0
    )

    avg_latency = float(
        np.mean(latencies)
    )

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)

    print(f"TP: {tp}")
    print(f"TN: {tn}")
    print(f"FP: {fp}")
    print(f"FN: {fn}")

    print(
        f"\nAccuracy: "
        f"{accuracy:.2%}"
    )

    print(
        f"Pneumonia recall: "
        f"{pneumonia_recall:.2%}"
    )

    print(
        f"Normal recall: "
        f"{normal_recall:.2%}"
    )

    print(
        f"Pneumonia precision: "
        f"{pneumonia_precision:.2%}"
    )

    print(
        f"Average CPU inference: "
        f"{avg_latency:.2f} ms"
    )


if __name__ == "__main__":
    main()