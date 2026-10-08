from __future__ import annotations

from dataclasses import dataclass

from src.diagnostics.lab_image_extractor import (
    ExtractedLabValue,
)

from src.diagnostics.lab_reference import (
    resolve_reference_bounds,
)


LIPID_NAME_ALIASES = {
    # Total cholesterol
    "cholesterol": "total_cholesterol",
    "total cholesterol": "total_cholesterol",
    "cholesterol total": "total_cholesterol",
    "serum cholesterol": "total_cholesterol",
    "serum total cholesterol": "total_cholesterol",

    # LDL
    "ldl": "ldl",
    "ldl c": "ldl",
    "ldl cholesterol": "ldl",
    "ldl chol": "ldl",
    "low density lipoprotein": "ldl",

    # HDL
    "hdl": "hdl",
    "hdl c": "hdl",
    "hdl cholesterol": "hdl",
    "hdl chol": "hdl",
    "high density lipoprotein": "hdl",

    # Triglycerides
    "tg": "triglycerides",
    "triglyceride": "triglycerides",
    "triglycerides": "triglycerides",
    "serum triglycerides": "triglycerides",

    # VLDL
    "vldl": "vldl",
    "vldl c": "vldl",
    "vldl cholesterol": "vldl",
    "very low density lipoprotein": "vldl",
    
    # Lipid ratios
    "ldl / hdl": "ldl_hdl_ratio",
    "ldl/hdl": "ldl_hdl_ratio",

    "total cholesterol / hdl": (
        "total_cholesterol_hdl_ratio"
    ),
    "total cholesterol/hdl": (
        "total_cholesterol_hdl_ratio"
    ),

    "tg / hdl": "tg_hdl_ratio",
    "tg/hdl": "tg_hdl_ratio",

    # Non-HDL cholesterol
    "non hdl cholesterol": (
        "non_hdl_cholesterol"
    ),
    "non hdl": (
        "non_hdl_cholesterol"
    ),
}


@dataclass(frozen=True)
class NormalizedLipidValue:
    name: str
    raw_name: str
    value: float | None
    unit: str | None
    reference_min: float | None
    reference_max: float | None
    reference_text: str | None


def normalize_lipid_name(
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

    return LIPID_NAME_ALIASES.get(
        cleaned
    )


def normalize_lipid_result(
    result: ExtractedLabValue,
) -> NormalizedLipidValue | None:

    normalized_name = normalize_lipid_name(
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

    return NormalizedLipidValue(
        name=normalized_name,
        raw_name=result.raw_name,
        value=result.value,
        unit=result.unit,
        reference_min=reference_min,
        reference_max=reference_max,
        reference_text=result.reference_text,
    )


def normalize_lipid_results(
    results: list[ExtractedLabValue],
) -> list[NormalizedLipidValue]:

    normalized = []

    for result in results:
        item = normalize_lipid_result(
            result
        )

        if item is not None:
            normalized.append(item)

    return normalized


def find_unmapped_lipid_results(
    results: list[ExtractedLabValue],
) -> list[ExtractedLabValue]:

    return [
        result
        for result in results
        if normalize_lipid_name(
            result.raw_name
        )
        is None
    ]