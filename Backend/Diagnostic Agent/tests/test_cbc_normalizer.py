from src.diagnostics.cbc_normalizer import (
    find_unmapped_cbc_results,
    normalize_cbc_result,
    normalize_test_name,
)
from src.diagnostics.lab_image_extractor import (
    ExtractedLabValue,
)


def test_hgb_normalizes_to_hemoglobin():
    assert (
        normalize_test_name("HGB")
        == "hemoglobin"
    )


def test_hemoglobin_name_is_supported():
    assert (
        normalize_test_name("Hemoglobin")
        == "hemoglobin"
    )


def test_plt_normalizes_to_platelets():
    assert (
        normalize_test_name("PLT")
        == "platelets"
    )


def test_wbc_normalizes_to_wbc():
    assert (
        normalize_test_name("WBC")
        == "wbc"
    )


def test_mcv_normalizes_to_mcv():
    assert (
        normalize_test_name("MCV")
        == "mcv"
    )


def test_full_lab_value_is_preserved():
    raw = ExtractedLabValue(
        raw_name="PLT",
        value=256,
        unit="10^3/uL",
        reference_min=150,
        reference_max=450,
        reference_text="150-450",
    )

    result = normalize_cbc_result(
        raw
    )

    assert result is not None
    assert result.name == "platelets"
    assert result.raw_name == "PLT"
    assert result.value == 256
    assert result.unit == "10^3/uL"
    assert result.reference_min == 150
    assert result.reference_max == 450


def test_unknown_test_returns_none():
    assert (
        normalize_test_name(
            "UNKNOWN TEST"
        )
        is None
    )

def test_unknown_tests_are_tracked():
    results = [
        ExtractedLabValue(
            raw_name="HGB",
            value=12,
            unit="g/dL",
        ),
        ExtractedLabValue(
            raw_name="MPV",
            value=9.2,
            unit="fL",
        ),
    ]

    unmapped = find_unmapped_cbc_results(
        results
    )

    assert len(unmapped) == 1
    assert unmapped[0].raw_name == "MPV"    

def test_granulocyte_name_variants():
    assert (
        normalize_test_name("GRA#")
        == "granulocytes_absolute"
    )

    assert (
        normalize_test_name("GRAN#")
        == "granulocytes_absolute"
    )

    assert (
        normalize_test_name("GRAM#")
        == "granulocytes_absolute"
    )


def test_up_to_reference_text_fills_max():
    raw = ExtractedLabValue(
        raw_name="ESR",
        value=2,
        unit="mm/hr",
        reference_min=None,
        reference_max=None,
        reference_text="Up to 15",
    )

    result = normalize_cbc_result(raw)

    assert result is not None
    assert result.reference_min is None
    assert result.reference_max == 15


def test_numeric_reference_text_fills_bounds():
    raw = ExtractedLabValue(
        raw_name="WBC",
        value=6.7,
        unit="10^3/uL",
        reference_min=None,
        reference_max=None,
        reference_text="4.5 - 11",
    )

    result = normalize_cbc_result(raw)

    assert result is not None
    assert result.reference_min == 4.5
    assert result.reference_max == 11    