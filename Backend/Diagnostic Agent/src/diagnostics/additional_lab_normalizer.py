from __future__ import annotations

import re

from src.diagnostics.cbc_normalizer import NormalizedLabValue
from src.diagnostics.lab_image_extractor import ExtractedLabValue
from src.diagnostics.lab_reference import resolve_reference_bounds


# Additional common analytes, including vitamin D and tests often reviewed
# when evaluating anemia. Their flags use only the range printed by the lab.
ADDITIONAL_LAB_ALIASES = {
    "25-oh vitamin d": "vitamin_d_25oh",
    "25 oh vitamin d": "vitamin_d_25oh",
    "25-hydroxy vitamin d": "vitamin_d_25oh",
    "25 hydroxy vitamin d": "vitamin_d_25oh",
    "vitamin d, 25-hydroxy": "vitamin_d_25oh",
    "vitamin d 25-oh": "vitamin_d_25oh",
    "vitamin d (25-oh)": "vitamin_d_25oh",
    "25-ohd": "vitamin_d_25oh",
    "25(oh)d": "vitamin_d_25oh",
    "vitamin d": "vitamin_d_25oh",
    "vitamin d2": "vitamin_d2",
    "25-oh vitamin d2": "vitamin_d2",
    "25-hydroxy vitamin d2": "vitamin_d2",
    "vitamin d3": "vitamin_d3",
    "25-oh vitamin d3": "vitamin_d3",
    "25-hydroxy vitamin d3": "vitamin_d3",
    "1,25-dihydroxy vitamin d": "vitamin_d_1_25oh2",
    "1,25 dihydroxy vitamin d": "vitamin_d_1_25oh2",
    "1,25-dihydroxyvitamin d": "vitamin_d_1_25oh2",
    "calcitriol": "vitamin_d_1_25oh2",
    "ferritin": "ferritin",
    "serum ferritin": "ferritin",
    "iron": "serum_iron",
    "serum iron": "serum_iron",
    "iron, serum": "serum_iron",
    "tibc": "tibc",
    "total iron binding capacity": "tibc",
    "total iron-binding capacity": "tibc",
    "transferrin saturation": "transferrin_saturation",
    "transferrin saturation %": "transferrin_saturation",
    "iron saturation": "transferrin_saturation",
    "iron saturation %": "transferrin_saturation",
    "vitamin b12": "vitamin_b12",
    "vit b12": "vitamin_b12",
    "b12": "vitamin_b12",
    "cobalamin": "vitamin_b12",
    "folate": "folate",
    "serum folate": "folate",
    "folic acid": "folate",
    "reticulocyte count": "reticulocyte_count",
    "reticulocytes": "reticulocyte_count",
    "retic count": "reticulocyte_count",
}


def normalize_additional_name(raw_name: str) -> str | None:
    cleaned = raw_name.strip().lower().replace("_", " ")
    if re.fullmatch(r"1\s*,?\s*25\s*\(?\s*oh\s*\)?\s*2\s*d", cleaned):
        return "vitamin_d_1_25oh2"
    if re.fullmatch(r"25\s*\(?\s*oh\s*\)?\s*d", cleaned):
        return "vitamin_d_25oh"
    cleaned = re.sub(r"\([^)]*\)", " ", cleaned)
    cleaned = " ".join(cleaned.split())
    return ADDITIONAL_LAB_ALIASES.get(cleaned)


def normalize_additional_results(
    results: list[ExtractedLabValue],
) -> list[NormalizedLabValue]:
    normalized: list[NormalizedLabValue] = []
    for result in results:
        name = normalize_additional_name(result.raw_name)
        if name is None:
            continue
        reference_min, reference_max = resolve_reference_bounds(
            result.reference_min,
            result.reference_max,
            result.reference_text,
        )
        normalized.append(
            NormalizedLabValue(
                name=name,
                raw_name=result.raw_name,
                value=result.value,
                unit=result.unit,
                reference_min=reference_min,
                reference_max=reference_max,
                reference_text=result.reference_text,
            )
        )
    return normalized
