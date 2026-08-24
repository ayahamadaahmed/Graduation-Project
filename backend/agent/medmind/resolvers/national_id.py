from __future__ import annotations

import re


ARABIC_DIGITS = str.maketrans(
    {
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
    }
)


def resolve_national_id(
    value: str | None,
) -> str | None:
    """
    Normalize an Egyptian national ID.

    This performs structural validation only.
    Final validation remains the backend's job.
    """

    if not value:
        return None

    value = value.translate(
        ARABIC_DIGITS
    )

    digits = re.sub(
        r"\D",
        "",
        value,
    )

    if len(digits) != 14:
        return None

    return digits