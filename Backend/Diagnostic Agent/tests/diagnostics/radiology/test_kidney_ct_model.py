import numpy as np
import pytest
from PIL import Image

from src.diagnostics.radiology.kidney_ct_model import (
    KidneyCtInputError,
    KidneyCtModel,
    KidneyCtModelError,
)
from src.diagnostics.radiology.kidney_ct_types import (
    KidneyCtClassification,
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
def kidney_ct_image(tmp_path):
    image_path = tmp_path / "kidney_ct.png"

    image = Image.new(
        "L",
        (140, 180),
        color=255,
    )

    image.save(image_path)

    return image_path


def test_preprocessing_and_cyst_prediction(
    kidney_ct_image,
):
    fake_model = FakeModel(
        [0.80, 0.10, 0.05, 0.05]
    )

    engine = KidneyCtModel(
        model=fake_model,
    )

    result = engine.predict(
        kidney_ct_image
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
        == KidneyCtClassification.CYST
    )

    assert (
        result.cyst_probability
        == pytest.approx(0.80, abs=1e-6)
    )

    assert (
        result.confidence
        == pytest.approx(0.80, abs=1e-6)
    )


def test_normal_prediction(
    kidney_ct_image,
):
    fake_model = FakeModel(
        [0.05, 0.90, 0.03, 0.02]
    )

    engine = KidneyCtModel(
        model=fake_model,
    )

    result = engine.predict(
        kidney_ct_image
    )

    assert (
        result.classification
        == KidneyCtClassification.NORMAL
    )


def test_stone_prediction(
    kidney_ct_image,
):
    fake_model = FakeModel(
        [0.05, 0.05, 0.85, 0.05]
    )

    engine = KidneyCtModel(
        model=fake_model,
    )

    result = engine.predict(
        kidney_ct_image
    )

    assert (
        result.classification
        == KidneyCtClassification.STONE
    )


def test_tumor_prediction(
    kidney_ct_image,
):
    fake_model = FakeModel(
        [0.05, 0.05, 0.10, 0.80]
    )

    engine = KidneyCtModel(
        model=fake_model,
    )

    result = engine.predict(
        kidney_ct_image
    )

    assert (
        result.classification
        == KidneyCtClassification.TUMOR
    )


def test_invalid_output_size_raises_model_error(
    kidney_ct_image,
):
    fake_model = FakeModel(
        [0.50, 0.50]
    )

    engine = KidneyCtModel(
        model=fake_model,
    )

    with pytest.raises(
        KidneyCtModelError,
        match="Expected 4 probabilities",
    ):
        engine.predict(
            kidney_ct_image
        )


def test_invalid_probability_sum_raises_model_error(
    kidney_ct_image,
):
    fake_model = FakeModel(
        [0.40, 0.40, 0.40, 0.40]
    )

    engine = KidneyCtModel(
        model=fake_model,
    )

    with pytest.raises(
        KidneyCtModelError,
        match="must sum to 1.0",
    ):
        engine.predict(
            kidney_ct_image
        )


def test_missing_image_raises_input_error(
    tmp_path,
):
    engine = KidneyCtModel(
        model=FakeModel(
            [0.25, 0.25, 0.25, 0.25]
        ),
    )

    missing_path = (
        tmp_path / "missing.png"
    )

    with pytest.raises(
        KidneyCtInputError,
        match="image not found",
    ):
        engine.predict(
            missing_path
        )


def test_model_warm_up_uses_expected_batch():
    fake_model = FakeModel(
        [0.25, 0.25, 0.25, 0.25]
    )

    engine = KidneyCtModel(
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