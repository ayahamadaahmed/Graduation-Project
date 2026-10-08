import pytest

from src.diagnostics.radiology.brain_mri_types import (
    BrainMriClassification,
    BrainMriResult,
)


def test_brain_mri_result_valid_glioma():
    result = BrainMriResult(
        classification=BrainMriClassification.GLIOMA,
        glioma_probability=0.70,
        meningioma_probability=0.10,
        notumor_probability=0.15,
        pituitary_probability=0.05,
        confidence=0.70,
        inference_latency_ms=200.0,
        model_name="medmind-brain-mri-efficientnetb0",
        model_version="v1",
    )

    assert (
        result.classification
        == BrainMriClassification.GLIOMA
    )

    assert result.probabilities == {
        "glioma": 0.70,
        "meningioma": 0.10,
        "notumor": 0.15,
        "pituitary": 0.05,
    }

    assert result.confidence == 0.70
    assert result.modality == "brain_mri"


def test_brain_mri_result_rejects_invalid_probability_sum():
    with pytest.raises(
        ValueError,
        match="must sum to 1.0",
    ):
        BrainMriResult(
            classification=BrainMriClassification.GLIOMA,
            glioma_probability=0.70,
            meningioma_probability=0.20,
            notumor_probability=0.20,
            pituitary_probability=0.10,
            confidence=0.70,
            inference_latency_ms=200.0,
            model_name="medmind-brain-mri-efficientnetb0",
            model_version="v1",
        )


def test_brain_mri_result_rejects_wrong_confidence():
    with pytest.raises(
        ValueError,
        match="highest class probability",
    ):
        BrainMriResult(
            classification=BrainMriClassification.MENINGIOMA,
            glioma_probability=0.10,
            meningioma_probability=0.70,
            notumor_probability=0.10,
            pituitary_probability=0.10,
            confidence=0.50,
            inference_latency_ms=200.0,
            model_name="medmind-brain-mri-efficientnetb0",
            model_version="v1",
        )


def test_brain_mri_result_rejects_classification_mismatch():
    with pytest.raises(
        ValueError,
        match="classification must match",
    ):
        BrainMriResult(
            classification=BrainMriClassification.GLIOMA,
            glioma_probability=0.10,
            meningioma_probability=0.70,
            notumor_probability=0.10,
            pituitary_probability=0.10,
            confidence=0.70,
            inference_latency_ms=200.0,
            model_name="medmind-brain-mri-efficientnetb0",
            model_version="v1",
        )


def test_brain_mri_result_rejects_negative_latency():
    with pytest.raises(
        ValueError,
        match="non-negative",
    ):
        BrainMriResult(
            classification=BrainMriClassification.NO_TUMOR,
            glioma_probability=0.05,
            meningioma_probability=0.05,
            notumor_probability=0.85,
            pituitary_probability=0.05,
            confidence=0.85,
            inference_latency_ms=-1.0,
            model_name="medmind-brain-mri-efficientnetb0",
            model_version="v1",
        )