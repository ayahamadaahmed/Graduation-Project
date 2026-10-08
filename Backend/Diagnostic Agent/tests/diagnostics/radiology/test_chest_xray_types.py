import pytest

from src.diagnostics.radiology.chest_xray_types import (
    ChestXrayClassification,
    ChestXrayResult,
)


def test_chest_xray_result_valid_pneumonia():
    result = ChestXrayResult(
        classification=ChestXrayClassification.PNEUMONIA,
        normal_probability=0.10,
        pneumonia_probability=0.90,
        confidence=0.90,
        inference_latency_ms=315.5,
        model_name="mediscan-efficientnetb3-pneumonia",
        model_version="x-ray.keras",
    )

    assert result.classification == ChestXrayClassification.PNEUMONIA
    assert result.probabilities == {
        "normal": 0.10,
        "pneumonia": 0.90,
    }
    assert result.confidence == 0.90
    assert result.modality == "chest_xray"


def test_chest_xray_result_rejects_invalid_probability_sum():
    with pytest.raises(
        ValueError,
        match="must sum to 1.0",
    ):
        ChestXrayResult(
            classification=ChestXrayClassification.NORMAL,
            normal_probability=0.80,
            pneumonia_probability=0.40,
            confidence=0.80,
            inference_latency_ms=250.0,
            model_name="mediscan-efficientnetb3-pneumonia",
            model_version="x-ray.keras",
        )


def test_chest_xray_result_rejects_wrong_confidence():
    with pytest.raises(
        ValueError,
        match="highest class probability",
    ):
        ChestXrayResult(
            classification=ChestXrayClassification.PNEUMONIA,
            normal_probability=0.20,
            pneumonia_probability=0.80,
            confidence=0.60,
            inference_latency_ms=250.0,
            model_name="mediscan-efficientnetb3-pneumonia",
            model_version="x-ray.keras",
        )


def test_chest_xray_result_rejects_negative_latency():
    with pytest.raises(
        ValueError,
        match="non-negative",
    ):
        ChestXrayResult(
            classification=ChestXrayClassification.NORMAL,
            normal_probability=0.90,
            pneumonia_probability=0.10,
            confidence=0.90,
            inference_latency_ms=-1.0,
            model_name="mediscan-efficientnetb3-pneumonia",
            model_version="x-ray.keras",
        )