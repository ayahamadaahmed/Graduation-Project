from __future__ import annotations

from pathlib import Path
import tensorflow as tf


MODEL_PATH = (
    Path(__file__).resolve().parents[1]
    / "model_review"
    / "mediscan_hf_space"
    / "x-ray.keras"
)


def main():
    print("=" * 70)
    print("MEDISCAN X-RAY MODEL INSPECTION")
    print("=" * 70)

    print(f"\nModel path:\n{MODEL_PATH}")
    print(f"Exists: {MODEL_PATH.exists()}")

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Model not found: {MODEL_PATH}"
        )

    model = tf.keras.models.load_model(
        MODEL_PATH
    )

    print("\nLoaded successfully ✅")

    print("\nInput shape:")
    print(model.input_shape)

    print("\nOutput shape:")
    print(model.output_shape)

    print("\nModel summary:")
    model.summary()

    print("\nLast layer:")
    last_layer = model.layers[-1]
    print(type(last_layer).__name__)
    print("name:", last_layer.name)

    if hasattr(last_layer, "activation"):
        print(
            "activation:",
            last_layer.activation.__name__,
        )

    if hasattr(last_layer, "units"):
        print("units:", last_layer.units)


if __name__ == "__main__":
    main()