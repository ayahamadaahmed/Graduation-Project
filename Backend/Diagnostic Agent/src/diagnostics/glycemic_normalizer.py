from __future__ import annotations

from dataclasses import dataclass

from src.diagnostics.lab_image_extractor import (
    ExtractedLabValue,
)

from src.diagnostics.lab_reference import (
    resolve_reference_bounds,
)


GLYCEMIC_NAME_ALIASES = {
    # Fasting glucose
    "fbs": "fasting_glucose",
    "fbg": "fasting_glucose",
    "fasting glucose": "fasting_glucose",
    "fasting blood glucose": "fasting_glucose",
    "fasting blood sugar": "fasting_glucose",
    "fasting plasma glucose": "fasting_glucose",
    "fpg": "fasting_glucose",

    # Random glucose
    "rbs": "random_glucose",
    "rbg": "random_glucose",
    "random glucose": "random_glucose",
    "random blood glucose": "random_glucose",
    "random blood sugar": "random_glucose",

    # Generic glucose
    "glucose": "glucose",
    "blood glucose": "glucose",
    "blood sugar": "glucose",
    "serum glucose": "glucose",

    # HbA1c
    "hba1c": "hba1c",
    "hb a1c": "hba1c",
    "a1c": "hba1c",

    "hemoglobin a1c": "hba1c",
    "haemoglobin a1c": "hba1c",

    "glycated hemoglobin": "hba1c",
    "glycated haemoglobin": "hba1c",

    "glycosylated hemoglobin": "hba1c",
    "glycosylated haemoglobin": "hba1c",
}


@dataclass(frozen=True)
class NormalizedGlycemicValue:
    name: str
    raw_name: str
    value: float | None
    unit: str | None

    reference_min: float | None
    reference_max: float | None
    reference_text: str | None


def normalize_glycemic_name(
    raw_name: str,
) -> str | None:

    cleaned = (
        raw_name
        .strip()
        .lower()
        .replace("_", " ")
        .replace("-", " ")
    )

    cleaned = " ".join(
        cleaned.split()
    )

    return GLYCEMIC_NAME_ALIASES.get(
        cleaned
    )


def normalize_glycemic_result(
    result: ExtractedLabValue,
) -> NormalizedGlycemicValue | None:

    normalized_name = normalize_glycemic_name(
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

    return NormalizedGlycemicValue(
        name=normalized_name,
        raw_name=result.raw_name,
        value=result.value,
        unit=result.unit,
        reference_min=reference_min,
        reference_max=reference_max,
        reference_text=result.reference_text,
    )


def normalize_glycemic_results(
    results: list[ExtractedLabValue],
) -> list[NormalizedGlycemicValue]:

    normalized = []

    for result in results:
        item = normalize_glycemic_result(
            result
        )

        if item is not None:
            normalized.append(item)

    return normalized


def find_unmapped_glycemic_results(
    results: list[ExtractedLabValue],
) -> list[ExtractedLabValue]:

    return [
        result
        for result in results
        if normalize_glycemic_name(
            result.raw_name
        )
        is None
    ]