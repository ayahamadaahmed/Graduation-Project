import pytest

from src.diagnostics.radiology.kidney_ct_types import (
    KidneyCtClassification,
    KidneyCtResult,
)


def test_kidney_ct_result_valid():
    result = KidneyCtResult(
        classification=KidneyCtClassification.STONE,
        cyst_probability=0.05,
        normal_probability=0.10,
        stone_probability=0.80,
        tumor_probability=0.05,
        confidence=0.80,
        inference_latency_ms=120.0,
        model_name="medmind-kidney-ct-efficientnetb0",
        model_version="v1",
    )

    assert result.classification == KidneyCtClassification.STONE

    assert result.probabilities == {
        "cyst": 0.05,
        "normal": 0.10,
        "stone": 0.80,
        "tumor": 0.05,
    }

    assert result.modality == "kidney_ct"


def test_kidney_ct_rejects_invalid_probability_sum():
    with pytest.raises(
        ValueError,
        match="must sum to 1.0",
    ):
        KidneyCtResult(
            classification=KidneyCtClassification.CYST,
            cyst_probability=0.70,
            normal_probability=0.20,
            stone_probability=0.20,
            tumor_probability=0.10,
            confidence=0.70,
            inference_latency_ms=100.0,
            model_name="medmind-kidney-ct-efficientnetb0",
            model_version="v1",
        )


def test_kidney_ct_rejects_wrong_confidence():
    with pytest.raises(
        ValueError,
        match="highest class probability",
    ):
        KidneyCtResult(
            classification=KidneyCtClassification.NORMAL,
            cyst_probability=0.10,
            normal_probability=0.70,
            stone_probability=0.10,
            tumor_probability=0.10,
            confidence=0.50,
            inference_latency_ms=100.0,
            model_name="medmind-kidney-ct-efficientnetb0",
            model_version="v1",
        )


def test_kidney_ct_rejects_classification_mismatch():
    with pytest.raises(
        ValueError,
        match="classification must match",
    ):
        KidneyCtResult(
            classification=KidneyCtClassification.CYST,
            cyst_probability=0.10,
            normal_probability=0.10,
            stone_probability=0.70,
            tumor_probability=0.10,
            confidence=0.70,
            inference_latency_ms=100.0,
            model_name="medmind-kidney-ct-efficientnetb0",
            model_version="v1",
        )


def test_kidney_ct_rejects_negative_latency():
    with pytest.raises(
        ValueError,
        match="non-negative",
    ):
        KidneyCtResult(
            classification=KidneyCtClassification.TUMOR,
            cyst_probability=0.05,
            normal_probability=0.05,
            stone_probability=0.05,
            tumor_probability=0.85,
            confidence=0.85,
            inference_latency_ms=-1.0,
            model_name="medmind-kidney-ct-efficientnetb0",
            model_version="v1",
        )