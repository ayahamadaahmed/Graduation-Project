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
from src.diagnostics.radiology.radiology_assessment import (
    RadiologyAssessmentBuilder,
    RadiologyAssessmentError,
)
from src.diagnostics.radiology.radiology_processor import (
    RadiologyModality,
    RadiologyProcessorResult,
)


def test_builds_chest_xray_assessment():
    result = ChestXrayResult(
        classification=ChestXrayClassification.NORMAL,
        normal_probability=0.90,
        pneumonia_probability=0.10,
        confidence=0.90,
        inference_latency_ms=120.0,
        model_name="chest-model",
        model_version="v1",
    )

    processing = RadiologyProcessorResult(
        modality=RadiologyModality.CHEST_XRAY,
        result=result,
    )

    assessment = RadiologyAssessmentBuilder().build(
        processing
    )

    assert (
        assessment.modality
        == RadiologyModality.CHEST_XRAY
    )

    assert assessment.classification == "normal"

    assert assessment.probabilities == {
        "normal": 0.90,
        "pneumonia": 0.10,
    }

    assert assessment.confidence == 0.90


def test_builds_brain_mri_assessment():
    result = BrainMriResult(
        classification=BrainMriClassification.NO_TUMOR,
        glioma_probability=0.05,
        meningioma_probability=0.05,
        notumor_probability=0.85,
        pituitary_probability=0.05,
        confidence=0.85,
        inference_latency_ms=100.0,
        model_name="brain-model",
        model_version="v1",
    )

    processing = RadiologyProcessorResult(
        modality=RadiologyModality.BRAIN_MRI,
        result=result,
    )

    assessment = RadiologyAssessmentBuilder().build(
        processing
    )

    assert assessment.classification == "notumor"
    assert assessment.probabilities["notumor"] == 0.85


def test_builds_kidney_ct_assessment():
    result = KidneyCtResult(
        classification=KidneyCtClassification.STONE,
        cyst_probability=0.05,
        normal_probability=0.10,
        stone_probability=0.80,
        tumor_probability=0.05,
        confidence=0.80,
        inference_latency_ms=110.0,
        model_name="kidney-model",
        model_version="v1",
    )

    processing = RadiologyProcessorResult(
        modality=RadiologyModality.KIDNEY_CT,
        result=result,
    )

    assessment = RadiologyAssessmentBuilder().build(
        processing
    )

    assert assessment.classification == "stone"
    assert assessment.probabilities["stone"] == 0.80


def test_rejects_modality_mismatch():
    result = KidneyCtResult(
        classification=KidneyCtClassification.NORMAL,
        cyst_probability=0.05,
        normal_probability=0.85,
        stone_probability=0.05,
        tumor_probability=0.05,
        confidence=0.85,
        inference_latency_ms=100.0,
        model_name="kidney-model",
        model_version="v1",
    )

    processing = RadiologyProcessorResult(
        modality=RadiologyModality.BRAIN_MRI,
        result=result,
    )

    with pytest.raises(
        RadiologyAssessmentError,
        match="does not match",
    ):
        RadiologyAssessmentBuilder().build(
            processing
        )