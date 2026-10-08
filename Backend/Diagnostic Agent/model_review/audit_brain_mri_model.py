from pathlib import Path

import tensorflow as tf


MODEL_PATH = Path(
    "model_review/mediscan_hf_space/"
    "best_brain_tumor_model.keras"
)


def print_layer_tree(layer, indent=0):
    prefix = " " * indent

    print(
        f"{prefix}- {layer.name}: "
        f"{layer.__class__.__name__}"
    )

    if hasattr(layer, "layers"):
        for child in layer.layers:
            print_layer_tree(
                child,
                indent + 2,
            )


def main():
    print("=" * 80)
    print("MEDMIND BRAIN MRI MODEL AUDIT")
    print("=" * 80)

    print()
    print(f"Artifact: {MODEL_PATH}")

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Model not found: {MODEL_PATH}"
        )

    print(f"Size:     {MODEL_PATH.stat().st_size / 1024 / 1024:.2f} MB")

    print()
    print("Loading model...")

    model = tf.keras.models.load_model(
        MODEL_PATH,
        compile=False,
    )

    print()
    print("=" * 80)
    print("BASIC MODEL INFO")
    print("=" * 80)

    print(f"Model name:   {model.name}")
    print(f"Input shape:  {model.input_shape}")
    print(f"Output shape: {model.output_shape}")
    print(f"Parameters:   {model.count_params():,}")

    last_layer = model.layers[-1]

    print()
    print("=" * 80)
    print("OUTPUT LAYER")
    print("=" * 80)

    print(f"Name:       {last_layer.name}")
    print(f"Type:       {last_layer.__class__.__name__}")

    if hasattr(last_layer, "units"):
        print(f"Units:      {last_layer.units}")

    if hasattr(last_layer, "activation"):
        print(
            "Activation: "
            f"{last_layer.activation.__name__}"
        )

    print()
    print("=" * 80)
    print("PREPROCESSING-RELATED LAYERS")
    print("=" * 80)

    found = False

    def inspect(layer, path=""):
        nonlocal found

        current_path = (
            f"{path}/{layer.name}"
            if path
            else layer.name
        )

        layer_type = layer.__class__.__name__

        if layer_type in {
            "Rescaling",
            "Normalization",
            "RandomFlip",
            "RandomRotation",
            "RandomZoom",
            "RandomTranslation",
            "RandomContrast",
        }:
            found = True

            print(
                f"{current_path}: "
                f"{layer_type}"
            )

            try:
                print(
                    f"  config = {layer.get_config()}"
                )
            except Exception:
                pass

        if hasattr(layer, "layers"):
            for child in layer.layers:
                inspect(
                    child,
                    current_path,
                )

    inspect(model)

    if not found:
        print(
            "No explicit preprocessing layers "
            "were found inside the saved model."
        )

    print()
    print("=" * 80)
    print("MODEL TREE")
    print("=" * 80)

    print_layer_tree(model)


if __name__ == "__main__":
    main()