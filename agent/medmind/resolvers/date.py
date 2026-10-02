from __future__ import annotations

import re

from datetime import (
    date,
    datetime,
    timedelta,
)

from zoneinfo import ZoneInfo


CAIRO_TZ = ZoneInfo(
    "Africa/Cairo"
)


# ============================================================
# Arabic Text Normalization
# ============================================================

_ARABIC_DIACRITICS_RE = re.compile(
    r"[\u0610-\u061A"
    r"\u064B-\u065F"
    r"\u0670"
    r"\u06D6-\u06ED]"
)


_ARABIC_DIGITS_TRANSLATION = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩"
    "۰۱۲۳۴۵۶۷۸۹",
    "0123456789"
    "0123456789",
)


def normalize_arabic_date_text(
    text: str,
) -> str:
    """
    Normalize Arabic date text before resolving it.

    Examples:
        بُكره       -> بكرة
        بُكرة       -> بكرة
        بكرا        -> بكرة
        بعد بُكره   -> بعد بكرة
        ٢٣/٨        -> 23/8
    """

    normalized = (
        _ARABIC_DIACRITICS_RE.sub(
            "",
            text,
        )
        .replace(
            "ـ",
            "",
        )

        .replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")

        .translate(
            _ARABIC_DIGITS_TRANSLATION
        )
        .strip()
        .lower()
    )

    # Replace punctuation with spaces.
    normalized = re.sub(
        r"[،,.!?؟]+",
        " ",
        normalized,
    )

    # Collapse repeated whitespace.
    normalized = re.sub(
        r"\s+",
        " ",
        normalized,
    ).strip()

    # Normalize Egyptian Arabic variants.
    replacements = {
        "بعد بكره": "بعد بكرة",
        "بعد بكرا": "بعد بكرة",
        "بكره": "بكرة",
        "بكرا": "بكرة",
    }

    # Longer expressions first.
    for source, target in replacements.items():

        normalized = normalized.replace(
            source,
            target,
        )

    return normalized


# ============================================================
# Current Cairo Date
# ============================================================


def cairo_today() -> date:

    return datetime.now(
        CAIRO_TZ
    ).date()


# ============================================================
# Phrase Matching
# ============================================================


def _contains_phrase(
    text: str,
    phrases: set[str],
) -> bool:
    """
    Check whether a date expression occurs inside a longer
    caller sentence.

    Example:
        "احجزلي بكرة"
        -> contains "بكرة"
    """

    padded_text = (
        f" {text} "
    )

    for phrase in phrases:

        padded_phrase = (
            f" {phrase} "
        )

        if (
            padded_phrase
            in padded_text
        ):

            return True

    return False


# ============================================================
# Date Resolver
# ============================================================


def resolve_date(
    value: str | None,
    *,
    today: date | None = None,
) -> date | None:
    """
    Resolve common Arabic / English date expressions
    into an absolute date.

    Supported examples:

        النهارده
        النهاردة
        اليوم
        today

        بكرة
        بكره
        بُكره
        بكرا
        tomorrow

        بعد بكرة
        بعد بكره
        بعد بُكره
        day after tomorrow

        احجزلي بكرة
        عايز الموعد بكرة
        ممكن بعد بكرة

        2026-08-20

        20-08-2026
        20/08/2026

        20-8
        20/8

        ٢٠/٨
        ٢٣/٨
    """

    if not value:
        return None

    current_date = (
        today
        or cairo_today()
    )

    # IMPORTANT:
    # All date parsing now uses the normalized text.
    text = (
        normalize_arabic_date_text(
            value
        )
    )

    if not text:
        return None

    # ========================================================
    # RELATIVE DATES
    # ========================================================

    today_values = {
        "النهارده",
        "النهاردة",
        "اليوم",
        "today",
    }

    tomorrow_values = {
        "بكرة",
        "غدا",
        "tomorrow",
    }

    day_after_tomorrow_values = {
        "بعد بكرة",
        "بعد غد",
        "day after tomorrow",
        "the day after tomorrow",
    }

    # IMPORTANT:
    # Check "day after tomorrow" BEFORE "tomorrow".
    #
    # Otherwise:
    # "بعد بكرة"
    # could accidentally match "بكرة".
    if _contains_phrase(
        text,
        day_after_tomorrow_values,
    ):

        return (
            current_date
            + timedelta(
                days=2
            )
        )

    if _contains_phrase(
        text,
        today_values,
    ):

        return current_date

    if _contains_phrase(
        text,
        tomorrow_values,
    ):

        return (
            current_date
            + timedelta(
                days=1
            )
        )

    # ========================================================
    # WEEKDAYS
    #
    # Resolve the nearest occurrence of an Arabic / English
    # weekday.
    #
    # Python weekday():
    # Monday=0 ... Sunday=6
    # ========================================================

    weekday_values: dict[
        int,
        set[str],
    ] = {
        0: {
            "الاتنين",
            "الاثنين",
            "monday",
        },

        1: {
            "التلات",
            "الثلاثاء",
            "الثلاثا",
            "tuesday",
        },

        2: {
            "الاربع",
            "الاربعاء",
            "wednesday",
        },

        3: {
            "الخميس",
            "thursday",
        },

        4: {
            "الجمعة",
            "الجمعه",
            "friday",
        },

        5: {
            "السبت",
            "saturday",
        },

        6: {
            "الاحد",
            "الأحد",
            "sunday",
        },
    }

    for (
        target_weekday,
        weekday_phrases,
    ) in weekday_values.items():

        if not _contains_phrase(
            text,
            weekday_phrases,
        ):
            continue

        days_ahead = (
            target_weekday
            - current_date.weekday()
        ) % 7

        return (
            current_date
            + timedelta(
                days=days_ahead
            )
        )
    # ========================================================
    # ISO
    # YYYY-MM-DD
    # ========================================================

    iso_match = re.search(
        r"\b"
        r"(\d{4})"
        r"-"
        r"(\d{1,2})"
        r"-"
        r"(\d{1,2})"
        r"\b",
        text,
    )

    if iso_match:

        year_value = int(
            iso_match.group(
                1
            )
        )

        month_value = int(
            iso_match.group(
                2
            )
        )

        day_value = int(
            iso_match.group(
                3
            )
        )

        try:

            return date(
                year_value,
                month_value,
                day_value,
            )

        except ValueError:

            return None

    # ========================================================
    # DD-MM-YYYY / DD/MM/YYYY
    # ========================================================

    full_match = re.search(
        r"\b"
        r"(\d{1,2})"
        r"[-/]"
        r"(\d{1,2})"
        r"[-/]"
        r"(\d{4})"
        r"\b",
        text,
    )

    if full_match:

        day_value = int(
            full_match.group(
                1
            )
        )

        month_value = int(
            full_match.group(
                2
            )
        )

        year_value = int(
            full_match.group(
                3
            )
        )

        try:

            return date(
                year_value,
                month_value,
                day_value,
            )

        except ValueError:

            return None

    # ========================================================
    # DD-MM / DD/MM
    #
    # Assume current year.
    # If the date already passed, use next year.
    # ========================================================

    short_match = re.search(
        r"\b"
        r"(\d{1,2})"
        r"[-/]"
        r"(\d{1,2})"
        r"\b",
        text,
    )

    if short_match:

        day_value = int(
            short_match.group(
                1
            )
        )

        month_value = int(
            short_match.group(
                2
            )
        )

        try:

            candidate = date(
                current_date.year,
                month_value,
                day_value,
            )

        except ValueError:

            return None

        if (
            candidate
            < current_date
        ):

            try:

                candidate = date(
                    current_date.year
                    + 1,
                    month_value,
                    day_value,
                )

            except ValueError:

                return None

        return candidate

    return None