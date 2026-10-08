from src.diagnostics.glycemic_normalizer import (
    find_unmapped_glycemic_results,
    normalize_glycemic_name,
    normalize_glycemic_result,
)

from src.diagnostics.lab_image_extractor import (
    ExtractedLabValue,
)


def test_fbs_normalizes_to_fasting_glucose():
    assert (
        normalize_glycemic_name("FBS")
        == "fasting_glucose"
    )


def test_fpg_normalizes_to_fasting_glucose():
    assert (
        normalize_glycemic_name("FPG")
        == "fasting_glucose"
    )


def test_fasting_blood_sugar_normalizes():
    assert (
        normalize_glycemic_name(
            "Fasting Blood Sugar"
        )
        == "fasting_glucose"
    )


def test_rbs_normalizes_to_random_glucose():
    assert (
        normalize_glycemic_name("RBS")
        == "random_glucose"
    )


def test_hba1c_variants_normalize():
    assert (
        normalize_glycemic_name("HbA1c")
        == "hba1c"
    )

    assert (
        normalize_glycemic_name("Hb A1c")
        == "hba1c"
    )

    assert (
        normalize_glycemic_name("A1C")
        == "hba1c"
    )


def test_reference_text_is_resolved():
    raw = ExtractedLabValue(
        raw_name="FBS",
        value=95,
        unit="mg/dL",
        reference_min=None,
        reference_max=None,
        reference_text="70 - 99",
    )

    result = normalize_glycemic_result(
        raw
    )

    assert result is not None
    assert result.name == "fasting_glucose"
    assert result.reference_min == 70
    assert result.reference_max == 99


def test_unknown_test_is_tracked():
    results = [
        ExtractedLabValue(
            raw_name="FBS",
            value=90,
            unit="mg/dL",
        ),
        ExtractedLabValue(
            raw_name="Some Unknown Test",
            value=10,
            unit="unit",
        ),
    ]

    unmapped = (
        find_unmapped_glycemic_results(
            results
        )
    )

    assert len(unmapped) == 1

    assert (
        unmapped[0].raw_name
        == "Some Unknown Test"
    )

def test_hemoglobin_a1c_normalizes():
    assert (
        normalize_glycemic_name(
            "Hemoglobin A1c"
        )
        == "hba1c"
    )    