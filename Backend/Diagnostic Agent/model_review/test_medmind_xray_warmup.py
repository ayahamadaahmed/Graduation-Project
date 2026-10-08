from pathlib import Path
from time import perf_counter

from src.diagnostics.radiology.chest_xray_model import ChestXrayModel


MODEL_PATH = Path(
    "model_review/mediscan_hf_space/x-ray.keras"
)

IMAGE_PATH = Path(
    "model_review/xray_validation/"
    "PNEUMONIA/person1000_virus_1681.jpeg"
)


def main():
    engine = ChestXrayModel(
        model_path=MODEL_PATH,
    )

    print("=" * 70)
    print("MEDMIND CHEST X-RAY WARM-UP TEST")
    print("=" * 70)

    startup_start = perf_counter()

    warmup_latency = engine.warm_up()

    total_startup_ms = (
        perf_counter() - startup_start
    ) * 1000.0

    print()
    print(f"Startup + model load: {total_startup_ms:.2f} ms")
    print(f"Warm-up inference:    {warmup_latency:.2f} ms")

    print()
    print("Running first REAL patient image after warm-up...")

    result = engine.predict(IMAGE_PATH)

    print()
    print(f"Image:       {IMAGE_PATH.name}")
    print(f"Predicted:   {result.classification.value.upper()}")
    print(f"Normal:      {result.normal_probability:.4f}")
    print(f"Pneumonia:   {result.pneumonia_probability:.4f}")
    print(f"Confidence:  {result.confidence:.4f}")
    print(f"Patient latency: {result.inference_latency_ms:.2f} ms")


if __name__ == "__main__":
    main()