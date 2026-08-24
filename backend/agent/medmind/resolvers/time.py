from __future__ import annotations

import re


# ============================================================
# DIGIT NORMALIZATION
# ============================================================

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


def _normalize(
    value: str,
) -> str:

    value = value.translate(
        ARABIC_DIGITS
    )

    value = (
        value
        .strip()
        .lower()
    )

    value = (
        value
        .replace("الساعة", "")
        .replace("الساعه", "")
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


# ============================================================
# PERIOD DETECTION
# ============================================================

def _detect_period(
    text: str,
) -> str | None:
    """
    Returns:
    am
    pm
    None
    """

    am_words = {
        "ص",
        "صباح",
        "الصبح",
        "صباحا",
        "صباحًا",
        "am",
        "a.m.",
    }

    pm_words = {
        "م",
        "العصر",
        "المساء",
        "مساء",
        "مساءا",
        "مساءً",
        "بالليل",
        "الليل",
        "pm",
        "p.m.",
    }

    words = set(
        text.split()
    )

    if words & am_words:
        return "am"

    if words & pm_words:
        return "pm"

    return None


# ============================================================
# 24-HOUR CONVERSION
# ============================================================

def _to_24_hour(
    hour: int,
    minute: int,
    period: str | None,
) -> list[str]:

    if not (
        0 <= minute <= 59
    ):
        return []

    # --------------------------------------------------------
    # Explicit AM
    # --------------------------------------------------------

    if period == "am":

        if not (
            1 <= hour <= 12
        ):
            return []

        if hour == 12:
            hour = 0

        return [
            f"{hour:02d}:{minute:02d}"
        ]

    # --------------------------------------------------------
    # Explicit PM
    # --------------------------------------------------------

    if period == "pm":

        if not (
            1 <= hour <= 12
        ):
            return []

        if hour != 12:
            hour += 12

        return [
            f"{hour:02d}:{minute:02d}"
        ]

    # --------------------------------------------------------
    # Already 24-hour format
    # --------------------------------------------------------

    if hour > 12:

        if hour > 23:
            return []

        return [
            f"{hour:02d}:{minute:02d}"
        ]

    # --------------------------------------------------------
    # No AM / PM supplied.
    #
    # Return BOTH possibilities.
    #
    # Example:
    #
    # "1 ونص"
    #
    # → 01:30
    # → 13:30
    #
    # The workflow will compare them against
    # REAL AVAILABLE SLOTS and select only
    # a valid one.
    # --------------------------------------------------------

    if hour == 0:

        return [
            f"00:{minute:02d}"
        ]

    if hour == 12:

        return [
            f"12:{minute:02d}",
            f"00:{minute:02d}",
        ]

    if 1 <= hour <= 11:

        return [
            f"{hour:02d}:{minute:02d}",
            f"{hour + 12:02d}:{minute:02d}",
        ]

    return []


# ============================================================
# TIME RESOLVER
# ============================================================

def resolve_time_candidates(
    value: str | None,
) -> list[str]:
    """
    Return possible normalized HH:MM values.

    Examples:

    13:30
        -> ["13:30"]

    1:30 pm
        -> ["13:30"]

    1 ونص
        -> ["01:30", "13:30"]

    2 العصر
        -> ["14:00"]

    12
        -> ["12:00", "00:00"]

    The Booking Workflow decides which candidate
    matches the real available slots.
    """

    if not value:
        return []

    text = _normalize(
        value
    )

    period = _detect_period(
        text
    )

    # ========================================================
    # HH:MM
    # ========================================================

    match = re.search(
        r"\b(\d{1,2})"
        r":"
        r"(\d{2})\b",
        text,
    )

    if match:

        hour = int(
            match.group(1)
        )

        minute = int(
            match.group(2)
        )

        return _to_24_hour(
            hour,
            minute,
            period,
        )

    # ========================================================
    # ARABIC HALF HOUR
    #
    # 1 ونص
    # 1 ونصف
    # ========================================================

    match = re.search(
        r"\b(\d{1,2})"
        r"\s*"
        r"(?:و\s*)?"
        r"(?:نص|نصف)\b",
        text,
    )

    if match:

        hour = int(
            match.group(1)
        )

        return _to_24_hour(
            hour,
            30,
            period,
        )

    # ========================================================
    # QUARTER PAST
    #
    # 1 وربع
    # ========================================================

    match = re.search(
        r"\b(\d{1,2})"
        r"\s*"
        r"(?:و\s*)?"
        r"ربع\b",
        text,
    )

    if match:

        hour = int(
            match.group(1)
        )

        return _to_24_hour(
            hour,
            15,
            period,
        )

    # ========================================================
    # SIMPLE HOUR
    #
    # 1
    # 2 العصر
    # 12
    # ========================================================

    match = re.search(
        r"\b(\d{1,2})\b",
        text,
    )

    if match:

        hour = int(
            match.group(1)
        )

        return _to_24_hour(
            hour,
            0,
            period,
        )

    return []