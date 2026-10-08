from src.diagnostics.cbc_engine import (
    CBCAnalyzer,
    CBCPattern,
)

from src.diagnostics.lab_types import (
    LabFlag,
    LabValue,
)

def test_low_hemoglobin_is_detected():
    value = LabValue(
        name="hemoglobin",
        value=9.5,
        unit="g/dL",
        reference_min=12.0,
        reference_max=15.5,
    )

    assert value.flag() == LabFlag.LOW


def test_normal_value_is_detected():
    value = LabValue(
        name="platelets",
        value=250,
        unit="10^3/uL",
        reference_min=150,
        reference_max=450,
    )

    assert value.flag() == LabFlag.NORMAL


def test_unknown_when_reference_range_missing():
    value = LabValue(
        name="wbc",
        value=8.0,
        unit="10^3/uL",
    )

    assert value.flag() == LabFlag.UNKNOWN


def test_microcytic_pattern():
    analyzer = CBCAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="hemoglobin",
                value=9.5,
                unit="g/dL",
                reference_min=12,
                reference_max=15.5,
            ),
            LabValue(
                name="mcv",
                value=72,
                unit="fL",
                reference_min=80,
                reference_max=100,
            ),
            LabValue(
                name="wbc",
                value=7,
                unit="10^3/uL",
                reference_min=4,
                reference_max=11,
            ),
            LabValue(
                name="platelets",
                value=250,
                unit="10^3/uL",
                reference_min=150,
                reference_max=450,
            ),
        ]
    )

    assert (
        CBCPattern.LOW_HEMOGLOBIN_MICROCYTIC
        in result.patterns
    )


def test_normocytic_pattern():
    analyzer = CBCAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="hemoglobin",
                value=10,
                unit="g/dL",
                reference_min=12,
                reference_max=15.5,
            ),
            LabValue(
                name="mcv",
                value=88,
                unit="fL",
                reference_min=80,
                reference_max=100,
            ),
            LabValue(
                name="wbc",
                value=7,
                unit="10^3/uL",
                reference_min=4,
                reference_max=11,
            ),
            LabValue(
                name="platelets",
                value=250,
                unit="10^3/uL",
                reference_min=150,
                reference_max=450,
            ),
        ]
    )

    assert (
        CBCPattern.LOW_HEMOGLOBIN_NORMOCYTIC
        in result.patterns
    )


def test_high_wbc_is_reported_as_abnormal():
    analyzer = CBCAnalyzer()

    result = analyzer.analyze(
        [
            LabValue(
                name="hemoglobin",
                value=13,
                unit="g/dL",
                reference_min=12,
                reference_max=15.5,
            ),
            LabValue(
                name="mcv",
                value=88,
                unit="fL",
                reference_min=80,
                reference_max=100,
            ),
            LabValue(
                name="wbc",
                value=15,
                unit="10^3/uL",
                reference_min=4,
                reference_max=11,
            ),
            LabValue(
                name="platelets",
                value=250,
                unit="10^3/uL",
                reference_min=150,
                reference_max=450,
            ),
        ]
    )

    abnormal_names = [
        finding.name
        for finding in result.abnormal_findings
    ]

    assert "wbc" in abnormal_names


def test_upper_bound_only_reference_range():
    value = LabValue(
        name="esr",
        value=2,
        unit="mm/hr",
        reference_min=None,
        reference_max=15,
    )

    assert value.flag() == LabFlag.NORMAL


def test_upper_bound_only_detects_high_value():
    value = LabValue(
        name="esr",
        value=20,
        unit="mm/hr",
        reference_min=None,
        reference_max=15,
    )

    assert value.flag() == LabFlag.HIGH


def test_lower_bound_only_reference_range():
    value = LabValue(
        name="example_test",
        value=5,
        unit="unit",
        reference_min=3,
        reference_max=None,
    )

    assert value.flag() == LabFlag.NORMAL


def test_no_reference_range_stays_unknown():
    value = LabValue(
        name="example_test",
        value=5,
        unit="unit",
    )

    assert value.flag() == LabFlag.UNKNOWN    