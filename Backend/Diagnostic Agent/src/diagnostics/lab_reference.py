from __future__ import annotations

import re


def _to_number(
    value: str,
) -> float:
    return float(
        value.replace(",", ".")
    )


def parse_reference_text(
    reference_text: str | None,
) -> tuple[float | None, float | None]:
    """
    Parse common laboratory reference-range text.

    Examples:
        "4 - 11"    -> (4, 11)
        "Up to 15"  -> (None, 15)
        "< 15"      -> (None, 15)
        "> 3"       -> (3, None)

    This parses only what is written
    on the laboratory report.
    """

    if not reference_text:
        return None, None

    text = reference_text.strip()

    number = r"(-?\d+(?:[.,]\d+)?)"

    range_match = re.fullmatch(
        rf"\s*{number}\s*"
        rf"(?:-|–|—|to)\s*"
        rf"{number}\s*",
        text,
        re.IGNORECASE,
    )

    if range_match:
        return (
            _to_number(
                range_match.group(1)
            ),
            _to_number(
                range_match.group(2)
            ),
        )

    upper_match = re.fullmatch(
        rf"\s*(?:up\s+to|<=?|less\s+than)\s*"
        rf"{number}\s*",
        text,
        re.IGNORECASE,
    )

    if upper_match:
        return (
            None,
            _to_number(
                upper_match.group(1)
            ),
        )

    lower_match = re.fullmatch(
        rf"\s*(?:>=?|greater\s+than)\s*"
        rf"{number}\s*",
        text,
        re.IGNORECASE,
    )

    if lower_match:
        return (
            _to_number(
                lower_match.group(1)
            ),
            None,
        )

    return None, None


def resolve_reference_bounds(
    reference_min: float | None,
    reference_max: float | None,
    reference_text: str | None,
) -> tuple[float | None, float | None]:

    parsed_min, parsed_max = (
        parse_reference_text(
            reference_text
        )
    )

    resolved_min = (
        reference_min
        if reference_min is not None
        else parsed_min
    )

    resolved_max = (
        reference_max
        if reference_max is not None
        else parsed_max
    )

    return resolved_min, resolved_max