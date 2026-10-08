from pathlib import Path
from statistics import mean

from src.diagnostics.radiology.chest_xray_model import ChestXrayModel


MODEL_PATH = Path(
    "model_review/mediscan_hf_space/x-ray.keras"
)

DATASET_ROOT = Path(
    "model_review/xray_validation"
)


def main():
    engine = ChestXrayModel(
        model_path=MODEL_PATH,
    )

    correct = 0
    total = 0
    latencies = []

    print("=" * 80)
    print("MEDMIND CHEST X-RAY VALIDATION")
    print("=" * 80)

    for expected_class in ("NORMAL", "PNEUMONIA"):
        folder = DATASET_ROOT / expected_class

        for image_path in sorted(folder.glob("*")):
            result = engine.predict(image_path)

            predicted = result.classification.value.upper()
            is_correct = predicted == expected_class

            total += 1

            if is_correct:
                correct += 1

            latencies.append(
                result.inference_latency_ms
            )

            print()
            print(f"Image:      {image_path.name}")
            print(f"Expected:   {expected_class}")
            print(f"Predicted:  {predicted}")
            print(
                f"Confidence: "
                f"{result.confidence:.4f}"
            )
            print(
                f"Latency:    "
                f"{result.inference_latency_ms:.2f} ms"
            )
            print(
                f"Result:     "
                f"{'PASS' if is_correct else 'FAIL'}"
            )

    accuracy = (
        correct / total * 100.0
        if total
        else 0.0
    )

    # First prediction is TensorFlow cold-start.
    warm_latencies = latencies[1:]

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Correct:       {correct}/{total}")
    print(f"Accuracy:      {accuracy:.2f}%")

    if latencies:
        print(
            f"Cold latency:  "
            f"{latencies[0]:.2f} ms"
        )

    if warm_latencies:
        print(
            f"Warm average:  "
            f"{mean(warm_latencies):.2f} ms"
        )
        print(
            f"Warm min:      "
            f"{min(warm_latencies):.2f} ms"
        )
        print(
            f"Warm max:      "
            f"{max(warm_latencies):.2f} ms"
        )


if __name__ == "__main__":
    main()