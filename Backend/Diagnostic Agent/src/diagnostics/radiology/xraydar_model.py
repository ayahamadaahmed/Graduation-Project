from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import torch
from PIL import Image, UnidentifiedImageError

from .xraydar_inception import Inception3


XRAYDAR_LABELS = (
    "abnormal_non_clinically_important", "aortic_calcification", "apical_changes",
    "atelectasis", "axillary_abnormality", "bronchial_changes", "bulla",
    "cardiomegaly", "cavity", "clavicle_fracture", "consolidation",
    "cardiac_calcification", "dextrocardia", "dilated_bowel", "emphysema",
    "ground_glass_opacification", "hemidiaphragm_elevated", "hernia",
    "hyperexpanded_lungs", "interstitial_shadowing", "mediastinum_displaced",
    "mediastinum_widened", "object", "paraspinal_mass",
    "paratracheal_hilar_enlargement", "parenchymal_lesion", "pleural_abnormality",
    "pleural_effusion", "pneumomediastinum", "pneumoperitoneum", "pneumothorax",
    "rib_fracture", "rib_lesion", "scoliosis", "subcutaneous_emphysema",
    "tortuosity_aorta", "pulmonary_bloodflow_redistribution", "volume_loss",
)

SCALES = (299, 512, 1024)
MODEL_NAME = "xraydar-multiscale"
MODEL_VERSION = "38-labels"


class XRaydarModelError(RuntimeError):
    """Raised when the local X-Raydar model cannot be loaded or run."""


class XRaydarChestXrayModel:
    """Local multi-label X-Raydar inference for frontal chest radiographs."""

    def __init__(self, model_dir: str | Path | None = None) -> None:
        self.model_dir = Path(model_dir) if model_dir else Path(__file__).resolve().parents[3] / "models" / "xraydar"
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.models: list[torch.nn.Module] = []
        self._load_models()

    def _load_models(self) -> None:
        for scale in SCALES:
            checkpoint_path = self.model_dir / f"is{scale}" / "model_best.pth.tar"
            if not checkpoint_path.is_file():
                raise XRaydarModelError(
                    f"Missing X-Raydar {scale}px weights: {checkpoint_path}. "
                    "See models/xraydar/README.md for setup."
                )
            model = Inception3(num_classes=len(XRAYDAR_LABELS), aux_logits=True,
                               transform_input=True, in_channels=1,
                               init_weights=False)
            try:
                # The publisher's checkpoint includes NumPy metadata alongside
                # the state dict, which weights_only=True rejects on newer torch.
                # Only load checkpoints placed in this explicitly configured model folder.
                checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
                state = checkpoint.get("state_dict", checkpoint)
                state = {key.removeprefix("module."): value for key, value in state.items()}
                model.load_state_dict(state, strict=True)
            except Exception as exc:
                raise XRaydarModelError(f"Could not load X-Raydar weights at {checkpoint_path}.") from exc
            model.to(self.device).eval()
            self.models.append(model)

    @staticmethod
    def _prepare_image(image_path: str | Path) -> Image.Image:
        try:
            image = Image.open(image_path).convert("L")
        except (OSError, UnidentifiedImageError) as exc:
            raise ValueError("The supplied file is not a readable chest X-ray image.") from exc
        width, height = image.size
        if width < 2 or height < 2:
            raise ValueError("The chest X-ray image dimensions are invalid.")
        side = max(width, height)
        canvas = Image.new("L", (side, side), color=0)
        canvas.paste(image, ((side - width) // 2, (side - height) // 2))
        return canvas

    def _predict_scores(self, image: Image.Image) -> np.ndarray:
        tensors = []
        for scale in SCALES:
            resized = image.resize((scale, scale), Image.Resampling.BILINEAR)
            array = np.asarray(resized, dtype=np.float32) / 255.0
            tensor = torch.from_numpy(array).unsqueeze(0).unsqueeze(0)
            tensors.append((tensor - 0.491) / 0.271)
        predictions = []
        with torch.inference_mode():
            for model, tensor in zip(self.models, tensors):
                output: Any = model(tensor.to(self.device))
                logits = output.logits if hasattr(output, "logits") else output
                predictions.append(torch.sigmoid(logits).squeeze(0).cpu())
        return torch.stack(predictions).mean(dim=0).numpy()

    def predict(self, image_path: str | Path) -> Any:
        started = perf_counter()
        scores = self._predict_scores(self._prepare_image(image_path))
        score_map = {label: float(score) for label, score in zip(XRAYDAR_LABELS, scores)}
        classification = max(score_map, key=score_map.get)
        return XRaydarResult(
            classification=classification,
            probabilities=score_map,
            confidence=score_map[classification],
            inference_latency_ms=(perf_counter() - started) * 1000.0,
            model_name=MODEL_NAME,
            model_version=MODEL_VERSION,
        )

    def warm_up(self) -> float:
        start = perf_counter()
        self._predict_scores(Image.new("L", (1024, 1024), color=0))
        return (perf_counter() - start) * 1000.0


class XRaydarResult:
    """Attribute-compatible result consumed by RadiologyAssessmentBuilder."""

    modality = "chest_xray"
    status = "completed"
    limitations = (
        "Research model output for educational decision support; not a clinical diagnosis.",
        "The 38 findings are independent, non-exclusive scores; they are not calibrated probabilities or diagnostic confidence.",
        "There is no dedicated pulmonary embolism or pulmonary infarction label; a chest X-ray score cannot rule these conditions in or out.",
        "Pulmonary edema is not a dedicated label; related findings do not establish or exclude edema.",
        "This model is intended for frontal chest radiographs. Image quality, view, population, and local validation affect performance.",
        "Review by a qualified radiologist and clinical correlation are required.",
    )

    def __init__(self, classification: str, probabilities: dict[str, float], confidence: float,
                 inference_latency_ms: float, model_name: str, model_version: str) -> None:
        self.classification = classification
        self.probabilities = probabilities
        self.confidence = confidence
        self.inference_latency_ms = inference_latency_ms
        self.model_name = model_name
        self.model_version = model_version
