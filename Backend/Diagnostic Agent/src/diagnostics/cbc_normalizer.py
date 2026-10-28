from __future__ import annotations

import re
from dataclasses import dataclass

from src.diagnostics.lab_image_extractor import ExtractedLabValue
from src.diagnostics.lab_reference import (
    resolve_reference_bounds,
)

CBC_NAME_ALIASES = {
    # Hemoglobin
    "hgb": "hemoglobin",
    "hb": "hemoglobin",
    "hemoglobin": "hemoglobin",
    "haemoglobin": "hemoglobin",

    # Red blood cells
    "rbc": "rbc",
    "rbc count": "rbc",
    "red blood cells": "rbc",
    "red cell count": "rbc",

    # Hematocrit
    "hct": "hematocrit",
    "hematocrit": "hematocrit",
    "haematocrit": "hematocrit",

    # Red cell indices
    "mcv": "mcv",
    "mch": "mch",
    "mchc": "mchc",
    "rdw": "rdw",
    "rdw-cv": "rdw_cv",
    "rdw cv": "rdw_cv",
    "rdw-sd": "rdw_sd",
    "rdw sd": "rdw_sd",

    # White blood cells
    "wbc": "wbc",
    "wbc count": "wbc",
    "white blood cells": "wbc",
    "total leukocyte count": "wbc",
    "total leucocyte count": "wbc",
    "total leukocytes": "wbc",
    "total leucocytes": "wbc",
    "tlc": "wbc",

    # Platelets
    "plt": "platelets",
    "platelet": "platelets",
    "platelets": "platelets",
    "platelet count": "platelets",

    # Differential
    "segmented %": "neutrophils_percent",
    "segmented%": "neutrophils_percent",
    "segmented": "neutrophils_percent",
    "segmented neutrophils": "neutrophils_percent",
    "neutrophil %": "neutrophils_percent",
    "neutrophils %": "neutrophils_percent",
    "neu%": "neutrophils_percent",
    "neutrophils%": "neutrophils_percent",
    "neutrophils": "neutrophils_percent",

    "absolute neutrophils": "neutrophils_absolute",
    "absolute neutrophils count": "neutrophils_absolute",
    "absolute neutrophil": "neutrophils_absolute",
    "absolute neutrophil count": "neutrophils_absolute",
    "neutrophils absolute": "neutrophils_absolute",
    "anc": "neutrophils_absolute",

    "lym%": "lymphocytes_percent",
    "lymphocytes%": "lymphocytes_percent",
    "lymphocytes %": "lymphocytes_percent",
    "lymphocyte %": "lymphocytes_percent",

    "mon%": "monocytes_percent",
    "monocytes%": "monocytes_percent",
    "monocytes %": "monocytes_percent",
    "absolute monocytes": "monocytes_absolute",
    "absolute monocyte count": "monocytes_absolute",
    "monocytes absolute": "monocytes_absolute",

    "eos%": "eosinophils_percent",
    "eosinophils%": "eosinophils_percent",
    "eosinophils %": "eosinophils_percent",
    "absolute eosinophils": "eosinophils_absolute",
    "absolute eosinophills": "eosinophils_absolute",
    "absolute eosinophills count": "eosinophils_absolute",
    "absolute eosinophil count": "eosinophils_absolute",
    "eosinophills %": "eosinophils_percent",
    "eosinophils absolute": "eosinophils_absolute",

    "bas%": "basophils_percent",
    "basophils%": "basophils_percent",
    "basophils %": "basophils_percent",
    "basophil %": "basophils_percent",
    "absolute basophils": "basophils_absolute",
    "absolute basophil count": "basophils_absolute",
    "basophils absolute": "basophils_absolute",

    "lym#": "lymphocytes_absolute",
    "absolute lymphocytes": "lymphocytes_absolute",
    "absolute lymphocytes count": "lymphocytes_absolute",
    "absolute lymphocyte count": "lymphocytes_absolute",
    "lymphocytes absolute": "lymphocytes_absolute",
    "gra#": "granulocytes_absolute",
    "gran#": "granulocytes_absolute",
    "gram#": "granulocytes_absolute",

    # Some laboratory reports label band/stab cells as Staff.
    "staff %": "staff_percent",
    "staff%": "staff_percent",
    "stab %": "staff_percent",
    "bands %": "staff_percent",

    # ESR
    "esr": "esr",
}




@dataclass(frozen=True)
class NormalizedLabValue:
    name: str
    raw_name: str
    value: float | None
    unit: str | None
    reference_min: float | None
    reference_max: float | None
    reference_text: str | None


def normalize_test_name(
    raw_name: str,
) -> str | None:

    cleaned = (
        raw_name
        .strip()
        .lower()
        .replace("_", " ")
    )
    cleaned = re.sub(r"\([^)]*\)", " ", cleaned)
    cleaned = cleaned.strip(" :;,.\t\r\n")

    cleaned = " ".join(
        cleaned.split()
    )

    return CBC_NAME_ALIASES.get(
        cleaned
    )
 
def normalize_cbc_result(
    result: ExtractedLabValue,
) -> NormalizedLabValue | None:

    normalized_name = normalize_test_name(
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

    return NormalizedLabValue(
        name=normalized_name,
        raw_name=result.raw_name,
        value=result.value,
        unit=result.unit,
        reference_min=reference_min,
        reference_max=reference_max,
        reference_text=result.reference_text,
    )


def normalize_cbc_results(
    results: list[ExtractedLabValue],
) -> list[NormalizedLabValue]:

    normalized = []

    for result in results:
        item = normalize_cbc_result(
            result
        )

        if item is not None:
            normalized.append(item)

    return normalized

def find_unmapped_cbc_results(
    results: list[ExtractedLabValue],
) -> list[ExtractedLabValue]:

    unmapped = []

    for result in results:
        if normalize_test_name(result.raw_name) is None:
            unmapped.append(result)

    return unmapped
