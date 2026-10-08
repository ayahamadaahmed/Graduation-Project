from pathlib import Path

from src.diagnostics.radiology.chest_xray_model import ChestXrayModel


MODEL_PATH = Path(
    "model_review/mediscan_hf_space/x-ray.keras"
)

SAMPLES = [
    (
        "NORMAL",
        Path(
            "model_review/xray_validation/"
            "NORMAL/IM-0001-0001.jpeg"
        ),
    ),
    (
        "PNEUMONIA",
        Path(
            "model_review/xray_validation/"
            "PNEUMONIA/person1000_virus_1681.jpeg"
        ),
    ),
]


def main():
    engine = ChestXrayModel(
        model_path=MODEL_PATH,
    )

    print("=" * 70)
    print("MEDMIND CHEST X-RAY REAL ARTIFACT SMOKE TEST")
    print("=" * 70)

    for expected, image_path in SAMPLES:
        result = engine.predict(image_path)

        print()
        print(f"Image:      {image_path.name}")
        print(f"Expected:   {expected}")
        print(
            f"Predicted:  {result.classification.value.upper()}"
        )
        print(
            f"Normal:     {result.normal_probability:.4f}"
        )
        print(
            f"Pneumonia:  {result.pneumonia_probability:.4f}"
        )
        print(
            f"Confidence: {result.confidence:.4f}"
        )
        print(
            f"Latency:    {result.inference_latency_ms:.2f} ms"
        )


if __name__ == "__main__":
    main()