from src.diagnostics.lab_image_extractor import (
    ExtractedLabValue,
)

from src.diagnostics.lipid_normalizer import (
    find_unmapped_lipid_results,
    normalize_lipid_name,
    normalize_lipid_result,
)


def test_total_cholesterol_variants():
    assert (
        normalize_lipid_name(
            "Total Cholesterol"
        )
        == "total_cholesterol"
    )

    assert (
        normalize_lipid_name(
            "Serum Cholesterol"
        )
        == "total_cholesterol"
    )


def test_ldl_variants():
    assert (
        normalize_lipid_name("LDL")
        == "ldl"
    )

    assert (
        normalize_lipid_name("LDL-C")
        == "ldl"
    )


def test_hdl_variants():
    assert (
        normalize_lipid_name("HDL")
        == "hdl"
    )

    assert (
        normalize_lipid_name("HDL-C")
        == "hdl"
    )


def test_triglycerides_variants():
    assert (
        normalize_lipid_name(
            "Triglycerides"
        )
        == "triglycerides"
    )

    assert (
        normalize_lipid_name("TG")
        == "triglycerides"
    )


def test_vldl_variants():
    assert (
        normalize_lipid_name("VLDL")
        == "vldl"
    )

    assert (
        normalize_lipid_name("VLDL-C")
        == "vldl"
    )


def test_reference_text_is_resolved():
    raw = ExtractedLabValue(
        raw_name="LDL-C",
        value=120,
        unit="mg/dL",
        reference_min=None,
        reference_max=None,
        reference_text="0 - 130",
    )

    result = normalize_lipid_result(
        raw
    )

    assert result is not None
    assert result.name == "ldl"
    assert result.reference_min == 0
    assert result.reference_max == 130


def test_unknown_test_is_tracked():
    results = [
        ExtractedLabValue(
            raw_name="HDL-C",
            value=50,
            unit="mg/dL",
        ),
        ExtractedLabValue(
            raw_name="Unknown Lipid Test",
            value=10,
            unit="unit",
        ),
    ]

    unmapped = (
        find_unmapped_lipid_results(
            results
        )
    )

    assert len(unmapped) == 1

    assert (
        unmapped[0].raw_name
        == "Unknown Lipid Test"
    )

def test_ldl_hdl_ratio_normalizes():
    assert (
        normalize_lipid_name(
            "LDL / HDL"
        )
        == "ldl_hdl_ratio"
    )


def test_total_cholesterol_hdl_ratio_normalizes():
    assert (
        normalize_lipid_name(
            "TOTAL CHOLESTEROL / HDL"
        )
        == "total_cholesterol_hdl_ratio"
    )


def test_tg_hdl_ratio_normalizes():
    assert (
        normalize_lipid_name(
            "TG / HDL"
        )
        == "tg_hdl_ratio"
    )


def test_non_hdl_cholesterol_normalizes():
    assert (
        normalize_lipid_name(
            "NON-HDL CHOLESTEROL"
        )
        == "non_hdl_cholesterol"
    )    