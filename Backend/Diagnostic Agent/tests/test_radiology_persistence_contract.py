import pytest

from src.diagnostics.radiology.radiology_assessment import (
    RadiologyAssessment,
)

from src.diagnostics.radiology.radiology_persistence_contract import (
    RadiologyPersistenceContractBuilder,
    RadiologyPersistenceContractError,
)

from src.diagnostics.radiology.radiology_processor import (
    RadiologyModality,
)


def make_assessment():

    return RadiologyAssessment(
        modality=(
            RadiologyModality.CHEST_XRAY
        ),

        classification="normal",

        probabilities={
            "normal": 0.7836,
            "pneumonia": 0.2164,
        },

        confidence=0.7836,

        inference_latency_ms=271.4,

        model_name=(
            "medmind_chest_xray"
        ),

        model_version="1.0",

        limitations=(
            (
                "Decision-support "
                "classification only."
            ),
        ),
    )


def test_builds_radiology_persistence_contract():

    assessment = make_assessment()

    contract = (
        RadiologyPersistenceContractBuilder()
        .build(
            assessment=assessment
        )
    )

    assert (
        contract.schema_version
        == "1.0"
    )

    assert (
        contract.modality
        == "chest_xray"
    )

    assert (
        contract.classification
        == "normal"
    )

    assert contract.probabilities == {
        "normal": 0.7836,
        "pneumonia": 0.2164,
    }

    assert (
        contract.confidence
        == 0.7836
    )

    assert (
        contract.inference_latency_ms
        == 271.4
    )

    assert (
        contract.model_name
        == "medmind_chest_xray"
    )

    assert (
        contract.model_version
        == "1.0"
    )

    assert contract.limitations == [
        (
            "Decision-support "
            "classification only."
        )
    ]


def test_contract_copies_mutable_values():

    assessment = make_assessment()

    contract = (
        RadiologyPersistenceContractBuilder()
        .build(
            assessment=assessment
        )
    )

    contract.probabilities[
        "normal"
    ] = 0.1

    contract.limitations.append(
        "test"
    )

    assert (
        assessment.probabilities[
            "normal"
        ]
        == 0.7836
    )

    assert (
        "test"
        not in assessment.limitations
    )


def test_rejects_classification_missing_from_probabilities():

    assessment = RadiologyAssessment(
        modality=(
            RadiologyModality.CHEST_XRAY
        ),

        classification="normal",

        probabilities={
            "pneumonia": 1.0,
        },

        confidence=1.0,

        inference_latency_ms=100.0,

        model_name="model",

        model_version="1.0",

        limitations=(),
    )

    with pytest.raises(
        RadiologyPersistenceContractError
    ):
        (
            RadiologyPersistenceContractBuilder()
            .build(
                assessment=assessment
            )
        )