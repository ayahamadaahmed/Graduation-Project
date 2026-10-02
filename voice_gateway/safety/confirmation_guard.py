from __future__ import annotations

import re
import unicodedata


CRITICAL_DUAL_STT_STAGES = {
    "awaiting_phone_confirmation",
    "awaiting_confirmation",
    "awaiting_cancel_confirmation",
    "awaiting_reschedule_confirmation",
}


def _strip_diacritics(
    text: str,
) -> str:

    return "".join(
        character
        for character in unicodedata.normalize(
            "NFKD",
            text,
        )
        if not unicodedata.combining(
            character
        )
    )


def _normalize_confirmation_text(
    transcript: str,
) -> str:

    return (
        _strip_diacritics(
            transcript
        )
        .replace("ـ", "")
        .replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ٱ", "ا")
        .lower()
        .strip()
    )


def classify_confirmation_action(
    transcript: str,
    *,
    stage: str | None = None,
) -> str | None:
    """
    Conservative stage-aware confirmation classifier.

    "confirm" means:
        approve the action currently being proposed.

    "reject" means:
        reject the action currently being proposed.

    This does not replace MedMind NLU.
    It is used only for critical dual-STT disagreement checks.
    """

    text = (
        _normalize_confirmation_text(
            transcript
        )
    )

    tokens = set(
        re.findall(
            r"[a-z]+|[\u0600-\u06ff]+",
            text,
        )
    )

    normalized_stage = (
        stage.strip().lower()
        if stage
        else ""
    )

    # --------------------------------------------------
    # Explicit yes / no
    # --------------------------------------------------

    yes_tokens = {
        "ايوه",
        "ايوا",
        "اه",
        "نعم",
        "yes",
    }

    no_tokens = {
        "لا",
        "لاء",
        "لالا",
        "no",
    }

    has_confirm = bool(
        tokens & yes_tokens
    )

    has_reject = bool(
        tokens & no_tokens
    )

    # --------------------------------------------------
    # Stage-specific action wording
    # --------------------------------------------------

    if (
        normalized_stage
        == "awaiting_cancel_confirmation"
    ):

        cancel_tokens = {
            "الغي",
            "الغى",
            "الغاء",
            "cancel",
        }

        has_confirm = (
            has_confirm
            or bool(
                tokens & cancel_tokens
            )
        )

    elif (
        normalized_stage
        == "awaiting_reschedule_confirmation"
    ):

        reschedule_tokens = {
            "غير",
            "اغير",
            "تغيير",
            "reschedule",
        }

        has_confirm = (
            has_confirm
            or bool(
                tokens & reschedule_tokens
            )
        )

    elif (
        normalized_stage
        == "awaiting_phone_confirmation"
    ):

        phone_confirm_tokens = {
            "صح",
            "صحيح",
            "correct",
        }

        phone_reject_tokens = {
            "غلط",
            "خطا",
            "wrong",
        }

        has_confirm = (
            has_confirm
            or bool(
                tokens
                & phone_confirm_tokens
            )
        )

        has_reject = (
            has_reject
            or bool(
                tokens
                & phone_reject_tokens
            )
        )

    else:

        # Booking/general confirmation.
        booking_confirm_tokens = {
            "اكد",
            "اكدي",
            "اكدوا",
            "confirm",
        }

        booking_reject_tokens = {
            "الغي",
            "الغى",
            "الغاء",
            "cancel",
        }

        has_confirm = (
            has_confirm
            or bool(
                tokens
                & booking_confirm_tokens
            )
        )

        has_reject = (
            has_reject
            or bool(
                tokens
                & booking_reject_tokens
            )
        )

    # Both or neither -> ambiguous.
    if has_confirm == has_reject:
        return None

    if has_confirm:
        return "confirm"

    return "reject"


def critical_stt_actions_disagree(
    *,
    hamsa_transcript: str,
    deepgram_transcript: str,
    stage: str | None = None,
) -> bool:

    hamsa_action = (
        classify_confirmation_action(
            hamsa_transcript,
            stage=stage,
        )
    )

    deepgram_action = (
        classify_confirmation_action(
            deepgram_transcript,
            stage=stage,
        )
    )

    return bool(
        hamsa_action
        and deepgram_action
        and hamsa_action
        != deepgram_action
    )

def get_critical_stt_retry_prompt(
    stage: str,
) -> str:

    normalized_stage = (
        stage.strip().lower()
    )

    if (
        normalized_stage
        == "awaiting_phone_confirmation"
    ):

        return (
            "معلش، أتأكد تاني: "
            "رقم الموبايل اللي قلته صح ولا لأ؟"
        )

    if (
        normalized_stage
        == "awaiting_cancel_confirmation"
    ):

        return (
            "معلش، أتأكد تاني: "
            "ألغي الحجز ولا لأ؟"
        )

    if (
        normalized_stage
        == "awaiting_reschedule_confirmation"
    ):

        return (
            "معلش، أتأكد تاني: "
            "أغيّر الميعاد ولا لأ؟"
        )

    return (
        "معلش، أتأكد تاني: "
        "أأكد الحجز ولا لأ؟"
    )