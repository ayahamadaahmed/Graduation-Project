import numpy as np
import pytest
from PIL import Image

from src.diagnostics.radiology.brain_mri_model import (
    BrainMriInputError,
    BrainMriModel,
    BrainMriModelError,
)
from src.diagnostics.radiology.brain_mri_types import (
    BrainMriClassification,
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
            [self.output],
            dtype=np.float32,
        )


@pytest.fixture
def brain_mri_image(tmp_path):
    image_path = tmp_path / "brain_mri.png"

    image = Image.new(
        "L",
        (120, 180),
        color=255,
    )

    image.save(image_path)

    return image_path


def test_preprocessing_and_glioma_prediction(
    brain_mri_image,
):
    fake_model = FakeModel(
        [0.70, 0.10, 0.15, 0.05]
    )

    engine = BrainMriModel(
        model=fake_model,
    )

    result = engine.predict(
        brain_mri_image
    )

    assert fake_model.last_batch.shape == (
        1,
        224,
        224,
        3,
    )

    assert (
        fake_model.last_batch.dtype
        == np.float32
    )

    assert (
        fake_model.last_batch.max()
        == 255.0
    )

    assert fake_model.last_verbose == 0

    assert (
        result.classification
        == BrainMriClassification.GLIOMA
    )

    assert (
        result.glioma_probability
        == pytest.approx(0.70, abs=1e-6)
    )

    assert (
        result.confidence
        == pytest.approx(0.70, abs=1e-6)
    )


def test_notumor_prediction(
    brain_mri_image,
):
    fake_model = FakeModel(
        [0.02, 0.03, 0.90, 0.05]
    )

    engine = BrainMriModel(
        model=fake_model,
    )

    result = engine.predict(
        brain_mri_image
    )

    assert (
        result.classification
        == BrainMriClassification.NO_TUMOR
    )

    assert (
        result.notumor_probability
        == pytest.approx(0.90, abs=1e-6)
    )


def test_pituitary_prediction(
    brain_mri_image,
):
    fake_model = FakeModel(
        [0.02, 0.03, 0.05, 0.90]
    )

    engine = BrainMriModel(
        model=fake_model,
    )

    result = engine.predict(
        brain_mri_image
    )

    assert (
        result.classification
        == BrainMriClassification.PITUITARY
    )


def test_invalid_output_size_raises_model_error(
    brain_mri_image,
):
    fake_model = FakeModel(
        [0.50, 0.50]
    )

    engine = BrainMriModel(
        model=fake_model,
    )

    with pytest.raises(
        BrainMriModelError,
        match="Expected 4 probabilities",
    ):
        engine.predict(
            brain_mri_image
        )


def test_invalid_probability_sum_raises_model_error(
    brain_mri_image,
):
    fake_model = FakeModel(
        [0.40, 0.40, 0.40, 0.40]
    )

    engine = BrainMriModel(
        model=fake_model,
    )

    with pytest.raises(
        BrainMriModelError,
        match="must sum to 1.0",
    ):
        engine.predict(
            brain_mri_image
        )


def test_missing_image_raises_input_error(
    tmp_path,
):
    engine = BrainMriModel(
        model=FakeModel(
            [0.25, 0.25, 0.25, 0.25]
        ),
    )

    missing_path = (
        tmp_path / "missing.png"
    )

    with pytest.raises(
        BrainMriInputError,
        match="image not found",
    ):
        engine.predict(
            missing_path
        )


def test_model_warm_up_uses_expected_batch():
    fake_model = FakeModel(
        [0.25, 0.25, 0.25, 0.25]
    )

    engine = BrainMriModel(
        model=fake_model,
    )

    latency_ms = engine.warm_up()

    assert fake_model.last_batch.shape == (
        1,
        224,
        224,
        3,
    )

    assert (
        fake_model.last_batch.dtype
        == np.float32
    )

    assert fake_model.last_verbose == 0

    assert latency_ms >= 0.0