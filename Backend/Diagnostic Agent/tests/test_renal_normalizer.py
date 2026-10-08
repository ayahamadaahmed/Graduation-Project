from src.diagnostics.lab_image_extractor import (
    ExtractedLabValue,
)

from src.diagnostics.renal_normalizer import (
    find_unmapped_renal_results,
    normalize_renal_name,
    normalize_renal_result,
)


def test_serum_creatinine_normalizes():
    assert (
        normalize_renal_name(
            "Serum Creatinine"
        )
        == "creatinine"
    )


def test_s_creatinine_normalizes():
    assert (
        normalize_renal_name(
            "S. Creatinine"
        )
        == "creatinine"
    )


def test_egfr_variants_normalize():
    assert (
        normalize_renal_name(
            "eGFR"
        )
        == "egfr"
    )

    assert (
        normalize_renal_name(
            "Estimated GFR"
        )
        == "egfr"
    )


def test_bun_normalizes():
    assert (
        normalize_renal_name(
            "BUN"
        )
        == "bun"
    )


def test_blood_urea_nitrogen_normalizes():
    assert (
        normalize_renal_name(
            "Blood Urea Nitrogen"
        )
        == "bun"
    )


def test_urea_normalizes():
    assert (
        normalize_renal_name(
            "Serum Urea"
        )
        == "urea"
    )


def test_reference_text_is_resolved():
    raw = ExtractedLabValue(
        raw_name="eGFR",
        value=85,
        unit="mL/min/1.73m2",
        reference_min=None,
        reference_max=None,
        reference_text="> 60",
    )

    result = normalize_renal_result(
        raw
    )

    assert result is not None
    assert result.name == "egfr"

    assert (
        result.reference_min
        == 60
    )

    assert (
        result.reference_max
        is None
    )


def test_unknown_test_is_tracked():
    results = [
        ExtractedLabValue(
            raw_name="Creatinine",
            value=0.9,
            unit="mg/dL",
        ),
        ExtractedLabValue(
            raw_name="Unknown Renal Test",
            value=10,
            unit="unit",
        ),
    ]

    unmapped = (
        find_unmapped_renal_results(
            results
        )
    )

    assert len(unmapped) == 1

    assert (
        unmapped[0].raw_name
        == "Unknown Renal Test"
    )