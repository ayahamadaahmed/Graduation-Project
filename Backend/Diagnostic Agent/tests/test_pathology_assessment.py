from src.diagnostics.lab_image_extractor import (
    ExtractedLabReport,
    ExtractedLabValue,
)

from src.diagnostics.pathology_assessment import (
    PathologyAssessmentBuilder,
)

from src.diagnostics.pathology_processor import (
    PathologyProcessor,
)


def test_builds_unified_pathology_assessment():
    report = ExtractedLabReport(
        document_type="mixed",
        results=[
            ExtractedLabValue(
                raw_name="HGB",
                value=10,
                unit="g/dL",
                reference_min=12,
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
        ],
    )

    processing = PathologyProcessor().process(
        report
    )

    assessment = (
        PathologyAssessmentBuilder()
        .build(processing)
    )

    assert set(
        assessment.detected_panels
    ) == {
        "cbc",
        "glycemic",
    }

    abnormal_names = {
        finding.name
        for finding
        in assessment.abnormal_findings
    }

    assert "hemoglobin" in abnormal_names

    normal_names = {
        finding.name
        for finding
        in assessment.normal_findings
    }

    assert "hba1c" in normal_names


def test_unknown_reference_is_preserved():
    report = ExtractedLabReport(
        document_type="lft",
        results=[
            ExtractedLabValue(
                raw_name="SERUM ALKALINE PHOSPHATASE",
                value=11,
                unit="U/L",
                reference_min=None,
                reference_max=None,
            )
        ],
    )

    processing = PathologyProcessor().process(
        report
    )

    assessment = (
        PathologyAssessmentBuilder()
        .build(processing)
    )

    assert len(
        assessment.unknown_findings
    ) == 1

    assert (
        assessment.unknown_findings[0].name
        == "alp"
    )


def test_unmapped_test_is_preserved():
    report = ExtractedLabReport(
        document_type="lab",
        results=[
            ExtractedLabValue(
                raw_name="UNKNOWN XYZ",
                value=10,
                unit="unit",
            )
        ],
    )

    processing = PathologyProcessor().process(
        report
    )

    assessment = (
        PathologyAssessmentBuilder()
        .build(processing)
    )

    assert assessment.unmapped_tests == [
        "UNKNOWN XYZ"
    ]