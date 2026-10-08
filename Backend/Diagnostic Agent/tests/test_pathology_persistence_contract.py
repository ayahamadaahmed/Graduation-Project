import pytest

from src.diagnostics.lab_image_extractor import (
    ExtractedLabReport,
    ExtractedLabValue,
)
from src.diagnostics.pathology_persistence_contract import (
    PathologyPersistenceContractBuilder,
    PathologyPersistenceContractError,
)
from src.diagnostics.pathology_processor import (
    PathologyProcessor,
)


def test_builds_persistence_contract_in_original_order():

    # Deliberately interleaved panels.
    report = ExtractedLabReport(
        document_type="mixed_lab_report",
        results=[
            ExtractedLabValue(
                raw_name="HbA1c",
                value=5.4,
                unit="%",
                reference_min=4,
                reference_max=5.6,
                reference_text="4 - 5.6",
            ),
            ExtractedLabValue(
                raw_name="HGB",
                value=10,
                unit="g/dL",
                reference_min=12,
                reference_max=16,
                reference_text="12 - 16",
            ),
            ExtractedLabValue(
                raw_name="Unknown XYZ",
                value=7,
                unit="unit",
            ),
            ExtractedLabValue(
                raw_name="Serum Creatinine",
                value=0.9,
                unit="mg/dL",
                reference_min=0.6,
                reference_max=1.2,
            ),
        ],
        unreadable_fields=[
            "patient_age",
        ],
    )

    processing = PathologyProcessor().process(
        report
    )

    contract = (
        PathologyPersistenceContractBuilder()
        .build(
            report=report,
            processing=processing,
        )
    )

    assert (
        contract.schema_version
        == "1.0"
    )

    assert (
        contract.document_type
        == "mixed_lab_report"
    )

    assert (
        contract.unreadable_fields
        == ["patient_age"]
    )

    assert [
        result["raw_name"]
        for result in contract.results
    ] == [
        "HbA1c",
        "HGB",
        "Unknown XYZ",
        "Serum Creatinine",
    ]

    assert [
        result["result_index"]
        for result in contract.results
    ] == [
        0,
        1,
        2,
        3,
    ]

    hba1c = contract.results[0]

    assert hba1c["panel"] == "glycemic"
    assert hba1c["canonical_name"] == "hba1c"
    assert hba1c["flag"] == "normal"
    assert hba1c["mapping_status"] == "mapped"

    hgb = contract.results[1]

    assert hgb["panel"] == "cbc"
    assert hgb["canonical_name"] == "hemoglobin"
    assert hgb["flag"] == "low"
    assert hgb["mapping_status"] == "mapped"

    unknown = contract.results[2]

    assert unknown["panel"] is None
    assert unknown["canonical_name"] is None
    assert unknown["flag"] == "unknown"
    assert (
        unknown["mapping_status"]
        == "unmapped"
    )


def test_unreadable_result_is_preserved():

    report = ExtractedLabReport(
        document_type="glycemic",
        results=[
            ExtractedLabValue(
                raw_name="HbA1c",
                value=None,
                unit="%",
                reference_min=4,
                reference_max=5.6,
            ),
        ],
    )

    processing = PathologyProcessor().process(
        report
    )

    contract = (
        PathologyPersistenceContractBuilder()
        .build(
            report=report,
            processing=processing,
        )
    )

    result = contract.results[0]

    assert result["value"] is None
    assert result["flag"] == "unknown"
    assert (
        result["mapping_status"]
        == "unreadable"
    )


def test_fails_if_processing_trace_is_missing():

    report = ExtractedLabReport(
        document_type="lab",
        results=[
            ExtractedLabValue(
                raw_name="Unknown XYZ",
                value=10,
                unit="unit",
            ),
        ],
    )

    processing = PathologyProcessor().process(
        report
    )

    processing.value_traces.clear()

    with pytest.raises(
        PathologyPersistenceContractError
    ):

        (
            PathologyPersistenceContractBuilder()
            .build(
                report=report,
                processing=processing,
            )
        )