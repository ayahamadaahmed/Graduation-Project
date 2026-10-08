from __future__ import annotations

import re
from datetime import date


ARABIC_DIGIT_TRANSLATION = str.maketrans(
    {
        # Arabic-Indic digits
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

        # Extended Arabic-Indic digits
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
    }
)

def normalize_arabic_digits(
    text: str,
) -> str:
    """
    Normalize Arabic-Indic and extended Arabic-Indic
    numerals to ASCII digits before date/time parsing.

    This is a text-to-speech preprocessing step only.
    """

    return text.translate(
        ARABIC_DIGIT_TRANSLATION
    )

# ============================================================
# Booking reference patterns
# ============================================================

BOOKING_REFERENCE_CLAUSE_PATTERN = re.compile(
    r"(?:"
    r"رقم\s+الحجز"
    r"|كود\s+الحجز"
    r"|booking\s+(?:reference|code|number)"
    r")"
    r"\s*[:：]?\s*"
    r"APT-[A-Za-z0-9-]+"
    r"[.!؟]?",
    re.IGNORECASE,
)

BOOKING_REFERENCE_PATTERN = re.compile(
    r"\bAPT-[A-Za-z0-9-]+\b",
    re.IGNORECASE,
)


# ============================================================
# Date and time patterns
# ============================================================

ISO_DATE_PATTERN = re.compile(
    r"\b(\d{4})-(\d{2})-(\d{2})\b"
)

ARABIC_TIME_WITH_PREFIX_PATTERN = re.compile(
    r"\bالساعة\s+([01]\d|2[0-3]):([0-5]\d)\b"
)

TIME_PATTERN = re.compile(
    r"\b([01]\d|2[0-3]):([0-5]\d)\b"
)


# ============================================================
# Egyptian Arabic normalization patterns
# ============================================================

ARABIC_APPOINTMENT_WORD_PATTERN = re.compile(
    r"(?<!\w)"
    r"(?P<article>ال)?"
    r"(?:موعد|معاد)"
    r"(?P<suffix>كم|نا|ها|ك|ه|ي)?"
    r"(?!\w)"
)

EGYPTIAN_BOOKING_PHRASE_REPLACEMENTS = (
    (
        re.compile(
            r"تم\s+تأكيد\s+"
            r"(?:الحجز|حجزك|الموعد|موعدك)\s+"
            r"بنجاح\s*[.!؟]?"
        ),
        "تمام، حجزك اتأكد.",
    ),
    (
        re.compile(
            r"تم\s+حجز\s+"
            r"(?:الموعد|موعدك)\s+"
            r"بنجاح\s*[.!؟]?"
        ),
        "تمام، حجزك اتأكد.",
    ),
    (
        re.compile(
            r"تم\s+إلغاء\s+"
            r"(?:الحجز|حجزك|الموعد|موعدك)\s+"
            r"بنجاح\s*[.!؟]?"
        ),
        "تمام، حجزك اتلغى.",
    ),
    (
        re.compile(
            r"تمت?\s+"
            r"(?:تغيير|إعادة\s+جدولة)\s+"
            r"(?:"
            r"ميعاد\s+الحجز"
            r"|موعد\s+الحجز"
            r"|الموعد"
            r"|موعدك"
            r")\s+"
            r"بنجاح\s*[.!؟]?"
        ),
        "تمام، ميعاد حجزك اتغير.",
    ),
)


# ============================================================
# Arabic date vocabulary
# ============================================================

ARABIC_MONTHS = {
    1: "يناير",
    2: "فبراير",
    3: "مارس",
    4: "أبريل",
    5: "مايو",
    6: "يونيو",
    7: "يوليو",
    8: "أغسطس",
    9: "سبتمبر",
    10: "أكتوبر",
    11: "نوفمبر",
    12: "ديسمبر",
}

ARABIC_WEEKDAYS = {
    0: "الاثنين",
    1: "الثلاثاء",
    2: "الأربعاء",
    3: "الخميس",
    4: "الجمعة",
    5: "السبت",
    6: "الأحد",
}

ARABIC_DAYS = {
    1: "واحد",
    2: "اتنين",
    3: "تلاتة",
    4: "أربعة",
    5: "خمسة",
    6: "ستة",
    7: "سبعة",
    8: "تمانية",
    9: "تسعة",
    10: "عشرة",
    11: "حداشر",
    12: "اتناشر",
    13: "تلتاشر",
    14: "أربعتاشر",
    15: "خمستاشر",
    16: "ستاشر",
    17: "سبعتاشر",
    18: "تمنتاشر",
    19: "تسعتاشر",
    20: "عشرين",
    21: "واحد وعشرين",
    22: "اتنين وعشرين",
    23: "تلاتة وعشرين",
    24: "أربعة وعشرين",
    25: "خمسة وعشرين",
    26: "ستة وعشرين",
    27: "سبعة وعشرين",
    28: "تمانية وعشرين",
    29: "تسعة وعشرين",
    30: "تلاتين",
    31: "واحد وتلاتين",
}


# ============================================================
# Egyptian Arabic clock vocabulary
# ============================================================

ARABIC_HOURS = {
    1: "واحدة",
    2: "اتنين",
    3: "تلاتة",
    4: "أربعة",
    5: "خمسة",
    6: "ستة",
    7: "سبعة",
    8: "تمانية",
    9: "تسعة",
    10: "عشرة",
    11: "حداشر",
    12: "اتناشر",
}

ARABIC_SMALL_NUMBERS = {
    1: "واحد",
    2: "اتنين",
    3: "تلاتة",
    4: "أربعة",
    5: "خمسة",
    6: "ستة",
    7: "سبعة",
    8: "تمانية",
    9: "تسعة",
    10: "عشرة",
    11: "حداشر",
    12: "اتناشر",
    13: "تلتاشر",
    14: "أربعتاشر",
    15: "خمستاشر",
    16: "ستاشر",
    17: "سبعتاشر",
    18: "تمنتاشر",
    19: "تسعتاشر",
}

ARABIC_TENS = {
    20: "عشرين",
    30: "تلاتين",
    40: "أربعين",
    50: "خمسين",
}

ARABIC_FEW_MINUTES = {
    3: "تلات دقايق",
    4: "أربع دقايق",
    5: "خمس دقايق",
    6: "ست دقايق",
    7: "سبع دقايق",
    8: "تمن دقايق",
    9: "تسع دقايق",
    10: "عشر دقايق",
}


# ============================================================
# Booking reference removal
# ============================================================

def _remove_booking_reference(
    text: str,
) -> str:
    """
    Remove the booking reference from spoken output only.

    The original backend response and structured booking data
    remain unchanged.
    """

    cleaned = BOOKING_REFERENCE_CLAUSE_PATTERN.sub(
        "",
        text,
    )

    cleaned = BOOKING_REFERENCE_PATTERN.sub(
        "",
        cleaned,
    )

    cleaned = re.sub(
        r"[ \t]{2,}",
        " ",
        cleaned,
    )

    cleaned = re.sub(
        r"\n{3,}",
        "\n\n",
        cleaned,
    )

    return cleaned.strip()


# ============================================================
# Egyptian Arabic text normalization
# ============================================================

def _replace_arabic_appointment_word(
    match: re.Match[str],
) -> str:
    article = (
        match.group("article")
        or ""
    )

    suffix = (
        match.group("suffix")
        or ""
    )

    return (
        f"{article}ميعاد{suffix}"
    )


def normalize_egyptian_voice_text(
    text: str,
) -> str:
    """
    Convert formal booking phrases into natural Egyptian Arabic.

    This function is used only on the spoken TTS text.
    It does not change the backend response or stored data.
    """

    normalized = text

    for (
        pattern,
        replacement,
    ) in EGYPTIAN_BOOKING_PHRASE_REPLACEMENTS:
        normalized = pattern.sub(
            replacement,
            normalized,
        )

    normalized = ARABIC_APPOINTMENT_WORD_PATTERN.sub(
        _replace_arabic_appointment_word,
        normalized,
    )

    normalized = re.sub(
        r"[ \t]{2,}",
        " ",
        normalized,
    )

    normalized = re.sub(
        r"\.{2,}",
        ".",
        normalized,
    )

    return normalized.strip()


# ============================================================
# Arabic time helpers
# ============================================================

def _replace_arabic_time_with_prefix(
    match: re.Match[str],
) -> str:
    value = (
        f"{match.group(1)}:"
        f"{match.group(2)}"
    )

    return format_arabic_time(
        value
    )


def _arabic_day_period(
    hour_24: int,
) -> str:
    """
    Return a natural Egyptian-Arabic day period.

    Examples:
        08:00 -> الصبح
        12:00 -> الضهر
        17:00 -> العصر
        20:00 -> بالليل
    """

    if 5 <= hour_24 < 12:
        return "الصبح"

    if 12 <= hour_24 < 16:
        return "الضهر"

    if 16 <= hour_24 < 19:
        return "العصر"

    return "بالليل"


def _hour_12(
    hour_24: int,
) -> int:
    hour = hour_24 % 12

    if hour == 0:
        return 12

    return hour


def _arabic_number_under_sixty(
    number: int,
) -> str:
    """
    Convert a number from 1 to 59 into Egyptian Arabic words.
    """

    small_number = ARABIC_SMALL_NUMBERS.get(
        number
    )

    if small_number:
        return small_number

    tens = (
        number // 10
    ) * 10

    ones = (
        number % 10
    )

    tens_word = ARABIC_TENS.get(
        tens
    )

    if not tens_word:
        return str(number)

    if not ones:
        return tens_word

    return (
        f"{ARABIC_SMALL_NUMBERS[ones]} "
        f"و{tens_word}"
    )


def _arabic_minute_phrase(
    minute: int,
) -> str:
    """
    Return natural Egyptian-Arabic minute wording.

    Examples:
        12:00 -> اتناشر
        12:15 -> اتناشر وربع
        12:30 -> اتناشر ونص
        12:45 -> واحدة إلا ربع
    """

    if minute == 0:
        return ""

    if minute == 15:
        return "وربع"

    if minute == 30:
        return "ونص"

    if minute == 45:
        return "إلا ربع"

    if minute == 1:
        return "ودقيقة"

    if minute == 2:
        return "ودقيقتين"

    few_minutes = ARABIC_FEW_MINUTES.get(
        minute
    )

    if few_minutes:
        return f"و{few_minutes}"

    return (
        f"و{_arabic_number_under_sixty(minute)} "
        f"دقيقة"
    )


# ============================================================
# Arabic date formatter
# ============================================================

def format_arabic_date(
    value: str,
) -> str:
    try:
        parsed = date.fromisoformat(
            value
        )

    except ValueError:
        return value

    weekday = ARABIC_WEEKDAYS[
        parsed.weekday()
    ]

    month = ARABIC_MONTHS[
        parsed.month
    ]

    day = ARABIC_DAYS.get(
        parsed.day,
        str(parsed.day),
    )

    return (
        f"{weekday} "
        f"{day} "
        f"{month}"
    )


# ============================================================
# Arabic time formatter
# ============================================================

def format_arabic_time(
    value: str,
) -> str:
    try:
        hour_text, minute_text = value.split(
            ":",
            maxsplit=1,
        )

        hour_24 = int(
            hour_text
        )

        minute = int(
            minute_text
        )

    except (
        ValueError,
        AttributeError,
    ):
        return value

    if not (
        0 <= hour_24 <= 23
        and
        0 <= minute <= 59
    ):
        return value

    hour_12 = _hour_12(
        hour_24
    )

    period = _arabic_day_period(
        hour_24
    )

    # 12:45 -> واحدة إلا ربع
    # 13:45 -> اتنين إلا ربع
    if minute == 45:
        next_hour_24 = (
            hour_24 + 1
        ) % 24

        next_hour_12 = _hour_12(
            next_hour_24
        )

        spoken_hour = ARABIC_HOURS[
            next_hour_12
        ]

        next_period = _arabic_day_period(
            next_hour_24
        )

        return (
            f"الساعة "
            f"{spoken_hour} "
            f"إلا ربع "
            f"{next_period}"
        )

    spoken_hour = ARABIC_HOURS[
        hour_12
    ]

    minute_phrase = _arabic_minute_phrase(
        minute
    )

    if minute_phrase:
        return (
            f"الساعة "
            f"{spoken_hour} "
            f"{minute_phrase} "
            f"{period}"
        )

    return (
        f"الساعة "
        f"{spoken_hour} "
        f"{period}"
    )


# ============================================================
# English date vocabulary
# ============================================================

ENGLISH_MONTHS = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}

ENGLISH_WEEKDAYS = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    5: "Saturday",
    6: "Sunday",
}


# ============================================================
# English helpers
# ============================================================

def _english_ordinal(
    number: int,
) -> str:
    if (
        10
        <= number % 100
        <= 20
    ):
        suffix = "th"

    else:
        suffix = {
            1: "st",
            2: "nd",
            3: "rd",
        }.get(
            number % 10,
            "th",
        )

    return (
        f"{number}{suffix}"
    )


def format_english_date(
    value: str,
) -> str:
    try:
        parsed = date.fromisoformat(
            value
        )

    except ValueError:
        return value

    weekday = ENGLISH_WEEKDAYS[
        parsed.weekday()
    ]

    month = ENGLISH_MONTHS[
        parsed.month
    ]

    day = _english_ordinal(
        parsed.day
    )

    return (
        f"{weekday}, "
        f"{month} "
        f"{day}"
    )


def format_english_time(
    value: str,
) -> str:
    try:
        hour_text, minute_text = value.split(
            ":",
            maxsplit=1,
        )

        hour_24 = int(
            hour_text
        )

        minute = int(
            minute_text
        )

    except (
        ValueError,
        AttributeError,
    ):
        return value

    if not (
        0 <= hour_24 <= 23
        and
        0 <= minute <= 59
    ):
        return value

    period = (
        "AM"
        if hour_24 < 12
        else "PM"
    )

    hour = (
        hour_24 % 12
    )

    if hour == 0:
        hour = 12

    if minute == 0:
        return (
            f"{hour} {period}"
        )

    return (
        f"{hour}:"
        f"{minute:02d} "
        f"{period}"
    )


# ============================================================
# Replacement functions
# ============================================================

def _replace_arabic_date(
    match: re.Match[str],
) -> str:
    return format_arabic_date(
        match.group(0)
    )


def _replace_arabic_time(
    match: re.Match[str],
) -> str:
    return format_arabic_time(
        match.group(0)
    )


def _replace_english_date(
    match: re.Match[str],
) -> str:
    return format_english_date(
        match.group(0)
    )


def _replace_english_time(
    match: re.Match[str],
) -> str:
    return format_english_time(
        match.group(0)
    )


def format_arabic_time_compact(
    value: str,
) -> str:
    """
    Format an Arabic time without repeating the word الساعة.

    Used when the response contains a list of several times.
    """

    formatted = format_arabic_time(
        value
    )

    prefix = "الساعة "

    if formatted.startswith(
        prefix
    ):
        return formatted[
            len(prefix):
        ]

    return formatted


def _replace_arabic_time_compact(
    match: re.Match[str],
) -> str:
    return format_arabic_time_compact(
        match.group(0)
    )


# ============================================================
# Public API
# ============================================================

def prepare_text_for_speech(
    text: str,
    *,
    language: str = "ar",
) -> str:
    """
    Prepare backend text before sending it to TTS.

    The transformation affects spoken output only.
    The backend response, structured state and database
    values remain unchanged.
    """

    clean_text = normalize_arabic_digits(
        text.strip()
    )

    # Hide the long booking reference from spoken output.
    clean_text = _remove_booking_reference(
        clean_text
    )

    if not clean_text:
        return clean_text

    normalized_language = (
        language
        .strip()
        .lower()
    )

    # ========================================================
    # English
    # ========================================================

    if normalized_language.startswith(
        "en"
    ):
        formatted = ISO_DATE_PATTERN.sub(
            _replace_english_date,
            clean_text,
        )

        formatted = TIME_PATTERN.sub(
            _replace_english_time,
            formatted,
        )

        return formatted

    # ========================================================
    # Arabic
    # ========================================================

    # Convert formal Arabic booking wording into Egyptian
    # Arabic before sending the reply to TTS.
    clean_text = normalize_egyptian_voice_text(
        clean_text
    )

    formatted = ISO_DATE_PATTERN.sub(
        _replace_arabic_date,
        clean_text,
    )

    time_count = len(
        TIME_PATTERN.findall(
            formatted
        )
    )

    # When several appointment times are returned, do not
    # repeat الساعة before every option.
    if time_count >= 3:
        formatted = TIME_PATTERN.sub(
            _replace_arabic_time_compact,
            formatted,
        )

    else:
        # Replace "الساعة 12:30" as one unit to prevent:
        # الساعة الساعة اتناشر ونص الضهر
        formatted = ARABIC_TIME_WITH_PREFIX_PATTERN.sub(
            _replace_arabic_time_with_prefix,
            formatted,
        )

        formatted = TIME_PATTERN.sub(
            _replace_arabic_time,
            formatted,
        )

    return formatted