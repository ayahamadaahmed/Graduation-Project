from __future__ import annotations

import re
from typing import Literal


Language = Literal[
    "ar",
    "en",
    "mixed",
]


# ============================================================
# CHARACTER PATTERNS
# ============================================================

ARABIC_PATTERN = re.compile(
    r"[\u0600-\u06FF]"
)

ENGLISH_PATTERN = re.compile(
    r"[A-Za-z]"
)


# ============================================================
# NEUTRAL MESSAGE PATTERNS
#
# These messages carry structured data, not a conversation
# language preference.
#
# Examples:
#
# 29901010000001
# 20/8
# 14:30
# APT-260818-7733DB38
# UUID values
# ============================================================

NUMERIC_STRUCTURED_PATTERN = re.compile(
    r"^[\d\s:/.\-+()]+$"
)

IDENTIFIER_PATTERN = re.compile(
    r"^[A-Za-z0-9_-]+$"
)


def is_language_neutral(
    text: str,
) -> bool:
    """
    Return True when the message is structured data
    rather than a meaningful Arabic/English utterance.

    Neutral messages must NOT change the current
    conversation language.
    """

    normalized = (
        text
        .strip()
    )

    if not normalized:
        return True

    # --------------------------------------------------------
    # Pure numeric / date / time / phone-like input
    # --------------------------------------------------------

    if NUMERIC_STRUCTURED_PATTERN.fullmatch(
        normalized
    ):
        return True

    # --------------------------------------------------------
    # Identifier-like values
    #
    # Examples:
    # APT-260818-7733DB38
    # 955ed459-1f70-5bf3-a88c-709019974a1f
    #
    # Require at least one digit so normal English words
    # such as "hello" are NOT treated as neutral.
    # --------------------------------------------------------

    if (
        IDENTIFIER_PATTERN.fullmatch(
            normalized
        )
        and
        any(
            char.isdigit()
            for char
            in normalized
        )
    ):
        return True

    return False


# ============================================================
# STATELESS LANGUAGE DETECTION
# ============================================================

def detect_language(
    text: str,
) -> Language:
    """
    Detect whether meaningful text is mainly:
    - Arabic
    - English
    - Mixed

    This function is stateless.

    Conversation-level language persistence is handled
    separately by resolve_conversation_language().
    """

    arabic_count = len(
        ARABIC_PATTERN.findall(
            text
        )
    )

    english_count = len(
        ENGLISH_PATTERN.findall(
            text
        )
    )

    total = (
        arabic_count
        + english_count
    )

    if total == 0:
        return "ar"

    if (
        arabic_count > 0
        and
        english_count == 0
    ):
        return "ar"

    if (
        english_count > 0
        and
        arabic_count == 0
    ):
        return "en"

    arabic_ratio = (
        arabic_count
        / total
    )

    if arabic_ratio >= 0.70:
        return "ar"

    if arabic_ratio <= 0.30:
        return "en"

    return "mixed"


# ============================================================
# CONVERSATION-AWARE LANGUAGE
# ============================================================

def resolve_conversation_language(
    *,
    text: str,
    previous_language: Language,
) -> Language:
    """
    Resolve the language for the current conversation turn.

    Structured / neutral values keep the previous session
    language instead of switching Arabic <-> English.
    """

    if is_language_neutral(
        text
    ):
        return previous_language

    return detect_language(
        text
    )