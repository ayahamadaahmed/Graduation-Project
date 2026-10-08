import pytest

from src.diagnostics.radiology.brain_mri_types import (
    BrainMriClassification,
    BrainMriResult,
)
from src.diagnostics.radiology.chest_xray_types import (
    ChestXrayClassification,
    ChestXrayResult,
)
from src.diagnostics.radiology.kidney_ct_types import (
    KidneyCtClassification,
    KidneyCtResult,
)
from src.diagnostics.radiology.radiology_processor import (
    RadiologyModality,
    RadiologyProcessor,
    UnsupportedRadiologyModalityError,
)


class FakeModel:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def predict(self, image_path):
        self.calls.append(image_path)
        return self.result


def make_chest_result():
    return ChestXrayResult(
        classification=ChestXrayClassification.NORMAL,
        normal_probability=0.90,
        pneumonia_probability=0.10,
        confidence=0.90,
        inference_latency_ms=100.0,
        model_name="test-chest",
        model_version="v1",
    )


def make_brain_result():
    return BrainMriResult(
        classification=BrainMriClassification.NO_TUMOR,
        glioma_probability=0.05,
        meningioma_probability=0.05,
        notumor_probability=0.85,
        pituitary_probability=0.05,
        confidence=0.85,
        inference_latency_ms=100.0,
        model_name="test-brain",
        model_version="v1",
    )


def make_kidney_result():
    return KidneyCtResult(
        classification=KidneyCtClassification.NORMAL,
        cyst_probability=0.05,
        normal_probability=0.85,
        stone_probability=0.05,
        tumor_probability=0.05,
        confidence=0.85,
        inference_latency_ms=100.0,
        model_name="test-kidney",
        model_version="v1",
    )


def test_routes_chest_xray_to_chest_model_only():
    chest = FakeModel(make_chest_result())
    brain = FakeModel(make_brain_result())
    kidney = FakeModel(make_kidney_result())

    processor = RadiologyProcessor(
        chest_xray_model=chest,
        brain_mri_model=brain,
        kidney_ct_model=kidney,
    )

    result = processor.process(
        "patient.jpg",
        RadiologyModality.CHEST_XRAY,
    )

    assert result.modality == RadiologyModality.CHEST_XRAY
    assert result.result is chest.result

    assert chest.calls == ["patient.jpg"]
    assert brain.calls == []
    assert kidney.calls == []


def test_routes_brain_mri_from_string():
    chest = FakeModel(make_chest_result())
    brain = FakeModel(make_brain_result())
    kidney = FakeModel(make_kidney_result())

    processor = RadiologyProcessor(
        chest_xray_model=chest,
        brain_mri_model=brain,
        kidney_ct_model=kidney,
    )

    result = processor.process(
        "brain.jpg",
        " BRAIN_MRI ",
    )

    assert result.modality == RadiologyModality.BRAIN_MRI
    assert result.result is brain.result

    assert chest.calls == []
    assert brain.calls == ["brain.jpg"]
    assert kidney.calls == []


def test_routes_kidney_ct_to_kidney_model_only():
    chest = FakeModel(make_chest_result())
    brain = FakeModel(make_brain_result())
    kidney = FakeModel(make_kidney_result())

    processor = RadiologyProcessor(
        chest_xray_model=chest,
        brain_mri_model=brain,
        kidney_ct_model=kidney,
    )

    result = processor.process(
        "kidney.jpg",
        RadiologyModality.KIDNEY_CT,
    )

    assert result.modality == RadiologyModality.KIDNEY_CT
    assert result.result is kidney.result

    assert chest.calls == []
    assert brain.calls == []
    assert kidney.calls == ["kidney.jpg"]


def test_rejects_unsupported_modality():
    processor = RadiologyProcessor(
        chest_xray_model=FakeModel(make_chest_result()),
        brain_mri_model=FakeModel(make_brain_result()),
        kidney_ct_model=FakeModel(make_kidney_result()),
    )

    with pytest.raises(
        UnsupportedRadiologyModalityError,
        match="Unsupported radiology modality",
    ):
        processor.process(
            "image.jpg",
            "ultrasound",
        )