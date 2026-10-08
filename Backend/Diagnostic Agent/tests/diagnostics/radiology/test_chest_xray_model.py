import numpy as np
import pytest
from PIL import Image

from src.diagnostics.radiology.chest_xray_model import (
    ChestXrayInputError,
    ChestXrayModel,
)
from src.diagnostics.radiology.chest_xray_types import (
    ChestXrayClassification,
)


class FakeModel:
    def __init__(self, output):
        self.output = output
        self.last_batch = None
        self.last_verbose = None

    def predict(self, batch, verbose=0):
        self.last_batch = batch
        self.last_verbose = verbose

        return np.array(
            [[self.output]],
            dtype=np.float32,
        )


@pytest.fixture
def xray_image(tmp_path):
    image_path = tmp_path / "xray.png"

    image = Image.new(
        "L",
        (100, 200),
        color=255,
    )

    image.save(image_path)

    return image_path


def test_preprocessing_and_pneumonia_prediction(xray_image):
    fake_model = FakeModel(0.90)

    engine = ChestXrayModel(
        model=fake_model,
    )

    result = engine.predict(xray_image)

    assert fake_model.last_batch.shape == (
        1,
        384,
        384,
        3,
    )

    assert fake_model.last_batch.dtype == np.float32

    # Confirms pixels remain in raw 0-255 range.
    assert fake_model.last_batch.max() == 255.0

    assert fake_model.last_verbose == 0

    assert (
        result.classification
        == ChestXrayClassification.PNEUMONIA
    )

    assert result.pneumonia_probability == pytest.approx(
        0.90,
        abs=1e-6,
    )

    assert result.normal_probability == pytest.approx(
        0.10,
        abs=1e-6,
    )

    assert result.confidence == pytest.approx(
        0.90,
        abs=1e-6,
    )


def test_normal_prediction(xray_image):
    fake_model = FakeModel(0.20)

    engine = ChestXrayModel(
        model=fake_model,
    )

    result = engine.predict(xray_image)

    assert (
        result.classification
        == ChestXrayClassification.NORMAL
    )

    assert result.pneumonia_probability == pytest.approx(
        0.20,
        abs=1e-6,
    )

    assert result.normal_probability == pytest.approx(
        0.80,
        abs=1e-6,
    )

    assert result.confidence == pytest.approx(
        0.80,
        abs=1e-6,
    )


def test_threshold_exactly_half_is_normal(xray_image):
    fake_model = FakeModel(0.50)

    engine = ChestXrayModel(
        model=fake_model,
    )

    result = engine.predict(xray_image)

    assert (
        result.classification
        == ChestXrayClassification.NORMAL
    )


def test_missing_image_raises_input_error(tmp_path):
    engine = ChestXrayModel(
        model=FakeModel(0.5),
    )

    missing_path = tmp_path / "missing.png"

    with pytest.raises(
        ChestXrayInputError,
        match="image not found",
    ):
        engine.predict(missing_path)

def test_model_warm_up_uses_expected_batch():
    fake_model = FakeModel(0.5)

    engine = ChestXrayModel(
        model=fake_model,
    )

    latency_ms = engine.warm_up()

    assert fake_model.last_batch.shape == (
        1,
        384,
        384,
        3,
    )

    assert fake_model.last_batch.dtype == np.float32

    assert fake_model.last_verbose == 0

    assert latency_ms >= 0.0        