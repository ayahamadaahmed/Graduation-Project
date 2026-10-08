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


# ============================================================
# ARABIC / EGYPTIAN SPOKEN HOUR WORDS
# ============================================================

ARABIC_HOUR_WORDS = {
    # --------------------------------------------------------
    # 1
    # --------------------------------------------------------
    "واحد": "1",
    "واحدة": "1",
    "واحده": "1",

    # --------------------------------------------------------
    # 2
    # --------------------------------------------------------
    "اتنين": "2",
    "إتنين": "2",
    "اثنين": "2",
    "إثنين": "2",

    # --------------------------------------------------------
    # 3
    # --------------------------------------------------------
    "تلاتة": "3",
    "تلاته": "3",
    "ثلاثة": "3",
    "ثلاثه": "3",

    # --------------------------------------------------------
    # 4
    # --------------------------------------------------------
    "اربعة": "4",
    "أربعة": "4",
    "اربعه": "4",
    "أربعه": "4",

    # --------------------------------------------------------
    # 5
    # --------------------------------------------------------
    "خمسة": "5",
    "خمسه": "5",

    # --------------------------------------------------------
    # 6
    # --------------------------------------------------------
    "ستة": "6",
    "سته": "6",

    # --------------------------------------------------------
    # 7
    # --------------------------------------------------------
    "سبعة": "7",
    "سبعه": "7",

    # --------------------------------------------------------
    # 8
    # --------------------------------------------------------
    "تمانية": "8",
    "تمانيه": "8",
    "ثمانية": "8",
    "ثمانيه": "8",

    # --------------------------------------------------------
    # 9
    # --------------------------------------------------------
    "تسعة": "9",
    "تسعه": "9",

    # --------------------------------------------------------
    # 10
    # --------------------------------------------------------
    "عشرة": "10",
    "عشره": "10",

    # --------------------------------------------------------
    # 11
    # --------------------------------------------------------
    "حداشر": "11",
    "حدعشر": "11",
    "احداشر": "11",
    "أحداشر": "11",

    # --------------------------------------------------------
    # 12
    # --------------------------------------------------------
    "اتناشر": "12",
    "إتناشر": "12",
    "اثناشر": "12",
    "إثناشر": "12",
}


def _replace_arabic_hour_words(
    value: str,
) -> str:
    """
    Convert spoken Arabic / Egyptian hour words into digits.

    Examples:

    خمسة
        -> 5

    خمسة ونص
        -> 5 ونص

    اتناشر
        -> 12

    سبعة الصبح
        -> 7 الصبح
    """

    words = value.split()

    normalized_words = [
        ARABIC_HOUR_WORDS.get(
            word,
            word,
        )
        for word in words
    ]

    return " ".join(
        normalized_words
    )


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def _normalize(
    value: str,
) -> str:
    """
    Normalize spoken / written time input.

    Examples:

    الساعة خمسة
        -> 5

    خمسة ونص
        -> 5 ونص

    الساعة سبعة الصبح
        -> 7 الصبح

    ٥ العصر
        -> 5 العصر
    """

    # --------------------------------------------------------
    # Arabic-Indic digits -> Western digits
    # --------------------------------------------------------

    value = value.translate(
        ARABIC_DIGITS
    )

    # --------------------------------------------------------
    # Basic text normalization
    # --------------------------------------------------------

    value = (
        value
        .strip()
        .lower()
    )

    # --------------------------------------------------------
    # Remove conversational hour prefix.
    #
    # "الساعة خمسة"
    # -> "خمسة"
    # --------------------------------------------------------

    value = (
        value
        .replace("الساعة", "")
        .replace("الساعه", "")
    )

    # --------------------------------------------------------
    # Normalize spaces before word parsing
    # --------------------------------------------------------

    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip()

    # --------------------------------------------------------
    # Spoken Arabic hour words -> digits
    #
    # "خمسة"
    # -> "5"
    #
    # "خمسة ونص"
    # -> "5 ونص"
    #
    # "ستة بالليل"
    # -> "6 بالليل"
    # --------------------------------------------------------

    value = (
        _replace_arabic_hour_words(
            value
        )
    )

    # --------------------------------------------------------
    # Final whitespace normalization
    # --------------------------------------------------------

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
    Detect whether the user explicitly means AM or PM.

    Returns:

        "am"
        "pm"
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
        "الظهر",
        "الضهر",
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
    """
    Convert a parsed hour/minute into one or more possible
    normalized HH:MM values.

    If AM/PM is explicit, return exactly one interpretation.

    If no period is supplied and the hour is between 1 and 11,
    return both AM and PM possibilities. The workflow later
    compares these candidates against REAL available slots.
    """

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
    # Return BOTH possible interpretations when appropriate.
    #
    # Example:
    #
    # "خمسة"
    #
    # -> 05:00
    # -> 17:00
    #
    # Booking / Reschedule workflow decides which candidate
    # matches the actual available slots.
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

    Supports numeric and Egyptian / Arabic spoken forms.

    Examples:

    13:30
        -> ["13:30"]

    1:30 pm
        -> ["13:30"]

    1 ونص
        -> ["01:30", "13:30"]

    خمسة ونص
        -> ["05:30", "17:30"]

    الساعة خمسة
        -> ["05:00", "17:00"]

    خمسة العصر
        -> ["17:00"]

    ستة بالليل
        -> ["18:00"]

    سبعة الصبح
        -> ["07:00"]

    2 العصر
        -> ["14:00"]

    اتناشر
        -> ["12:00", "00:00"]

    The Booking / Reschedule workflow decides which candidate
    matches the real available slots.
    """

    if not value:
        return []

    text = _normalize(
        value
    )

    if not text:
        return []

    period = _detect_period(
        text
    )

    # ========================================================
    # HH:MM
    #
    # Examples:
    #
    # 13:30
    # 5:30
    # 5:30 pm
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
    # HALF HOUR
    #
    # Numeric:
    #
    # 1 ونص
    # 1 ونصف
    #
    # Spoken Arabic is already normalized:
    #
    # خمسة ونص
    # -> 5 ونص
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
    # Numeric:
    #
    # 1 وربع
    #
    # Spoken Arabic:
    #
    # خمسة وربع
    # -> 5 وربع
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
    # Examples:
    #
    # 1
    # 2 العصر
    # 12
    #
    # Spoken Arabic is already normalized:
    #
    # خمسة
    # -> 5
    #
    # خمسة العصر
    # -> 5 العصر
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

# ============================================================
# TIME-ONLY REPLY RESOLVER
# ============================================================

_TIME_REPLY_EDGE_PUNCTUATION = (
    " \t\r\n"
    ".,"
    "،"
    "!?"
    "؟"
    ";"
    "؛"
)


def _is_time_only_expression(
    value: str,
) -> bool:
    """
    Return True only when the normalized text is a standalone
    time reply, not a conversational sentence that happens to
    contain a time.

    Examples accepted:

        5
        17:00
        5 مساء
        5 ونص
        5 و نص العصر

    Examples rejected:

        هل الدكتور موجود 5
        هل فيه موعد 5
        عايز احجز 5
    """

    tokens = value.split()

    if not tokens:
        return False

    # --------------------------------------------------------
    # The expression must START with the actual time value.
    # --------------------------------------------------------

    time_token = tokens[0]

    if (
        re.fullmatch(
            r"\d{1,2}(?::\d{2})?",
            time_token,
        )
        is None
    ):
        return False

    remaining = list(
        tokens[1:]
    )

    # --------------------------------------------------------
    # Optional spoken fraction.
    #
    # Examples:
    #   5 ونص
    #   5 و نص
    #   5 وربع
    #   5 و ربع
    #
    # Fractions are only valid with an hour-only token.
    # --------------------------------------------------------

    if ":" not in time_token:

        if (
            remaining
            and
            remaining[0]
            in {
                "ونص",
                "ونصف",
                "نص",
                "نصف",
                "وربع",
                "ربع",
            }
        ):

            remaining.pop(0)

        elif (
            len(remaining) >= 2
            and
            remaining[0] == "و"
            and
            remaining[1]
            in {
                "نص",
                "نصف",
                "ربع",
            }
        ):

            remaining = (
                remaining[2:]
            )

    # --------------------------------------------------------
    # No text left:
    #
    #   5
    #   17:00
    #   5 ونص
    # --------------------------------------------------------

    if not remaining:
        return True

    # --------------------------------------------------------
    # The only remaining token may be an AM/PM marker that
    # the existing resolver already understands.
    #
    # Reuse _detect_period() rather than duplicating the
    # Arabic/English period vocabulary here.
    # --------------------------------------------------------

    if (
        len(remaining) == 1
        and
        _detect_period(
            remaining[0]
        )
        is not None
    ):
        return True

    # Any additional conversational words make this unsafe
    # for a deterministic fast path.
    return False


def resolve_time_reply_candidates(
    value: str | None,
) -> list[str]:
    """
    Resolve a standalone time reply for deterministic agent
    routing.

    This is intentionally stricter than resolve_time_candidates().

    resolve_time_candidates():
        extracts/interprets time from general text.

    resolve_time_reply_candidates():
        accepts only a standalone time response suitable for
        bypassing LLM understanding safely.

    Provider schedules are NOT handled here. The caller must
    still validate returned candidates against trusted backend
    slots for the current tenant/provider.
    """

    if not value:
        return []

    cleaned = (
        value
        .strip()
        .strip(
            _TIME_REPLY_EDGE_PUNCTUATION
        )
        .strip()
    )

    if not cleaned:
        return []

    normalized = _normalize(
        cleaned
    )

    if not normalized:
        return []

    if not _is_time_only_expression(
        normalized
    ):
        return []

    return resolve_time_candidates(
        cleaned
    )    