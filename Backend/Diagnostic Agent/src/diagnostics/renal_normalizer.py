from __future__ import annotations

from dataclasses import dataclass

from src.diagnostics.lab_image_extractor import (
    ExtractedLabValue,
)

from src.diagnostics.lab_reference import (
    resolve_reference_bounds,
)


RENAL_NAME_ALIASES = {
    # Creatinine
    "creatinine": "creatinine",
    "serum creatinine": "creatinine",
    "s creatinine": "creatinine",
    "s. creatinine": "creatinine",
    "creat": "creatinine",

    # eGFR
    "egfr": "egfr",
    "e gfr": "egfr",
    "estimated gfr": "egfr",
    "estimated glomerular filtration rate": "egfr",
    "glomerular filtration rate": "egfr",

    # BUN
    "bun": "bun",
    "blood urea nitrogen": "bun",
    "blood urea nitrogen bun": "bun",

    # Urea
    "urea": "urea",
    "serum urea": "urea",
    "blood urea": "urea",
}


@dataclass(frozen=True)
class NormalizedRenalValue:
    name: str
    raw_name: str
    value: float | None
    unit: str | None

    reference_min: float | None
    reference_max: float | None
    reference_text: str | None


def normalize_renal_name(
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

    return RENAL_NAME_ALIASES.get(
        cleaned
    )


def normalize_renal_result(
    result: ExtractedLabValue,
) -> NormalizedRenalValue | None:

    normalized_name = normalize_renal_name(
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

    return NormalizedRenalValue(
        name=normalized_name,
        raw_name=result.raw_name,
        value=result.value,
        unit=result.unit,
        reference_min=reference_min,
        reference_max=reference_max,
        reference_text=result.reference_text,
    )


def normalize_renal_results(
    results: list[ExtractedLabValue],
) -> list[NormalizedRenalValue]:

    normalized = []

    for result in results:
        item = normalize_renal_result(
            result
        )

        if item is not None:
            normalized.append(item)

    return normalized


def find_unmapped_renal_results(
    results: list[ExtractedLabValue],
) -> list[ExtractedLabValue]:

    return [
        result
        for result in results
        if normalize_renal_name(
            result.raw_name
        )
        is None
    ]