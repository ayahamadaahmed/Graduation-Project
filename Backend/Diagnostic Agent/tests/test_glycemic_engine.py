from src.diagnostics.glycemic_engine import (
    GlycemicAnalyzer,
    GlycemicPattern,
)

from src.diagnostics.lab_types import (
    LabFlag,
    LabValue,
)


def test_glucose_above_report_reference():
    analyzer = GlycemicAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="fasting_glucose",
                value=120,
                unit="mg/dL",
                reference_min=70,
                reference_max=99,
            )
        ]
    )

    assert (
        result.findings[0].flag
        == LabFlag.HIGH
    )

    assert (
        GlycemicPattern.GLUCOSE_ABOVE_REFERENCE
        in result.patterns
    )


def test_glucose_within_reference():
    analyzer = GlycemicAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="fasting_glucose",
                value=90,
                unit="mg/dL",
                reference_min=70,
                reference_max=99,
            )
        ]
    )

    assert (
        result.findings[0].flag
        == LabFlag.NORMAL
    )

    assert (
        GlycemicPattern.ALL_WITHIN_REFERENCE
        in result.patterns
    )


def test_hba1c_above_reference():
    analyzer = GlycemicAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="hba1c",
                value=7.0,
                unit="%",
                reference_min=4.0,
                reference_max=5.6,
            )
        ]
    )

    assert (
        result.findings[0].flag
        == LabFlag.HIGH
    )

    assert (
        GlycemicPattern.HBA1C_ABOVE_REFERENCE
        in result.patterns
    )


def test_multiple_abnormal_results():
    analyzer = GlycemicAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="fasting_glucose",
                value=130,
                unit="mg/dL",
                reference_min=70,
                reference_max=99,
            ),
            LabValue(
                name="hba1c",
                value=7.0,
                unit="%",
                reference_min=4,
                reference_max=5.6,
            ),
        ]
    )

    assert len(
        result.abnormal_findings
    ) == 2

    assert (
        GlycemicPattern.MULTIPLE_ABNORMAL
        in result.patterns
    )


def test_missing_reference_range_is_unknown():
    analyzer = GlycemicAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="hba1c",
                value=6.0,
                unit="%",
            )
        ]
    )

    assert (
        result.findings[0].flag
        == LabFlag.UNKNOWN
    )

    assert (
        GlycemicPattern.INSUFFICIENT_DATA
        in result.patterns
    )


def test_no_supported_tests_is_insufficient():
    analyzer = GlycemicAnalyzer()

    result = analyzer.analyze([])

    assert (
        GlycemicPattern.INSUFFICIENT_DATA
        in result.patterns
    )