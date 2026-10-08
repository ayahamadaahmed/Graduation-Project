from __future__ import annotations

from dataclasses import dataclass

from src.diagnostics.lab_image_extractor import (
    ExtractedLabValue,
)

from src.diagnostics.lab_reference import (
    resolve_reference_bounds,
)

LIVER_NAME_ALIASES = {
    # ALT
    "alt": "alt",
    "sgpt": "alt",
    "sgpt alt": "alt",
    "alanine aminotransferase": "alt",
    "alanine transaminase": "alt",

    # AST
    "ast": "ast",
    "sgot": "ast",
    "sgot ast": "ast",
    "aspartate aminotransferase": "ast",
    "aspartate transaminase": "ast",

    # ALP
    "alp": "alp",
    "alkaline phosphatase": "alp",
    "alk phosphatase": "alp",
    "serum alkaline phosphatase": "alp",

    # Total bilirubin
    "total bilirubin": "total_bilirubin",
    "bilirubin total": "total_bilirubin",
    "serum bilirubin total": "total_bilirubin",
    "t bilirubin": "total_bilirubin",
    "t. bilirubin": "total_bilirubin",

    # Albumin
    "albumin": "albumin",
    "serum albumin": "albumin",

    # Direct bilirubin
    "direct bilirubin": "direct_bilirubin",
    "bilirubin direct": "direct_bilirubin",
    "serum bilirubin direct": "direct_bilirubin",

    # Indirect bilirubin
    "indirect bilirubin": "indirect_bilirubin",
    "bilirubin indirect": "indirect_bilirubin",
    "serum bilirubin indirect": "indirect_bilirubin",

    # Total protein
    "total protein": "total_protein",
    "serum protein": "total_protein",
    "serum total protein": "total_protein",

    # Globulin
    "globulin": "globulin",
    "serum globulin": "globulin",

    # Albumin / Globulin ratio
    "a/g ratio": "ag_ratio",
    "a g ratio": "ag_ratio",
    "albumin globulin ratio": "ag_ratio",
}

@dataclass(frozen=True)
class NormalizedLiverValue:
    name: str
    raw_name: str
    value: float | None
    unit: str | None

    reference_min: float | None
    reference_max: float | None
    reference_text: str | None


def normalize_liver_name(
    raw_name: str,
) -> str | None:

    cleaned = (
        raw_name
        .strip()
        .lower()
        .replace("_", " ")
        .replace("-", " ")
        .replace("(", " ")
        .replace(")", " ")
    )

    cleaned = " ".join(
        cleaned.split()
    )

    return LIVER_NAME_ALIASES.get(
        cleaned
    )


def normalize_liver_result(
    result: ExtractedLabValue,
) -> NormalizedLiverValue | None:

    normalized_name = normalize_liver_name(
        result.raw_name
    )

    if normalized_name is None:
        return None

    reference_min, reference_max = (
        resolve_reference_bounds(
            result.reference_min,
            result.reference_max,
            result.reference_text,
        )
    )

    return NormalizedLiverValue(
        name=normalized_name,
        raw_name=result.raw_name,
        value=result.value,
        unit=result.unit,
        reference_min=reference_min,
        reference_max=reference_max,
        reference_text=result.reference_text,
    )


def normalize_liver_results(
    results: list[ExtractedLabValue],
) -> list[NormalizedLiverValue]:

    normalized = []

    for result in results:
        item = normalize_liver_result(
            result
        )

        if item is not None:
            normalized.append(item)

    return normalized


def find_unmapped_liver_results(
    results: list[ExtractedLabValue],
) -> list[ExtractedLabValue]:

    return [
        result
        for result in results
        if normalize_liver_name(
            result.raw_name
        )
        is None
    ]