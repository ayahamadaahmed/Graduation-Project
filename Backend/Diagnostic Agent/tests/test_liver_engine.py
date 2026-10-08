from src.diagnostics.lab_types import (
    LabFlag,
    LabValue,
)

from src.diagnostics.liver_engine import (
    LiverAnalyzer,
    LiverPattern,
)


def test_alt_above_reference():
    analyzer = LiverAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="alt",
                value=70,
                unit="U/L",
                reference_min=0,
                reference_max=40,
            )
        ]
    )

    assert (
        result.findings[0].flag
        == LabFlag.HIGH
    )

    assert (
        LiverPattern.ALT_ABOVE_REFERENCE
        in result.patterns
    )


def test_ast_within_reference():
    analyzer = LiverAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="ast",
                value=25,
                unit="U/L",
                reference_min=0,
                reference_max=40,
            )
        ]
    )

    assert (
        LiverPattern.ALL_WITHIN_REFERENCE
        in result.patterns
    )


def test_bilirubin_above_reference():
    analyzer = LiverAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="total_bilirubin",
                value=2.0,
                unit="mg/dL",
                reference_min=0.2,
                reference_max=1.2,
            )
        ]
    )

    assert (
        LiverPattern.BILIRUBIN_ABOVE_REFERENCE
        in result.patterns
    )


def test_albumin_below_reference():
    analyzer = LiverAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="albumin",
                value=2.8,
                unit="g/dL",
                reference_min=3.5,
                reference_max=5.0,
            )
        ]
    )

    assert (
        result.findings[0].flag
        == LabFlag.LOW
    )

    assert (
        LiverPattern.ALBUMIN_BELOW_REFERENCE
        in result.patterns
    )


def test_multiple_abnormal_results():
    analyzer = LiverAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="alt",
                value=70,
                unit="U/L",
                reference_min=0,
                reference_max=40,
            ),
            LabValue(
                name="ast",
                value=80,
                unit="U/L",
                reference_min=0,
                reference_max=40,
            ),
        ]
    )

    assert len(
        result.abnormal_findings
    ) == 2

    assert (
        LiverPattern.MULTIPLE_ABNORMAL
        in result.patterns
    )


def test_missing_reference_is_unknown():
    analyzer = LiverAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="alt",
                value=50,
                unit="U/L",
            )
        ]
    )

    assert (
        result.findings[0].flag
        == LabFlag.UNKNOWN
    )

    assert (
        LiverPattern.INSUFFICIENT_DATA
        in result.patterns
    )


def test_no_liver_tests():
    analyzer = LiverAnalyzer()

    result = analyzer.analyze([])

    assert (
        LiverPattern.INSUFFICIENT_DATA
        in result.patterns
    )

def test_alp_below_reference_is_not_insufficient():
    analyzer = LiverAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="alp",
                value=11,
                unit="U/L",
                reference_min=40,
                reference_max=130,
            )
        ]
    )

    assert (
        result.findings[0].flag
        == LabFlag.LOW
    )

    assert (
        LiverPattern.OUTSIDE_REFERENCE_RANGE
        in result.patterns
    )

    assert (
        LiverPattern.INSUFFICIENT_DATA
        not in result.patterns
    )    

def test_partial_reference_data():
    analyzer = LiverAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="alt",
                value=36,
                unit="U/L",
                reference_min=13,
                reference_max=40,
            ),
            LabValue(
                name="alp",
                value=11,
                unit="U/L",
            ),
        ]
    )

    assert (
        LiverPattern.PARTIAL_REFERENCE_DATA
        in result.patterns
    )


def test_all_unknown_is_still_insufficient():
    analyzer = LiverAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="alp",
                value=11,
                unit="U/L",
            )
        ]
    )

    assert (
        LiverPattern.INSUFFICIENT_DATA
        in result.patterns
    )    