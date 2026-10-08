from src.diagnostics.lab_image_extractor import (
    ExtractedLabValue,
)

from src.diagnostics.liver_normalizer import (
    find_unmapped_liver_results,
    normalize_liver_name,
    normalize_liver_result,
)


def test_alt_variants_normalize():
    assert (
        normalize_liver_name("ALT")
        == "alt"
    )

    assert (
        normalize_liver_name("SGPT")
        == "alt"
    )


def test_ast_variants_normalize():
    assert (
        normalize_liver_name("AST")
        == "ast"
    )

    assert (
        normalize_liver_name("SGOT")
        == "ast"
    )


def test_alp_normalizes():
    assert (
        normalize_liver_name(
            "Alkaline Phosphatase"
        )
        == "alp"
    )


def test_total_bilirubin_normalizes():
    assert (
        normalize_liver_name(
            "Total Bilirubin"
        )
        == "total_bilirubin"
    )


def test_albumin_normalizes():
    assert (
        normalize_liver_name(
            "Serum Albumin"
        )
        == "albumin"
    )


def test_reference_text_is_resolved():
    raw = ExtractedLabValue(
        raw_name="ALT",
        value=30,
        unit="U/L",
        reference_min=None,
        reference_max=None,
        reference_text="0 - 40",
    )

    result = normalize_liver_result(
        raw
    )

    assert result is not None
    assert result.reference_min == 0
    assert result.reference_max == 40


def test_unknown_test_is_tracked():
    results = [
        ExtractedLabValue(
            raw_name="ALT",
            value=30,
            unit="U/L",
        ),
        ExtractedLabValue(
            raw_name="Unknown Liver Test",
            value=5,
            unit="unit",
        ),
    ]

    unmapped = (
        find_unmapped_liver_results(
            results
        )
    )

    assert len(unmapped) == 1

    assert (
        unmapped[0].raw_name
        == "Unknown Liver Test"
    )

def test_sgpt_alt_report_format():
    assert (
        normalize_liver_name(
            "SGPT (ALT)"
        )
        == "alt"
    )


def test_sgot_ast_report_format():
    assert (
        normalize_liver_name(
            "SGOT (AST)"
        )
        == "ast"
    )


def test_serum_alkaline_phosphatase():
    assert (
        normalize_liver_name(
            "SERUM ALKALINE PHOSPHATASE"
        )
        == "alp"
    )


def test_serum_total_bilirubin():
    assert (
        normalize_liver_name(
            "SERUM BILIRUBIN (TOTAL)"
        )
        == "total_bilirubin"
    )    

def test_direct_bilirubin_normalizes():
    assert (
        normalize_liver_name(
            "SERUM BILIRUBIN (DIRECT)"
        )
        == "direct_bilirubin"
    )


def test_indirect_bilirubin_normalizes():
    assert (
        normalize_liver_name(
            "SERUM BILIRUBIN (INDIRECT)"
        )
        == "indirect_bilirubin"
    )


def test_serum_protein_normalizes():
    assert (
        normalize_liver_name(
            "SERUM PROTEIN"
        )
        == "total_protein"
    )


def test_globulin_normalizes():
    assert (
        normalize_liver_name(
            "GLOBULIN"
        )
        == "globulin"
    )


def test_ag_ratio_normalizes():
    assert (
        normalize_liver_name(
            "A/G RATIO"
        )
        == "ag_ratio"
    )