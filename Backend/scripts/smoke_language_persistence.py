from medmind.language import (
    detect_language,
    is_language_neutral,
    resolve_conversation_language,
)


# ============================================================
# STATELESS DETECTION
# ============================================================

assert (
    detect_language(
        "عايزة أغير ميعاد الحجز"
    )
    == "ar"
)

assert (
    detect_language(
        "I want to reschedule"
    )
    == "en"
)


# ============================================================
# NEUTRAL DETECTION
# ============================================================

neutral_messages = [
    "29901010000001",
    "20/8",
    "2026-08-20",
    "14:30",
    "APT-260818-7733DB38",
    "955ed459-1f70-5bf3-a88c-709019974a1f",
]

for message in neutral_messages:

    assert (
        is_language_neutral(
            message
        )
        is True
    )


# ============================================================
# NORMAL LANGUAGE MUST NOT BE NEUTRAL
# ============================================================

assert (
    is_language_neutral(
        "hello"
    )
    is False
)

assert (
    is_language_neutral(
        "عايزة احجز"
    )
    is False
)

assert (
    is_language_neutral(
        "book 20/8"
    )
    is False
)


# ============================================================
# ARABIC SESSION PERSISTENCE
# ============================================================

language = "ar"

for message in neutral_messages:

    language = (
        resolve_conversation_language(
            text=message,
            previous_language=
                language,
        )
    )

    assert (
        language
        == "ar"
    )


# ============================================================
# ENGLISH SESSION PERSISTENCE
# ============================================================

language = "en"

for message in neutral_messages:

    language = (
        resolve_conversation_language(
            text=message,
            previous_language=
                language,
        )
    )

    assert (
        language
        == "en"
    )


# ============================================================
# REAL LANGUAGE SWITCH
# ============================================================

language = (
    resolve_conversation_language(
        text="I want another appointment",
        previous_language="ar",
    )
)

assert (
    language
    == "en"
)

language = (
    resolve_conversation_language(
        text="عايزة ميعاد تاني",
        previous_language="en",
    )
)

assert (
    language
    == "ar"
)


print(
    "LANGUAGE PERSISTENCE TEST PASSED"
)