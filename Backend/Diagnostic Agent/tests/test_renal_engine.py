from src.diagnostics.lab_types import (
    LabFlag,
    LabValue,
)

from src.diagnostics.renal_engine import (
    RenalAnalyzer,
    RenalPattern,
)


def test_creatinine_above_reference():
    analyzer = RenalAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="creatinine",
                value=1.8,
                unit="mg/dL",
                reference_min=0.6,
                reference_max=1.2,
            )
        ]
    )

    assert (
        result.findings[0].flag
        == LabFlag.HIGH
    )

    assert (
        RenalPattern.CREATININE_ABOVE_REFERENCE
        in result.patterns
    )


def test_creatinine_within_reference():
    analyzer = RenalAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="creatinine",
                value=0.9,
                unit="mg/dL",
                reference_min=0.6,
                reference_max=1.2,
            )
        ]
    )

    assert (
        RenalPattern.ALL_WITHIN_REFERENCE
        in result.patterns
    )


def test_egfr_lower_bound():
    analyzer = RenalAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="egfr",
                value=45,
                unit="mL/min/1.73m2",
                reference_min=60,
                reference_max=None,
            )
        ]
    )

    assert (
        result.findings[0].flag
        == LabFlag.LOW
    )

    assert (
        RenalPattern.EGFR_BELOW_REFERENCE
        in result.patterns
    )


def test_bun_above_reference():
    analyzer = RenalAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="bun",
                value=30,
                unit="mg/dL",
                reference_min=7,
                reference_max=20,
            )
        ]
    )

    assert (
        RenalPattern.BUN_ABOVE_REFERENCE
        in result.patterns
    )


def test_multiple_abnormal_values():
    analyzer = RenalAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="creatinine",
                value=1.8,
                unit="mg/dL",
                reference_min=0.6,
                reference_max=1.2,
            ),
            LabValue(
                name="egfr",
                value=45,
                unit="mL/min/1.73m2",
                reference_min=60,
                reference_max=None,
            ),
        ]
    )

    assert len(
        result.abnormal_findings
    ) == 2

    assert (
        RenalPattern.MULTIPLE_ABNORMAL
        in result.patterns
    )


def test_missing_reference_is_unknown():
    analyzer = RenalAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="creatinine",
                value=1.0,
                unit="mg/dL",
            )
        ]
    )

    assert (
        result.findings[0].flag
        == LabFlag.UNKNOWN
    )

    assert (
        RenalPattern.INSUFFICIENT_DATA
        in result.patterns
    )


def test_no_renal_tests():
    analyzer = RenalAnalyzer()

    result = analyzer.analyze([])

    assert (
        RenalPattern.INSUFFICIENT_DATA
        in result.patterns
    )