from src.diagnostics.lab_image_extractor import (
    ExtractedLabReport,
    ExtractedLabValue,
)

from src.diagnostics.pathology_processor import (
    PathologyProcessor,
)


def test_mixed_lab_report_routes_to_correct_engines():
    report = ExtractedLabReport(
        document_type="mixed_lab_report",
        results=[
            ExtractedLabValue(
                raw_name="HGB",
                value=12,
                unit="g/dL",
                reference_min=11,
                reference_max=16,
            ),
            ExtractedLabValue(
                raw_name="MCV",
                value=85,
                unit="fL",
                reference_min=80,
                reference_max=100,
            ),
            ExtractedLabValue(
                raw_name="WBC",
                value=7,
                unit="10^3/uL",
                reference_min=4,
                reference_max=11,
            ),
            ExtractedLabValue(
                raw_name="PLT",
                value=250,
                unit="10^3/uL",
                reference_min=150,
                reference_max=450,
            ),
            ExtractedLabValue(
                raw_name="HbA1c",
                value=5.4,
                unit="%",
                reference_min=4,
                reference_max=5.6,
            ),
            ExtractedLabValue(
                raw_name="Serum Creatinine",
                value=0.9,
                unit="mg/dL",
                reference_min=0.6,
                reference_max=1.2,
            ),
            ExtractedLabValue(
                raw_name="SGPT (ALT)",
                value=30,
                unit="U/L",
                reference_min=0,
                reference_max=40,
            ),
            ExtractedLabValue(
                raw_name="LDL-C",
                value=100,
                unit="mg/dL",
                reference_min=0,
                reference_max=130,
            ),
        ],
    )

    processor = PathologyProcessor()

    result = processor.process(
        report
    )

    assert result.cbc is not None
    assert result.glycemic is not None
    assert result.renal is not None
    assert result.liver is not None
    assert result.lipid is not None

    assert set(
        result.detected_panels
    ) == {
        "cbc",
        "glycemic",
        "renal",
        "liver",
        "lipid",
    }

    assert result.unmapped_tests == []

    hgb_trace = next(
        trace
        for trace in result.value_traces
        if trace.raw_name == "HGB"
    )
    assert hgb_trace.flag == "normal"

    assert hgb_trace.panel == "cbc"

    assert (
        hgb_trace.canonical_name
        == "hemoglobin"
    )

    assert hgb_trace.value == 12

    assert (
        hgb_trace.mapping_status
        == "mapped"
    )


def test_unknown_test_is_preserved():
    report = ExtractedLabReport(
        document_type="mixed",
        results=[
            ExtractedLabValue(
                raw_name="Unknown Test XYZ",
                value=10,
                unit="unit",
            )
        ],
    )

    result = PathologyProcessor().process(
        report
    )

    assert result.detected_panels == []

    assert result.unmapped_tests == [
        "Unknown Test XYZ"
    ]

    assert len(
        result.value_traces
    ) == 1

    trace = result.value_traces[0]

    assert (
        trace.raw_name
        == "Unknown Test XYZ"
    )

    assert trace.panel is None

    assert trace.canonical_name is None

    assert trace.value == 10

    assert trace.unit == "unit"

    assert (
        trace.mapping_status
        == "unmapped"
    )
    assert trace.flag == "unknown"


def test_unreadable_recognized_test_is_tracked():
    report = ExtractedLabReport(
        document_type="lab",
        results=[
            ExtractedLabValue(
                raw_name="HbA1c",
                value=None,
                unit="%",
                reference_min=4,
                reference_max=5.6,
            )
        ],
    )

    result = PathologyProcessor().process(
        report
    )

    assert "HbA1c" in result.skipped_unreadable

    assert "HbA1c" not in result.unmapped_tests

    trace = result.value_traces[0]

    assert trace.raw_name == "HbA1c"

    assert trace.panel == "glycemic"

    assert (
        trace.canonical_name
        == "hba1c"
    )

    assert trace.value is None

    assert (
        trace.mapping_status
        == "unreadable"
    )
    assert trace.flag == "unknown"