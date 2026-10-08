from src.diagnostics.lab_types import (
    LabFlag,
    LabValue,
)

from src.diagnostics.lipid_engine import (
    LipidAnalyzer,
    LipidPattern,
)


def test_total_cholesterol_above_reference():
    analyzer = LipidAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="total_cholesterol",
                value=230,
                unit="mg/dL",
                reference_min=0,
                reference_max=200,
            )
        ]
    )

    assert result.findings[0].flag == LabFlag.HIGH

    assert (
        LipidPattern.TOTAL_CHOLESTEROL_ABOVE_REFERENCE
        in result.patterns
    )


def test_ldl_above_reference():
    analyzer = LipidAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="ldl",
                value=150,
                unit="mg/dL",
                reference_min=0,
                reference_max=130,
            )
        ]
    )

    assert (
        LipidPattern.LDL_ABOVE_REFERENCE
        in result.patterns
    )


def test_hdl_below_reference():
    analyzer = LipidAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="hdl",
                value=35,
                unit="mg/dL",
                reference_min=40,
                reference_max=None,
            )
        ]
    )

    assert result.findings[0].flag == LabFlag.LOW

    assert (
        LipidPattern.HDL_BELOW_REFERENCE
        in result.patterns
    )


def test_triglycerides_above_reference():
    analyzer = LipidAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="triglycerides",
                value=200,
                unit="mg/dL",
                reference_min=0,
                reference_max=150,
            )
        ]
    )

    assert (
        LipidPattern.TRIGLYCERIDES_ABOVE_REFERENCE
        in result.patterns
    )


def test_all_within_reference():
    analyzer = LipidAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="total_cholesterol",
                value=180,
                unit="mg/dL",
                reference_min=0,
                reference_max=200,
            ),
            LabValue(
                name="ldl",
                value=100,
                unit="mg/dL",
                reference_min=0,
                reference_max=130,
            ),
        ]
    )

    assert (
        LipidPattern.ALL_WITHIN_REFERENCE
        in result.patterns
    )


def test_multiple_abnormal_results():
    analyzer = LipidAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="ldl",
                value=150,
                unit="mg/dL",
                reference_min=0,
                reference_max=130,
            ),
            LabValue(
                name="hdl",
                value=35,
                unit="mg/dL",
                reference_min=40,
                reference_max=None,
            ),
        ]
    )

    assert len(result.abnormal_findings) == 2

    assert (
        LipidPattern.MULTIPLE_ABNORMAL
        in result.patterns
    )


def test_partial_reference_data():
    analyzer = LipidAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="ldl",
                value=100,
                unit="mg/dL",
                reference_min=0,
                reference_max=130,
            ),
            LabValue(
                name="vldl",
                value=20,
                unit="mg/dL",
            ),
        ]
    )

    assert (
        LipidPattern.PARTIAL_REFERENCE_DATA
        in result.patterns
    )


def test_no_lipid_tests():
    analyzer = LipidAnalyzer()

    result = analyzer.analyze([])

    assert (
        LipidPattern.INSUFFICIENT_DATA
        in result.patterns
    )

def test_derived_ratio_does_not_drive_pattern():
    analyzer = LipidAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="total_cholesterol",
                value=180,
                unit="mg/dL",
                reference_min=0,
                reference_max=200,
            ),
            LabValue(
                name="total_cholesterol_hdl_ratio",
                value=3.27,
                unit="",
                reference_min=4,
                reference_max=6,
            ),
        ]
    )

    assert (
        LipidPattern.ALL_WITHIN_REFERENCE
        in result.patterns
    )

    assert (
        LipidPattern.OUTSIDE_REFERENCE_RANGE
        not in result.patterns
    )    