from __future__ import annotations

from typing import Any
import uuid
import asyncio
import json
import logging
import os
import re
import struct
import unicodedata

from voice_gateway.text.voice_formatter import (
    prepare_text_for_speech,
)
from voice_gateway.safety.name_guard import (
    NAME_DUAL_STT_STAGES,
    resolve_name_stage_transcript,
)
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from voice_gateway.audio.codec import (
    create_slin24_vad_resampler,
    pcm16_24k_to_ulaw8k,
    ulaw_to_pcm16,
)

from voice_gateway.audio.vad import StreamingVAD
from voice_gateway.config import (
    get_voice_settings,
    load_environment,
)
from voice_gateway.log_safety import (
    exception_fields,
    install_log_safety,
)
from voice_gateway.medmind_client import (
    MedMindClient,
    session_fingerprint,
)
from voice_gateway.providers.deepgram_stt import DeepgramStreamingSTT
from voice_gateway.providers.elevenlabs_tts import ElevenLabsTTS
from voice_gateway.providers.hamsa_stt import HamsaSTT
from voice_gateway.providers.hamsa_tts import HamsaTTS
from voice_gateway.session import VoiceSession
from voice_gateway.transport.asterisk_media import (
    flush_media,
    send_media_audio,
    send_media_chunk,
    start_media_buffering,
    stop_media_buffering,
)

from voice_gateway.safety.confirmation_guard import (
    CRITICAL_DUAL_STT_STAGES,
    classify_confirmation_action,
    critical_stt_actions_disagree,
    get_critical_stt_retry_prompt,
)

from voice_gateway.post_call_client import (
    PostCallClient,
)
from voice_gateway.media_auth import (
    POLICY_VIOLATION_CLOSE_CODE,
    MediaAuthError,
    MediaAuthorization,
    auth_timeout_seconds,
    authorize_media_start,
)
# ============================================================
# Environment
# ============================================================

load_environment()

VOICE_SETTINGS = get_voice_settings()
# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(
    "medmind.voice_gateway"
)

# Tracebacks keep types and line numbers but never exception messages.
install_log_safety(logger)

# uvicorn logs exceptions that escape asterisk_media (it re-raises) through
# "uvicorn.error" with logger.exception(...). Process-local: this covers the
# Voice Gateway process only. uvicorn configures logging before importing
# this module, and a later dictConfig keeps logger filters. Not covered:
# asyncio's unhandled-task logger, Gunicorn's own loggers, other servers.
install_log_safety(logging.getLogger("uvicorn.error"))


# ============================================================
# FastAPI
# ============================================================

app = FastAPI(
    title="MedMind Voice Gateway",
    version="0.1.0",
)


# ============================================================
# Turn Taking / Digit Collection
# ============================================================
DEFAULT_TURN_END_GRACE_SECONDS = (
    VOICE_SETTINGS.default_turn_end_grace_seconds
)

DIGIT_TURN_END_GRACE_SECONDS = (
    VOICE_SETTINGS.digit_turn_end_grace_seconds
)

DIGIT_MAX_UTTERANCE_SECONDS = (
    VOICE_SETTINGS.digit_max_utterance_seconds
)

HAMSA_PREROLL_SECONDS = (
    VOICE_SETTINGS.hamsa_preroll_seconds
)

HAMSA_NORMAL_SOFT_TIMEOUT_SECONDS = (
    VOICE_SETTINGS.hamsa_normal_soft_timeout_seconds
)

HAMSA_FAST_NORMAL_BUDGET_SECONDS = float(
    os.getenv(
        "VOICE_HAMSA_FAST_NORMAL_BUDGET_SECONDS",
        "0.8",
    )
)

HAMSA_DIGIT_SOFT_TIMEOUT_SECONDS = (
    VOICE_SETTINGS.hamsa_digit_soft_timeout_seconds
)

DEEPGRAM_NORMAL_FALLBACK_WAIT_SECONDS = (
    VOICE_SETTINGS.deepgram_normal_fallback_wait_seconds
)

DEEPGRAM_STARTUP_BUFFER_SECONDS = float(
    os.getenv(
        "VOICE_DEEPGRAM_STARTUP_BUFFER_SECONDS",
        "3.0",
    )
)

DIGIT_INCOMPLETE_RETRY_SECONDS = (
    VOICE_SETTINGS.digit_incomplete_retry_seconds
)

# Internal queue marker for TTS-only prompts that must not
# be sent to the MedMind backend.
LOCAL_TTS_PREFIX = "__MEDMIND_LOCAL_TTS__::"

CONVERSATION_TURN_PREFIX = (
    "__MEDMIND_CONVERSATION__::"
)

NATIONAL_ID_DIGIT_STAGES = {
    "awaiting_national_id",

    "awaiting_patient_identity",

    "awaiting_cancel_national_id",
    "awaiting_cancel_identity",

    "awaiting_reschedule_national_id",
    "awaiting_reschedule_identity",
}


DIGIT_COLLECTION_STAGES: dict[
    str,
    int,
] = {
    **{
        stage: 14
        for stage
        in NATIONAL_ID_DIGIT_STAGES
    },

    "awaiting_phone": 11,
}


# ============================================================
# Terminal Voice Call Stages
#
# The final TTS reply MUST be heard before we close the call.
# Therefore these stages only ARM hangup. The websocket is
# actually closed after Asterisk sends MEDIA_BUFFERING_COMPLETED
# for the terminal reply correlation_id.
# ============================================================

TERMINAL_CALL_STAGES = {
    "booking_completed",
    "booking_cancelled_before_create",

    # Current/legacy cancellation terminal names.
    "cancel_completed",
    "cancellation_completed",
    "cancel_already_completed",
    "cancel_declined",
    "cancelled_by_user",
    "already_cancelled",

    "reschedule_completed",
    "reschedule_declined",
}

PENDING_HANGUP_CORRELATION_KEY = (
    "_pending_hangup_correlation_id"
)

PENDING_HANGUP_STAGE_KEY = (
    "_pending_hangup_stage"
)

BARGE_IN_ENABLED = (
    os.getenv(
        "VOICE_BARGE_IN_ENABLED",
        "1",
    )
    .strip()
    == "1"
)

BARGE_IN_MIN_SPEECH_SECONDS = float(
    os.getenv(
        "VOICE_BARGE_IN_MIN_SPEECH_SECONDS",
        "0.0",
    )
)

BARGE_IN_INITIAL_PROTECTION_SECONDS = float(
    os.getenv(
        "VOICE_BARGE_IN_INITIAL_PROTECTION_SECONDS",
        "0.0",
    )
)

BARGE_IN_COOLDOWN_SECONDS = float(
    os.getenv(
        "VOICE_BARGE_IN_COOLDOWN_SECONDS",
        "0.60",
    )
)

# ============================================================
# Fast Pre-VAD Barge-in
#
# Silero remains responsible for turn segmentation.
# This detector is used ONLY to stop outbound audio quickly.
# ============================================================

FAST_BARGE_IN_ENABLED = (
    os.getenv(
        "VOICE_FAST_BARGE_IN_ENABLED",
        "1",
    )
    .strip()
    == "1"
)

FAST_BARGE_IN_ECHO_PROTECTION_SECONDS = float(
    os.getenv(
        "VOICE_FAST_BARGE_IN_ECHO_PROTECTION_SECONDS",
        "0.10",
    )
)

FAST_BARGE_IN_RMS_THRESHOLD = float(
    os.getenv(
        "VOICE_FAST_BARGE_IN_RMS_THRESHOLD",
        "1700",
    )
)

FAST_BARGE_IN_REQUIRED_FRAMES = int(
    os.getenv(
        "VOICE_FAST_BARGE_IN_REQUIRED_FRAMES",
        "2",
    )
)

PLAYBACK_ACTIVE_KEY = (
    "_voice_playback_active"
)

PLAYBACK_CORRELATION_KEY = (
    "_voice_playback_correlation_id"
)

PLAYBACK_STARTED_AT_KEY = (
    "_voice_playback_started_at"
)

LAST_BARGE_IN_AT_KEY = (
    "_voice_last_barge_in_at"
)
# ============================================================
# Post-call actions
# ============================================================

POST_CALL_EVENT_KEY = (
    "post_call_event"
)

POST_CALL_APPOINTMENT_REFERENCE_KEY = (
    "post_call_appointment_reference"
)

POST_CALL_BOOKING_CONFIRMED = (
    "booking_confirmation"
)


def calculate_pcm16_rms(
    pcm16_audio: bytes,
) -> float:
    """
    Calculate RMS energy for signed little-endian PCM16.

    Used only for fast barge-in detection.
    """

    usable_length = (
        len(pcm16_audio)
        - (
            len(pcm16_audio)
            % 2
        )
    )

    if usable_length <= 0:
        return 0.0

    total_squared = 0
    sample_count = 0

    for (
        sample,
    ) in struct.iter_unpack(
        "<h",
        pcm16_audio[
            :usable_length
        ],
    ):

        total_squared += (
            sample
            * sample
        )

        sample_count += 1

    if sample_count == 0:
        return 0.0

    return (
        total_squared
        / sample_count
    ) ** 0.5

def get_turn_end_grace_seconds(
    stage: str | None,
) -> float:
    """
    Keep a longer silence grace for digit collection,
    but use a very small debounce for normal conversation.

    Silero VAD already owns the actual speech boundary.
    This grace only protects against tiny false-end gaps.
    """

    normalized_stage = (
        stage or ""
    ).strip().lower()

    if (
        normalized_stage
        in DIGIT_COLLECTION_STAGES
    ):
        return (
            DIGIT_TURN_END_GRACE_SECONDS
        )

    return (
        DEFAULT_TURN_END_GRACE_SECONDS
    )

def is_valid_digit_candidate_for_stage(
    *,
    stage: str,
    digits: str,
) -> bool:
    """
    Validate a complete voice digit candidate before
    allowing it to win STT arbitration.

    National ID:
        exactly 14 digits.

    Egyptian mobile:
        exactly 11 digits and starts with:
        010 / 011 / 012 / 015.
    """

    normalized_stage = (
        stage
        .strip()
        .lower()
    )

    # ========================================================
    # Egyptian National ID
    # ========================================================

    if normalized_stage == "awaiting_national_id":

        return (
            len(digits) == 14
            and digits.isdigit()
        )

    # ========================================================
    # Egyptian Mobile Number
    # ========================================================

    if normalized_stage == "awaiting_phone":

        return (
            re.fullmatch(
                r"01[0125]\d{8}",
                digits,
            )
            is not None
        )

    # ========================================================
    # Other digit stages
    #
    # Existing length validation remains responsible for them.
    # ========================================================

    return True

def get_expected_digit_count(
    stage: str | None,
) -> int | None:

    normalized_stage = (
        stage or ""
    ).strip().lower()

    return (
        DIGIT_COLLECTION_STAGES.get(
            normalized_stage
        )
    )


def get_incomplete_digit_prompt(
    stage: str | None,
) -> str:

    normalized_stage = (
        stage or ""
    ).strip().lower()

    if (
        normalized_stage
        in NATIONAL_ID_DIGIT_STAGES
    ):
        return (
            "الرقم القومي مش كامل. "
            "ممكن تعيده من الأول لو سمحت؟"
        )

    if normalized_stage == "awaiting_phone":
        return (
            "رقم التليفون مش كامل. "
            "ممكن تعيده من الأول لو سمحت؟"
        )

    return (
        "الرقم مش كامل. "
        "ممكن تعيده من الأول لو سمحت؟"
    )


def get_digit_max_audio_bytes(
    *,
    stage: str | None,
    sample_rate: int,
) -> int | None:
    """
    Return the maximum PCM16 bytes allowed
    for one Hamsa digit chunk.

    PCM16 mono:
        sample_rate * 2 bytes * seconds
    """

    if (
        get_expected_digit_count(
            stage
        )
        is None
    ):
        return None

    return int(
        sample_rate
        * 2
        * DIGIT_MAX_UTTERANCE_SECONDS
    )


# ============================================================
# Digit Normalization
# ============================================================


def _strip_diacritics(
    text: str,
) -> str:

    return "".join(
        character
        for character
        in unicodedata.normalize(
            "NFKD",
            text,
        )
        if not unicodedata.combining(
            character
        )
    )


_ARABIC_DIGIT_TRANSLATION = str.maketrans(
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

_SPOKEN_DIGIT_WORDS = {
    # Zero
    "صفر": "0",
    "زيرو": "0",
    "zero": "0",

    # One
    "واحد": "1",
    "واحده": "1",
    "واحدة": "1",
    "one": "1",

    # Two
    "اتنين": "2",
    "اثنين": "2",
    "اثنان": "2",
    "two": "2",

    # Three
    "تلاته": "3",
    "تلاتة": "3",
    "ثلاثه": "3",
    "ثلاثة": "3",
    "three": "3",

    # Four
    "اربعه": "4",
    "اربعة": "4",
    "أربعه": "4",
    "أربعة": "4",
    "four": "4",

    # Five
    "خمسه": "5",
    "خمسة": "5",
    "five": "5",

    # Six
    "سته": "6",
    "ستة": "6",
    "six": "6",

    # Seven
    "سبعه": "7",
    "سبعة": "7",
    "seven": "7",

    # Eight
    "تمانيه": "8",
    "تمانية": "8",
    "ثمانيه": "8",
    "ثمانية": "8",
    "eight": "8",

    # Nine
    "تسعه": "9",
    "تسعة": "9",
    "nine": "9",
}



def _split_compound_spoken_digit_token(
    token: str,
) -> list[str] | None:
    """
    Split a token containing multiple spoken digit words
    concatenated together.

    Examples:

        "خمسةستة"
            -> ["5", "6"]

        "واحداتنين"
            -> ["1", "2"]

        "صفرواحدصفر"
            -> ["0", "1", "0"]

    Safety:
    The token is accepted only if the ENTIRE token can be
    segmented into known spoken-digit words.

    Normal words that only partially contain a digit word
    are therefore ignored.
    """

    if not token:
        return None

    # Direct dictionary match first.
    direct = (
        _SPOKEN_DIGIT_WORDS.get(
            token
        )
    )

    if direct is not None:

        return [
            direct
        ]

    # Only compound Arabic digit words need this path.
    if not re.fullmatch(
        r"[\u0600-\u06ff]+",
        token,
    ):

        return None

    # Longer words first.
    #
    # Example:
    # "اتنين" should be checked before shorter candidates.
    digit_words = sorted(
        (
            word
            for word in _SPOKEN_DIGIT_WORDS
            if re.fullmatch(
                r"[\u0600-\u06ff]+",
                word,
            )
        ),
        key=len,
        reverse=True,
    )

    # Dynamic programming:
    #
    # dp[index] =
    #     list of digits that successfully covers
    #     token[:index]
    dp: dict[
        int,
        list[str],
    ] = {
        0: [],
    }

    for index in range(
        len(token)
    ):

        if index not in dp:
            continue

        for word in digit_words:

            if not token.startswith(
                word,
                index,
            ):
                continue

            end_index = (
                index
                + len(word)
            )

            digit = (
                _SPOKEN_DIGIT_WORDS[
                    word
                ]
            )

            if end_index not in dp:

                dp[end_index] = (
                    dp[index]
                    + [
                        digit
                    ]
                )

    return dp.get(
        len(token)
    )


def extract_spoken_digits(
    transcript: str,
) -> str:
    """
    Extract digits from mixed Hamsa output.

    Supports examples:

        1 2 3
        ١ ٢ ٣
        ۱ ۲ ۳
        واحد اتنين تلاتة
        one two three
        واحد 2 تلاتة
    """

    normalized = (
        _strip_diacritics(
            transcript
        )
        .replace(
            "ـ",
            "",
        )
        .replace(
            "أ",
            "ا",
        )
        .replace(
            "إ",
            "ا",
        )
        .replace(
            "آ",
            "ا",
        )
        .replace(
            "ٱ",
            "ا",
        )
        .translate(
            _ARABIC_DIGIT_TRANSLATION
        )
        .lower()
    )

    tokens = re.findall(
        r"[0-9]+"
        r"|[a-z]+"
        r"|[\u0600-\u06ff]+",
        normalized,
    )

    digits: list[str] = []

    for token in tokens:

        if token.isdigit():

            digits.append(
                token
            )

            continue

        mapped = (
            _SPOKEN_DIGIT_WORDS.get(
                token
            )
        )

        if mapped is not None:

            digits.append(
                mapped
            )

            continue


        compound_digits = (
            _split_compound_spoken_digit_token(
                token
            )
        )

        if compound_digits:

            digits.extend(
                compound_digits
            )

    return "".join(
        digits
    )


_DIGIT_IDENTITY_HINTS = {
    "رقم",
    "الرقم",
    "رقمي",
    "القومي",
    "موبايل",
    "الموبايل",
    "تليفون",
    "التليفون",
    "تلفون",
    "التلفون",
    "phone",
    "mobile",
    "id",
}


_DIGIT_FILLER_WORDS = {
    "هو",
    "هي",
    "اه",
    "ايوه",
    "أيوه",
    "تمام",
    "يعني",
    "بتاعي",
    "بتاعتي",
    "رقمي",
    "الرقم",
    "رقم",
    "القومي",
    "الموبايل",
    "موبايل",
    "التليفون",
    "تليفون",
    "التلفون",
    "تلفون",
}


def is_digit_entry_utterance(
    transcript: str,
) -> bool:

    text = transcript.strip()

    if not text:
        return False

    extracted_digits = (
        extract_spoken_digits(
            text
        )
    )

    if not extracted_digits:
        return False

    normalized = (
        _strip_diacritics(
            text
        )
        .replace("ـ", "")
        .replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ٱ", "ا")
        .translate(
            _ARABIC_DIGIT_TRANSLATION
        )
        .lower()
    )

    tokens = re.findall(
        r"[0-9]+"
        r"|[a-z]+"
        r"|[\u0600-\u06ff]+",
        normalized,
    )

    # Explicit identity / phone wording.
    if any(
        token in _DIGIT_IDENTITY_HINTS
        for token in tokens
    ):
        return True

    for token in tokens:

        if token in _DIGIT_FILLER_WORDS:
            continue

        if extract_spoken_digits(
            token
        ):
            continue

        # Real conversational word:
        # "مواعيد", "دكتور", "الخميس", ...
        return False

    return True

class DigitCollector:
    """
    Collect partial STT digit results for ONE
    logical digit attempt.

    A new attempt_id automatically clears
    any partial digits from the previous attempt.
    """

    def __init__(
        self,
    ) -> None:

        self.stage: (
            str
            | None
        ) = None

        self.attempt_id: (
            int
            | None
        ) = None

        self.buffer = ""

    def reset(
        self,
    ) -> None:

        self.stage = None
        self.attempt_id = None
        self.buffer = ""

    def consume(
        self,
        *,
        stage: str,
        attempt_id: int,
        transcript: str,
    ) -> tuple[
        str | None,
        int,
        int,
    ]:

        expected_digits = (
            get_expected_digit_count(
                stage
            )
        )

        if (
            expected_digits
            is None
        ):

            self.reset()

            return (
                transcript,
                0,
                0,
            )

        normalized_stage = (
            stage
            .strip()
            .lower()
        )

        # ====================================================
        # New logical attempt
        #
        # Never mix partial digits from an older attempt.
        # ====================================================

        if (
            self.stage
            != normalized_stage
            or self.attempt_id
            != attempt_id
        ):

            self.stage = (
                normalized_stage
            )

            self.attempt_id = (
                attempt_id
            )

            self.buffer = ""

        new_digits = (
            extract_spoken_digits(
                transcript
            )
        )

        if new_digits:

            self.buffer += (
                new_digits
            )

        collected_count = len(
            self.buffer
        )

        if (
            collected_count
            < expected_digits
        ):

            return (
                None,
                collected_count,
                expected_digits,
            )

        completed_value = (
            self.buffer
        )

        completed_count = len(
            completed_value
        )

        self.reset()

        return (
            completed_value,
            completed_count,
            expected_digits,
        )


# ============================================================
# STT Transcript Guard
# ============================================================


def is_valid_stt_transcript(
    transcript: str,
) -> bool:
    """
    Prevent Hamsa status/control messages
    from reaching the MedMind backend.
    """

    text = (
        transcript.strip()
    )

    if not text:

        return False

    blocked_messages = {
        "[THINKING]",
        "[PROCESSING]",
        "[TRANSCRIBING]",
        "[LISTENING]",
        "[DONE]",
        "[READY]",
    }

    if (
        text.upper()
        in blocked_messages
    ):

        return False

    if (
        text.startswith("[")
        and text.endswith("]")
    ):

        return False

    return True


# ============================================================
# TTS Provider Factory
# ============================================================


def create_tts_provider():

    provider_name = (
        os.getenv(
            "VOICE_TTS_PROVIDER",
            "hamsa",
        )
        .strip()
        .lower()
    )

    # ========================================================
    # ElevenLabs fallback
    # ========================================================

    if (
        provider_name
        == "elevenlabs"
    ):

        provider = (
            ElevenLabsTTS()
        )

    # ========================================================
    # Hamsa primary
    # ========================================================

    elif (
        provider_name
        == "hamsa"
    ):

        provider = (
            HamsaTTS()
        )

    # ========================================================
    # Unsupported
    # ========================================================

    else:

        raise RuntimeError(
            "Unsupported VOICE_TTS_PROVIDER: "
            f"{provider_name}"
        )

    logger.info(
        "voice_tts_provider_ready "
        "provider=%s",
        provider_name,
    )

    return (
        provider_name,
        provider,
    )

# ============================================================
# Transcript Consumer
#
# Final transcript
#     â†“
# MedMind backend
#     â†“
# Reply
#     â†“
# TTS
#     â†“
# Asterisk
# ============================================================

async def dispatch_post_call_event(
    *,
    conversation_state: dict[
        str,
        Any,
    ],
    tenant_id: str,
    channel_id: str,
    client: PostCallClient,
) -> bool:
    """
    Dispatch one armed post-call event.

    This must never make call teardown fail.
    """

    event_type = (
        conversation_state.get(
            POST_CALL_EVENT_KEY
        )
    )

    appointment_reference = (
        conversation_state.get(
            POST_CALL_APPOINTMENT_REFERENCE_KEY
        )
    )

    # --------------------------------------------------------
    # Nothing armed
    # --------------------------------------------------------

    if (
        event_type
        != POST_CALL_BOOKING_CONFIRMED
    ):
        return False

    if (
        not appointment_reference
    ):

        logger.error(
            "voice_post_call_missing_reference "
            "channel_id=%s",
            channel_id,
        )

        return False

    # --------------------------------------------------------
    # Remove first.
    #
    # This prevents a duplicate dispatch if teardown code
    # accidentally reaches this helper twice.
    # --------------------------------------------------------

    conversation_state.pop(
        POST_CALL_EVENT_KEY,
        None,
    )

    conversation_state.pop(
        POST_CALL_APPOINTMENT_REFERENCE_KEY,
        None,
    )

    try:

        await (
            client.send_booking_confirmation(
                tenant_id=
                    tenant_id,

                appointment_reference=
                    appointment_reference,
            )
        )

    except Exception:

        logger.exception(
            "voice_post_call_dispatch_failed "
            "channel_id=%s "
            "appointment_reference=%s",
            channel_id,
            appointment_reference,
        )

        # Notification failure must NOT convert an already
        # successful booking into a failed phone call.
        return False

    logger.info(
        "voice_post_call_dispatch_success "
        "channel_id=%s "
        "appointment_reference=%s",
        channel_id,
        appointment_reference,
    )

    return True

def capture_post_call_booking_event(
    *,
    result: dict,
    conversation_state: dict[
        str,
        Any,
    ],
    channel_id: str,
) -> bool:
    """
    Capture a successful booking for post-call processing.

    Important:
    - Do not store patient PII in the Voice Gateway.
    - Store only the trusted appointment reference.
    - WhatsApp details will be loaded later from the backend.
    """

    response_type = (
        result.get(
            "response_type"
        )
    )

    stage = (
        result.get(
            "stage"
        )
    )

    appointment_reference = (
        result.get(
            "appointment_reference"
        )
    )

    # Defensive fallback in case a future API exposes
    # workflow data directly.
    if (
        not appointment_reference
        and isinstance(
            result.get(
                "data"
            ),
            dict,
        )
    ):
        appointment_reference = (
            result[
                "data"
            ].get(
                "appointment_reference"
            )
        )

    # --------------------------------------------------------
    # Both signals must indicate successful booking.
    # --------------------------------------------------------

    if (
        str(
            response_type
            or ""
        ).strip()
        != "booking_created"
    ):
        return False

    if (
        str(
            stage
            or ""
        ).strip()
        .lower()
        != "booking_completed"
    ):
        return False

    if (
        not isinstance(
            appointment_reference,
            str,
        )
        or not appointment_reference.strip()
    ):

        logger.error(
            "voice_post_call_booking_missing_reference "
            "channel_id=%s",
            channel_id,
        )

        return False

    appointment_reference = (
        appointment_reference.strip()
    )

    # --------------------------------------------------------
    # Minimal state only.
    # No name, phone, national ID, etc.
    # --------------------------------------------------------

    conversation_state[
        POST_CALL_EVENT_KEY
    ] = (
        POST_CALL_BOOKING_CONFIRMED
    )

    conversation_state[
        POST_CALL_APPOINTMENT_REFERENCE_KEY
    ] = (
        appointment_reference
    )

    logger.info(
        "voice_post_call_booking_armed "
        "channel_id=%s "
        "appointment_reference=%s",
        channel_id,
        appointment_reference,
    )

    return True


async def consume_final_transcripts(
    transcript_queue: asyncio.Queue[
        str
    ],
    *,
    websocket: WebSocket,
    channel_id: str,
    tenant_id: str,
    audio_format: str,
    conversation_state: dict[
        str,
        Any,
    ],
    media_send_lock: asyncio.Lock,
) -> None:

    medmind = (
        MedMindClient()
    )

    medmind_warmup_task = (
        asyncio.create_task(
            medmind.warmup(
                tenant_id=tenant_id,
            ),
            name=(
                "medmind-warmup-"
                f"{channel_id}"
            ),
        )
    )

    (
        tts_provider_name,
        tts,
    ) = (
        create_tts_provider()
    )

    # ====================================================
    # TTS Background Warm-up
    #
    # Never block the caller pipeline waiting for TTS
    # provider warm-up.
    # ====================================================

    tts_warmup_task: (
        asyncio.Task[bool]
        | None
    ) = None

    tts_warmup_method = (
        getattr(
            tts,
            "warmup",
            None,
        )
    )

    if callable(
        tts_warmup_method
    ):

        tts_warmup_task = (
            asyncio.create_task(
                tts_warmup_method(),
                name=(
                    "tts-warmup-"
                    f"{channel_id}"
                ),
            )
        )

        logger.info(
            "voice_tts_warmup_started "
            "channel_id=%s "
            "provider=%s",
            channel_id,
            tts_provider_name,
        )

    tts_streaming_enabled = (
        os.getenv(
            "VOICE_TTS_STREAMING",
            "0",
        )
        .strip()
        == "1"
    )

    logger.info(
        "voice_tts_streaming_config "
        "channel_id=%s "
        "provider=%s "
        "enabled=%s "
        "audio_format=%s",
        channel_id,
        tts_provider_name,
        tts_streaming_enabled,
        audio_format,
    )

    # Server-issued, unpredictable MedMind session for this call.
    # Created on the first transcript (see below) and closed at call end.
    # The Asterisk channel id is never used as the session id.
    session_id: str | None = None

    try:

        while True:

            transcript = (
                await transcript_queue.get()
            )


            is_conversation_turn = (
                transcript.startswith(
                    CONVERSATION_TURN_PREFIX
                )
            )

            if is_conversation_turn:

                transcript = (
                    transcript[
                        len(
                            CONVERSATION_TURN_PREFIX
                        ):
                    ]
                    .strip()
                )

            try:

                is_local_prompt = (
                    transcript.startswith(
                        LOCAL_TTS_PREFIX
                    )
                )

                local_prompt_reply: (
                    str
                    | None
                ) = None

                if is_local_prompt:

                    local_prompt_reply = (
                        transcript[
                            len(LOCAL_TTS_PREFIX):
                        ]
                        .strip()
                    )

                current_stage = (
                    conversation_state.get(
                        "stage",
                        "new",
                    )
                )

                sensitive_digit_stage = (
                    get_expected_digit_count(
                        current_stage
                    )
                    is not None
                    and not is_conversation_turn
                )

                if is_local_prompt:

                    logger.info(
                        "voice_local_prompt_received "
                        "channel_id=%s "
                        "stage=%s",
                        channel_id,
                        current_stage,
                    )

                elif sensitive_digit_stage:

                    digit_count = len(
                        extract_spoken_digits(
                            transcript
                        )
                    )

                    # National ID / phone digits: log the count only.
                    logger.info(
                        "voice_final_transcript_received "
                        "channel_id=%s "
                        "stage=%s "
                        "transcript_chars=%d "
                        "digit_count=%d",
                        channel_id,
                        current_stage,
                        len(transcript),
                        digit_count,
                    )

                else:

                    # Caller speech may contain names or other
                    # patient details: never log the text itself.
                    logger.info(
                        "voice_final_transcript_received "
                        "channel_id=%s "
                        "stage=%s "
                        "transcript_chars=%d",
                        channel_id,
                        current_stage,
                        len(transcript),
                    )

                # ====================================================
                # MedMind
                # ====================================================

                if is_local_prompt:

                    if not local_prompt_reply:

                        logger.warning(
                            "voice_local_prompt_empty "
                            "channel_id=%s",
                            channel_id,
                        )

                        continue

                    result = {
                        "stage": current_stage,
                        "reply": local_prompt_reply,
                        "intent": "voice_local_prompt",
                        "language": "ar",
                    }

                else:

                    try:

                        if session_id is None:
                            session_id = (
                                await medmind.start_session(
                                    tenant_id=(
                                        tenant_id
                                    ),
                                )
                            )

                        result = (
                            await medmind.chat(
                                tenant_id=(
                                    tenant_id
                                ),
                                session_id=(
                                    session_id
                                ),
                                message=(
                                    transcript
                                ),
                                sensitive=(
                                    sensitive_digit_stage
                                ),
                            )
                        )

                    except Exception:

                        logger.error(
                            "voice_medmind_request_failed "
                            "channel_id=%s "
                            "%s "
                            "stage=%s "
                            "session=%s",
                            channel_id,
                            exception_fields(),
                            conversation_state.get("stage", "new"),
                            session_fingerprint(session_id),
                        )

                        continue

                # ====================================================
                # Update conversation stage
                # ====================================================

                result_stage = (
                    result.get(
                        "stage"
                    )
                )

                if (
                    isinstance(
                        result_stage,
                        str,
                    )
                    and result_stage.strip()
                ):

                    conversation_state[
                        "stage"
                    ] = (
                        result_stage
                        .strip()
                        .lower()
                    )

                    logger.info(
                        "voice_conversation_stage_updated "
                        "channel_id=%s "
                        "stage=%s",
                        channel_id,
                        conversation_state[
                            "stage"
                        ],
                    )   

                if not is_local_prompt:

                    capture_post_call_booking_event(
                        result=result,
                        conversation_state=
                            conversation_state,
                        channel_id=
                            channel_id,
                    )

                terminal_stage: (
                    str
                    | None
                ) = None

                if (
                    isinstance(
                        result_stage,
                        str,
                    )
                    and result_stage.strip().lower()
                    in TERMINAL_CALL_STAGES
                ):

                    terminal_stage = (
                        result_stage
                        .strip()
                        .lower()
                    )

                    logger.info(
                        "voice_terminal_stage_detected "
                        "channel_id=%s "
                        "stage=%s "
                        "action=wait_for_final_playback",
                        channel_id,
                        terminal_stage,
                    )

                # ====================================================
                # Reply
                # ====================================================

                reply = (
                    result.get(
                        "reply"
                    )
                )

                if is_local_prompt:

                    logger.info(
                        "voice_local_prompt_reply "
                        "channel_id=%s "
                        "stage=%s "
                        "reply_chars=%d",
                        channel_id,
                        result.get(
                            "stage"
                        ),
                        len(reply),
                    )

                else:

                    logger.info(
                        "voice_medmind_reply "
                        "channel_id=%s "
                        "intent=%s "
                        "stage=%s "
                        "language=%s "
                        "reply_chars=%d",
                        channel_id,
                        result.get(
                            "intent"
                        ),
                        result.get(
                            "stage"
                        ),
                        result.get(
                            "language"
                        ),
                       len(reply),
                    )

                if (
                    not isinstance(
                        reply,
                        str,
                    )
                    or not reply.strip()
                ):

                    logger.error(
                        "voice_medmind_empty_reply "
                        "channel_id=%s",
                        channel_id,
                    )

                    continue

                reply = (
                    reply.strip()
                )


                # ====================================================
                # Stale Reply Guard
                #
                # If the caller has already produced a newer turn while
                # we were processing this response, do not speak an old
                # reply over the newer conversation.
                # ====================================================

                if (
                    not is_local_prompt
                    and terminal_stage is None
                    and not transcript_queue.empty()
                ):

                    logger.info(
                        "voice_stale_reply_skipped "
                        "channel_id=%s "
                        "stage=%s "
                        "pending_transcripts=%d",
                        channel_id,
                        conversation_state.get(
                            "stage",
                            "new",
                        ),
                        transcript_queue.qsize(),
                    )

                    continue

                language = str(
                    result.get(
                        "language"
                    )
                    or "ar"
                )

                try:

                    tts_text = (
                        prepare_text_for_speech(
                            reply,
                            language=language,
                        )
                    )

                except Exception as exc:

                    logger.error(
                        "voice_tts_text_prepare_failed "
                        "channel_id=%s "
                        "language=%s "
                        "action=fallback_to_raw_reply "
                        "%s "
                        "stage=%s "
                        "session=%s",
                        channel_id,
                        language,
                        exception_fields(),
                        conversation_state.get("stage", "new"),
                        session_fingerprint(session_id),
                    )

                    tts_text = (
                        reply
                    )


                if (
                    not isinstance(
                        tts_text,
                        str,
                    )
                    or not tts_text.strip()
                ):

                    logger.warning(
                        "voice_tts_text_empty_after_formatting "
                        "channel_id=%s "
                        "action=fallback_to_raw_reply",
                        channel_id,
                    )

                    tts_text = (
                        reply
                    )


                tts_text = (
                    tts_text.strip()
                )


                logger.info(
                    "voice_tts_text_prepared "
                    "channel_id=%s "
                    "language=%s "
                    "original_chars=%d "
                    "spoken_chars=%d",
                    channel_id,
                    language,
                    len(
                        reply
                    ),
                    len(
                        tts_text
                    ),
                )
                # ====================================================
                # True Streaming TTS
                # ====================================================

                use_true_streaming = (
                    tts_provider_name
                    in {
                        "elevenlabs",
                        "hamsa",
                    }
                    and audio_format
                    == "slin24"
                    and tts_streaming_enabled
                )

                if use_true_streaming:

                    total_audio_bytes = (
                        0
                    )

                    audio_chunks = (
                        0
                    )

                    buffering_started = (
                        False
                    )

                    buffering_stopped = (
                        False
                    )

                    playback_started = (
                        False
                    )

                    stream_interrupted = (
                        False
                    )

                    # ========================================================
                    # Create correlation ID BEFORE playback starts.
                    #
                    # This lets the barge-in system know which playback
                    # it is interrupting while TTS is still streaming.
                    # ========================================================

                    stream_correlation_id = str(
                        uuid.uuid4()
                    )

                    stream_started_at = (
                        asyncio
                        .get_running_loop()
                        .time()
                    )

                    try:

                        logger.info(
                            "voice_tts_stream_started "
                            "channel_id=%s "
                            "provider=%s "
                            "format=%s "
                            "correlation_id=%s",
                            channel_id,
                            tts_provider_name,
                            audio_format,
                            stream_correlation_id,
                        )

                        # ====================================================
                        # Tell Asterisk a streaming/bulk transfer is starting.
                        # ====================================================

                        await start_media_buffering(
                            websocket,
                            send_lock=media_send_lock,
                        )

                        buffering_started = (
                            True
                        )

                        # ====================================================
                        # TTS stream
                        # ====================================================

                        async for (
                            audio_chunk
                        ) in (
                            tts.stream_pcm24k(
                                tts_text
                            )
                        ):

                            if (
                                not audio_chunk
                            ):

                                continue

                            # =================================================
                            # If playback already started, check whether
                            # barge-in flushed this stream.
                            #
                            # Barge-in clears:
                            #
                            #   PLAYBACK_ACTIVE_KEY
                            #   PLAYBACK_CORRELATION_KEY
                            #
                            # Once that happens we MUST NOT keep sending
                            # new TTS chunks after FLUSH_MEDIA.
                            # =================================================

                            if playback_started:

                                playback_still_active = (
                                    conversation_state.get(
                                        PLAYBACK_ACTIVE_KEY,
                                        False,
                                    )
                                )

                                active_correlation_id = str(
                                    conversation_state.get(
                                        PLAYBACK_CORRELATION_KEY,
                                        "",
                                    )
                                )

                                if (
                                    not playback_still_active
                                    or active_correlation_id
                                    != stream_correlation_id
                                ):

                                    stream_interrupted = (
                                        True
                                    )

                                    logger.info(
                                        "voice_tts_stream_interrupted "
                                        "channel_id=%s "
                                        "provider=%s "
                                        "correlation_id=%s "
                                        "chunks_sent=%d "
                                        "bytes_sent=%d "
                                        "reason=playback_flushed",
                                        channel_id,
                                        tts_provider_name,
                                        stream_correlation_id,
                                        audio_chunks,
                                        total_audio_bytes,
                                    )

                                    break

                            # =================================================
                            # First playable chunk.
                            #
                            # From this moment the agent is actually speaking,
                            # so enable playback tracking and barge-in.
                            # =================================================

                            if not playback_started:

                                playback_started = (
                                    True
                                )

                                conversation_state[
                                    PLAYBACK_ACTIVE_KEY
                                ] = True

                                conversation_state[
                                    PLAYBACK_CORRELATION_KEY
                                ] = (
                                    stream_correlation_id
                                )

                                conversation_state[
                                    PLAYBACK_STARTED_AT_KEY
                                ] = (
                                    asyncio
                                    .get_running_loop()
                                    .time()
                                )

                                logger.info(
                                    "voice_playback_started "
                                    "channel_id=%s "
                                    "stage=%s "
                                    "provider=%s "
                                    "mode=stream "
                                    "correlation_id=%s",
                                    channel_id,
                                    conversation_state.get(
                                        "stage",
                                        "new",
                                    ),
                                    tts_provider_name,
                                    stream_correlation_id,
                                )

                            # =================================================
                            # Send PCM24k chunk to Asterisk.
                            # =================================================

                            await send_media_chunk(
                                websocket,
                                audio_chunk,
                                send_lock=media_send_lock,
                            )

                            audio_chunks += (
                                1
                            )

                            total_audio_bytes += (
                                len(
                                    audio_chunk
                                )
                            )

                        if stream_interrupted:

                            logger.info(
                                "voice_tts_stream_closed_after_barge_in "
                                "channel_id=%s "
                                "provider=%s "
                                "correlation_id=%s",
                                channel_id,
                                tts_provider_name,
                                stream_correlation_id,
                            )

                            continue

                        # ====================================================
                        # Normal streaming completion
                        # ====================================================

                        correlation_id = (
                            await stop_media_buffering(
                                websocket,
                                correlation_id=stream_correlation_id,
                                send_lock=media_send_lock,
                            )
                        )

                        buffering_stopped = (
                            True
                        )

                        elapsed_ms = (
                            (
                                asyncio
                                .get_running_loop()
                                .time()
                                - stream_started_at
                            )
                            * 1000
                        )

                        logger.info(
                            "voice_tts_stream_sent "
                            "channel_id=%s "
                            "provider=%s "
                            "format=%s "
                            "chunks=%d "
                            "bytes=%d "
                            "elapsed_ms=%.2f "
                            "correlation_id=%s",
                            channel_id,
                            tts_provider_name,
                            audio_format,
                            audio_chunks,
                            total_audio_bytes,
                            elapsed_ms,
                            correlation_id,
                        )

                        # ====================================================
                        # Terminal playback
                        #
                        # Wait for MEDIA_BUFFERING_COMPLETED before hanging up.
                        # ====================================================

                        if (
                            terminal_stage
                            is not None
                            and not is_local_prompt
                        ):

                            conversation_state[
                                PENDING_HANGUP_CORRELATION_KEY
                            ] = str(
                                correlation_id
                            )

                            conversation_state[
                                PENDING_HANGUP_STAGE_KEY
                            ] = (
                                terminal_stage
                            )

                            logger.info(
                                "voice_terminal_hangup_armed "
                                "channel_id=%s "
                                "stage=%s "
                                "correlation_id=%s",
                                channel_id,
                                terminal_stage,
                                correlation_id,
                            )

                    except Exception as exc:

                        logger.error(
                            "voice_tts_stream_failed "
                            "channel_id=%s "
                            "provider=%s "
                            "%s "
                            "stage=%s "
                            "session=%s",
                            channel_id,
                            tts_provider_name,
                            exception_fields(),
                            conversation_state.get("stage", "new"),
                            session_fingerprint(session_id),
                        )

                        # ====================================================
                        # Cleanup
                        #
                        # If barge-in already flushed this playback, do NOT
                        # send STOP_MEDIA_BUFFERING afterwards.
                        #
                        # But if streaming failed normally, close buffering.
                        # ====================================================

                        playback_still_owned = (
                            conversation_state.get(
                                PLAYBACK_ACTIVE_KEY,
                                False,
                            )
                            and str(
                                conversation_state.get(
                                    PLAYBACK_CORRELATION_KEY,
                                    "",
                                )
                            )
                            == stream_correlation_id
                        )

                        should_stop_buffering = (
                            buffering_started
                            and not buffering_stopped
                            and (
                                not playback_started
                                or playback_still_owned
                            )
                        )

                        if should_stop_buffering:

                            try:

                                await stop_media_buffering(
                                    websocket,
                                    correlation_id=stream_correlation_id,
                                    send_lock=media_send_lock,
                                )

                                buffering_stopped = (
                                    True
                                )

                            except Exception:

                                logger.error(
                                    "voice_tts_stream_"
                                    "buffer_stop_failed "
                                    "channel_id=%s "
                                    "provider=%s "
                                    "%s "
                                    "stage=%s "
                                    "session=%s",
                                    channel_id,
                                    tts_provider_name,
                                    exception_fields(),
                                    conversation_state.get("stage", "new"),
                                    session_fingerprint(session_id),
                                )

                        continue

                    continue

                # ====================================================
                # Non-streaming TTS
                # ====================================================

                try:

                    if (
                        audio_format
                        == "slin24"
                    ):

                        outbound_audio = (
                            await asyncio.to_thread(
                                tts.synthesize_pcm24k,
                                tts_text,
                            )
                        )

                    elif (
                        audio_format
                        == "ulaw"
                    ):

                        if (
                            tts_provider_name
                            == "elevenlabs"
                        ):

                            pcm24k = (
                                await asyncio.to_thread(
                                    tts.synthesize_pcm24k,
                                    tts_text,
                                )
                            )

                            outbound_audio = (
                                pcm16_24k_to_ulaw8k(
                                    pcm24k
                                )
                            )

                        else:

                            outbound_audio = (
                                await asyncio.to_thread(
                                    tts.synthesize_ulaw,
                                    tts_text,
                                )
                            )

                    else:

                        raise RuntimeError(
                            "Unsupported outbound "
                            "audio format: "
                            f"{audio_format}"
                        )

                except Exception as exc:

                    logger.error(
                        "voice_tts_failed "
                        "channel_id=%s "
                        "provider=%s "
                        "%s "
                        "stage=%s "
                        "session=%s",
                        channel_id,
                        tts_provider_name,
                        exception_fields(),
                        conversation_state.get("stage", "new"),
                        session_fingerprint(session_id),
                    )

                    continue

                # ====================================================
                # Re-check for a newer caller turn.
                #
                # The caller may have spoken while ElevenLabs was
                # synthesizing this response.
                # ====================================================

                if (
                    not is_local_prompt
                    and terminal_stage is None
                    and not transcript_queue.empty()
                ):

                    logger.info(
                        "voice_stale_tts_discarded "
                        "channel_id=%s "
                        "stage=%s "
                        "pending_transcripts=%d "
                        "audio_bytes=%d",
                        channel_id,
                        conversation_state.get(
                            "stage",
                            "new",
                        ),
                        transcript_queue.qsize(),
                        len(
                            outbound_audio
                        ),
                    )

                    continue    
                # ====================================================
                # Send Audio
                # ====================================================

                try:

                    correlation_id = (
                        await send_media_audio(
                            websocket,
                            outbound_audio,
                            send_lock=media_send_lock,
                        )
                    )

                except Exception as exc:

                    logger.error(
                        "voice_audio_send_failed "
                        "channel_id=%s "
                        "provider=%s "
                        "%s "
                        "stage=%s "
                        "session=%s",
                        channel_id,
                        tts_provider_name,
                        exception_fields(),
                        conversation_state.get("stage", "new"),
                        session_fingerprint(session_id),
                    )

                    continue

                conversation_state[
                    PLAYBACK_ACTIVE_KEY
                ] = True

                conversation_state[
                    PLAYBACK_CORRELATION_KEY
                ] = str(
                    correlation_id
                )

                conversation_state[
                    PLAYBACK_STARTED_AT_KEY
                ] = (
                    asyncio
                    .get_running_loop()
                    .time()
                )

                logger.info(
                    "voice_tts_sent "
                    "channel_id=%s "
                    "provider=%s "
                    "mode=non_stream "
                    "format=%s "
                    "bytes=%d "
                    "correlation_id=%s",
                    channel_id,
                    tts_provider_name,
                    audio_format,
                    len(
                        outbound_audio
                    ),
                    correlation_id,
                )

                logger.info(
                    "voice_playback_started "
                    "channel_id=%s "
                    "stage=%s "
                    "correlation_id=%s",
                    channel_id,
                    conversation_state.get(
                        "stage",
                        "new",
                    ),
                    correlation_id,
                )

                if (
                    terminal_stage
                    is not None
                    and not is_local_prompt
                ):

                    conversation_state[
                        PENDING_HANGUP_CORRELATION_KEY
                    ] = str(
                        correlation_id
                    )

                    conversation_state[
                        PENDING_HANGUP_STAGE_KEY
                    ] = terminal_stage

                    logger.info(
                        "voice_terminal_hangup_armed "
                        "channel_id=%s "
                        "stage=%s "
                        "correlation_id=%s",
                        channel_id,
                        terminal_stage,
                        correlation_id,
                    )

            finally:

                transcript_queue.task_done()

    finally:

        # ====================================================
        # Stop MedMind warm-up task
        # ====================================================

        if not medmind_warmup_task.done():

            medmind_warmup_task.cancel()

        try:

            await medmind_warmup_task

        except asyncio.CancelledError:

            pass

        except Exception:

            logger.error(
                "medmind_warmup_task_shutdown_error "
                "channel_id=%s "
                "%s "
                "stage=%s "
                "session=%s",
                channel_id,
                exception_fields(),
                conversation_state.get("stage", "new"),
                session_fingerprint(session_id),
            )

        # ====================================================
        # Close MedMind
        # ====================================================

        if session_id is not None:
            # Best effort; never raises.
            await medmind.end_session(
                tenant_id=tenant_id,
                session_id=session_id,
            )

        try:

            await medmind.close()

        except Exception:

            logger.error(
                "medmind_client_shutdown_error "
                "%s "
                "stage=%s "
                "session=%s",
                exception_fields(),
                conversation_state.get("stage", "new"),
                session_fingerprint(session_id)
            )

        # ====================================================
        # Stop / collect TTS warm-up task
        # ====================================================

        if (
            tts_warmup_task is not None
        ):

            if not tts_warmup_task.done():

                tts_warmup_task.cancel()

            try:

                await tts_warmup_task

            except asyncio.CancelledError:

                pass

            except Exception:

                logger.error(
                    "voice_tts_warmup_task_shutdown_error "
                    "channel_id=%s "
                    "provider=%s "
                    "%s "
                    "stage=%s "
                    "session=%s",
                    channel_id,
                    tts_provider_name,
                    exception_fields(),
                    conversation_state.get("stage", "new"),
                    session_fingerprint(session_id),
                )

        # ====================================================
        # Async TTS close
        # ====================================================

        aclose_method = (
            getattr(
                tts,
                "aclose",
                None,
            )
        )

        if (
            callable(
                aclose_method
            )
        ):

            try:

                await (
                    aclose_method()
                )

            except Exception:

                logger.error(
                    "voice_tts_async_provider_"
                    "shutdown_error "
                    "provider=%s "
                    "%s "
                    "stage=%s "
                    "session=%s",
                    tts_provider_name,
                    exception_fields(),
                    conversation_state.get("stage", "new"),
                    session_fingerprint(session_id),
                )

        # ====================================================
        # Sync TTS close
        # ====================================================

        close_method = (
            getattr(
                tts,
                "close",
                None,
            )
        )

        if (
            callable(
                close_method
            )
        ):

            try:

                await asyncio.to_thread(
                    close_method
                )

            except Exception:

                logger.error(
                    "voice_tts_provider_"
                    "shutdown_error "
                    "provider=%s "
                    "%s "
                    "stage=%s "
                    "session=%s",
                    tts_provider_name,
                    exception_fields(),
                    conversation_state.get("stage", "new"),
                    session_fingerprint(session_id),
                )


# ============================================================
# Health
# ============================================================


@app.get(
    "/health"
)
async def health() -> dict[
    str,
    str,
]:

    return {
        "status": "ok",
        "service":
            "medmind-voice-gateway",
    }


# ============================================================
# Asterisk Media WebSocket
# ============================================================


@app.websocket(
    "/asterisk/media"
)
async def asterisk_media(
    websocket: WebSocket,
) -> None:

    await websocket.accept(
        subprotocol="media"
    )

    event_loop = (
        asyncio.get_running_loop()
    )

    client = (
        websocket.client
    )

    # Nothing from this connection is trusted until MEDIA_START carries a
    # valid shared secret and an allowed tenant (voice_gateway/media_auth.py).
    media_authorization: (
        MediaAuthorization
        | None
    ) = None

    media_auth_deadline = (
        event_loop.time()
        + auth_timeout_seconds()
    )

    media_send_lock = (
        asyncio.Lock()
    )

    # ========================================================
    # Session / VAD
    # ========================================================

    session: (
        VoiceSession
        | None
    ) = None

    call_tenant_id: str | None = None

    vad: (
        StreamingVAD
        | None
    ) = None
    slin24_vad_resampler = None

    stt: (
        DeepgramStreamingSTT
        | None
    ) = None

    hamsa_primary: (
        HamsaSTT
        | None
    ) = None

    # ========================================================
    # Hamsa Capture State
    # ========================================================

    hamsa_preroll = (
        bytearray()
    )

    hamsa_utterance_audio = (
        bytearray()
    )

    hamsa_utterance_active = (
        False
    )

    hamsa_turn_number = (
        0
    )

    # ========================================================
    # MedMind Transcript Queue
    # ========================================================

    transcript_queue: (
        asyncio.Queue[
            str
        ]
        | None
    ) = None

    transcript_consumer_task: (
        asyncio.Task[
            None
        ]
        | None
    ) = None

    hamsa_work_queue: (
        asyncio.Queue[
            tuple[
                int,
                bytes,
                str,
                str,
                int,
            ]
        ]
        | None
    ) = None

    hamsa_worker_task: (
        asyncio.Task[
            None
        ]
        | None
    ) = None

    # ========================================================
    # Turn Grace
    # ========================================================

    pending_turn_finalize_task: (
        asyncio.Task[
            None
        ]
        | None
    ) = None

    # ========================================================
    # Deepgram Lifecycle
    # ========================================================

    deepgram_shadow_ready = (
        False
    )

    deepgram_audio_lock = (
        asyncio.Lock()
    )

    deepgram_startup_audio_buffer = (
        bytearray()
    )

    pending_deepgram_finalize_owner: (
        tuple[int, str, int]
        | None
    ) = None

    pending_deepgram_utterance_start = False

    deepgram_start_task: (
        asyncio.Task[
            None
        ]
        | None
    ) = None

    hamsa_preconnect_task: (
        asyncio.Task[
            None
        ]
        | None
    ) = None

    deepgram_finalize_tasks: set[
        asyncio.Task[
            None
        ]
    ] = set()

    hamsa_drain_tasks: set[
        asyncio.Task
    ] = set()

    active_hamsa_digit_task: (
        asyncio.Task[str]
        | None
    ) = None

    active_hamsa_digit_owner: (
        tuple[str, int]
        | None
    ) = None
    
    # ========================================================
    # Conversation State
    # ========================================================

    conversation_state: dict[
        str,
        Any,
    ] = {
        "stage": "new",
    }

    # ========================================================
    # Digit Collector
    # ========================================================

    digit_collector = (
        DigitCollector()
    )


    # ========================================================
    # Digit Attempt / Arbitration State
    # ========================================================

    digit_attempt_id = 0

    # Stage that owns the currently open digit attempt.
    # A short VAD pause does NOT create a new attempt.
    digit_attempt_stage: (
        str
        | None
    ) = None

    # Set when the current Hamsa digit accumulation is known
    # to be invalid (for example 15/14). The next caller
    # speech starts a fresh attempt.
    digit_attempt_force_restart = False

    # Attempts invalidated by the incomplete-number watchdog.
    # In-flight results from them must be ignored.
    invalid_digit_attempts: set[
        tuple[
            str,
            int,
        ]
    ] = set()

    pending_digit_retry_task: (
        asyncio.Task[
            None
        ]
        | None
    ) = None

    barge_in_guard_task: (
        asyncio.Task | None
    ) = None

    barge_in_speech_active = False

    fast_barge_in_active_frames = 0

    digit_completed_attempt: (
        tuple[
            str,
            int,
        ]
        | None
    ) = None

    digit_completion_lock = (
        asyncio.Lock()
    )

    # ========================================================
    # Normal Conversation Deepgram Fallback
    # ========================================================

    deepgram_normal_candidates: dict[
        int,
        str,
    ] = {}

    deepgram_normal_candidate_events: dict[
        int,
        asyncio.Event,
    ] = {}

    closed_normal_turns: set[
        int
    ] = set()
    logger.info(
        "asterisk_websocket_connected "
        "client=%s",
        client,
    )

    # ========================================================
    # Cancel pending SILENCE GRACE only
    # ========================================================

    async def cancel_pending_turn_finalize() -> None:

        nonlocal pending_turn_finalize_task


        task = (
            pending_turn_finalize_task
        )

        if (
            task is None
        ):

            return

        if (
            not task.done()
        ):

            task.cancel()

            try:

                await task

            except asyncio.CancelledError:

                pass

        if (
            pending_turn_finalize_task
            is task
        ):

            pending_turn_finalize_task = (
                None
            )

    # ========================================================
    # Deepgram Background Startup
    # ========================================================

    async def start_deepgram_shadow(
        shadow_stt: DeepgramStreamingSTT,
        *,
        channel_id: str,
        connection_id: str,
        language: str,
        encoding: str,
        sample_rate: int,
    ) -> None:

        nonlocal deepgram_shadow_ready
        nonlocal pending_deepgram_finalize_owner
        nonlocal pending_deepgram_utterance_start

        try:

            logger.info(
                "deepgram_shadow_starting "
                "channel_id=%s",
                channel_id,
            )

            await (
                shadow_stt.start()
            )

            pending_finalize_owner: (
                tuple[int, str, int]
                | None
            ) = None

            # ====================================================
            # Flush audio received while Deepgram was connecting.
            #
            # Hold one lock so live audio cannot overtake the
            # buffered startup audio.
            # ====================================================

            async with deepgram_audio_lock:

                if pending_deepgram_utterance_start:

                    shadow_stt.begin_utterance()

                    pending_deepgram_utterance_start = False

                    logger.info(
                        "deepgram_deferred_utterance_started "
                        "channel_id=%s",
                        channel_id,
                    )

                if deepgram_startup_audio_buffer:

                    buffered_audio = bytes(
                        deepgram_startup_audio_buffer
                    )

                    deepgram_startup_audio_buffer.clear()

                    await shadow_stt.send_audio(
                        buffered_audio
                    )

                    logger.info(
                        "deepgram_startup_audio_flushed "
                        "channel_id=%s "
                        "bytes=%d",
                        channel_id,
                        len(buffered_audio),
                    )

                # Only expose provider as ready AFTER old audio
                # has been delivered in the correct order.
                deepgram_shadow_ready = True

                pending_finalize_owner = (
                    pending_deepgram_finalize_owner
                )

                pending_deepgram_finalize_owner = None


                logger.info(
                    "deepgram_shadow_ready "
                    "connection_id=%s "
                    "model=nova-3 "
                    "language=%s "
                    "encoding=%s "
                    "sample_rate=%d",
                    connection_id,
                    language,
                    encoding,
                    sample_rate,
                )


                # ====================================================
                # VAD may already have detected speech-end while
                # Deepgram was connecting.
                # Finalize that turn now that its buffered audio
                # has reached Deepgram.
                # ====================================================

                if pending_finalize_owner is not None:

                    schedule_deepgram_finalize(
                        channel_id,
                        owner=pending_finalize_owner,
                    )

                    logger.info(
                        "deepgram_deferred_finalize_resumed "
                        "channel_id=%s "
                        "turn=%d "
                        "stage=%s "
                        "attempt_id=%d",
                        channel_id,
                        pending_finalize_owner[0],
                        pending_finalize_owner[1],
                        pending_finalize_owner[2],
                    )
        except asyncio.CancelledError:

            logger.info(
                "deepgram_shadow_start_cancelled "
                "channel_id=%s",
                channel_id,
            )

            raise

        except Exception:

            deepgram_shadow_ready = (
                False
            )

            logger.error(
                "deepgram_shadow_start_failed "
                "channel_id=%s "
                "%s "
                "stage=%s",
                channel_id,
                exception_fields(),
                conversation_state.get("stage", "new"),
            )

    # ========================================================
    # Hamsa Background Preconnect
    # ========================================================

    async def start_hamsa_primary(
        primary_stt: HamsaSTT,
        *,
        channel_id: str,
    ) -> None:
        """
        Preconnect Hamsa without blocking the voice pipeline.

        Failure is non-fatal:
        transcribe() can attempt lazy reconnect later,
        while Deepgram remains available as fallback.
        """

        try:

            logger.info(
                "hamsa_primary_preconnect_starting "
                "channel_id=%s",
                channel_id,
            )

            await (
                primary_stt.start()
            )

            logger.info(
                "hamsa_primary_ready "
                "channel_id=%s "
                "model=s3 "
                "sample_rate=24000 "
                "mode=persistent",
                channel_id,
            )

        except asyncio.CancelledError:

            logger.info(
                "hamsa_primary_preconnect_cancelled "
                "channel_id=%s",
                channel_id,
            )

            raise

        except Exception as exc:

            logger.warning(
                "hamsa_primary_preconnect_failed "
                "channel_id=%s "
                "error_type=%s "
                "action=continue_with_lazy_reconnect_and_deepgram_fallback",
                channel_id,
                type(
                    exc
                ).__name__,
            )
    # ========================================================
    # Deepgram Finalize
    # ========================================================

    async def finalize_deepgram_shadow_turn(
        channel_id: str,
        *,
        owner: tuple[int, str, int],
    ) -> None:

        if (
            stt is None
            or not deepgram_shadow_ready
        ):

            return

        try:

            await (
                stt.finalize(
                    owner=owner,
                )
            )

        except asyncio.CancelledError:

            raise

        except Exception:

            logger.error(
                "deepgram_shadow_finalize_failed "
                "channel_id=%s "
                "%s "
                "stage=%s",
                channel_id,
                exception_fields(),
                conversation_state.get("stage", "new"),
            )

    def schedule_deepgram_finalize(
        channel_id: str,
        *,
        owner: tuple[int, str, int],
    ) -> None:

        nonlocal pending_deepgram_finalize_owner

        if stt is None:
            return

        # ====================================================
        # The caller may finish speaking before the first
        # Deepgram WebSocket handshake has completed.
        #
        # Do not lose the finalize request.
        # ====================================================

        if not deepgram_shadow_ready:

            pending_deepgram_finalize_owner = (
                owner
            )

            logger.info(
                "deepgram_finalize_deferred_until_ready "
                "channel_id=%s "
                "turn=%d "
                "stage=%s "
                "attempt_id=%d",
                channel_id,
                owner[0],
                owner[1],
                owner[2],
            )

            return

        task = (
            asyncio.create_task(
                finalize_deepgram_shadow_turn(
                    channel_id,
                    owner=owner,
                ),
                name=(
                    "deepgram-shadow-finalize-"
                    f"{channel_id}"
                ),
            )
        )

        deepgram_finalize_tasks.add(
            task
        )

        task.add_done_callback(
            deepgram_finalize_tasks.discard
        )

    async def send_or_buffer_deepgram_audio(
        audio: bytes,
    ) -> None:

        if (
            stt is None
            or session is None
            or not audio
        ):
            return

        async with deepgram_audio_lock:

            # ====================================================
            # Deepgram connection still opening.
            #
            # Preserve the caller's first words instead of
            # silently dropping them.
            # ====================================================

            if not deepgram_shadow_ready:

                deepgram_startup_audio_buffer.extend(
                    audio
                )

                bytes_per_sample = (
                    1
                    if session.audio_format == "ulaw"
                    else 2
                )

                max_buffer_bytes = int(
                    session.sample_rate
                    * bytes_per_sample
                    * DEEPGRAM_STARTUP_BUFFER_SECONDS
                )

                # Bounded memory.
                if (
                    len(deepgram_startup_audio_buffer)
                    > max_buffer_bytes
                ):

                    overflow = (
                        len(
                            deepgram_startup_audio_buffer
                        )
                        - max_buffer_bytes
                    )

                    del deepgram_startup_audio_buffer[
                        :overflow
                    ]

                return

            # Normal live streaming after startup.
            await stt.send_audio(
                audio
            )    

    def track_hamsa_drain_task(
        task: asyncio.Task,
        *,
        turn_number: int,
    ) -> None:

        hamsa_drain_tasks.add(
            task
        )

        def on_done(
            completed_task: asyncio.Task,
        ) -> None:

            hamsa_drain_tasks.discard(
                completed_task
            )

            if completed_task.cancelled():
                return

            try:

                result = (
                    completed_task.result()
                )

            except Exception:

                logger.error(
                    "hamsa_drain_failed "
                    "channel_id=%s "
                    "turn=%d "
                    "%s "
                    "stage=%s",
                    (
                        session.channel_id
                        if session is not None
                        else "unknown"
                    ),
                    turn_number,
                    exception_fields(),
                    conversation_state.get("stage", "new"),
                )

                return

            logger.info(
                "hamsa_drain_completed "
                "channel_id=%s "
                "turn=%d "
                "transcript_received=%s",
                (
                    session.channel_id
                    if session is not None
                    else "unknown"
                ),
                turn_number,
                bool(
                    str(
                        result or ""
                    ).strip()
                ),
            )

        task.add_done_callback(
            on_done
        )

    # ========================================================
    # That old chunk must NOT restart DigitCollector.
    # ========================================================

    def discard_pending_digit_turns(
        completed_stage: str,
        completed_attempt_id: int,
    ) -> int:

        if hamsa_work_queue is None:

            return 0

        normalized_stage = (
            completed_stage
            .strip()
            .lower()
        )

        kept_items: list[
            tuple[
                int,
                bytes,
                str,
                str,
                int,
            ]
        ] = []

        dropped = 0

        while True:

            try:

                item = (
                    hamsa_work_queue
                    .get_nowait()
                )

            except asyncio.QueueEmpty:

                break

            (
                queued_turn,
                queued_audio,
                queued_stage,
                queued_reason,
                queued_attempt_id,
            ) = item

            # Balance Queue unfinished task accounting.
            hamsa_work_queue.task_done()

            same_attempt = (
                queued_stage
                .strip()
                .lower()
                == normalized_stage
                and queued_attempt_id
                == completed_attempt_id
            )

            if same_attempt:

                dropped += 1

                logger.info(
                    "hamsa_stale_digit_turn_dropped "
                    "channel_id=%s "
                    "turn=%d "
                    "stage=%s "
                    "attempt_id=%d "
                    "reason=%s "
                    "audio_bytes=%d",
                    (
                        session.channel_id
                        if session is not None
                        else "unknown"
                    ),
                    queued_turn,
                    queued_stage,
                    queued_attempt_id,
                    queued_reason,
                    len(
                        queued_audio
                    ),
                )

                continue

            kept_items.append(
                item
            )

        for item in kept_items:

            hamsa_work_queue.put_nowait(
                item
            )

        return (
            dropped
        )

    def is_current_digit_attempt(
        stage: str,
        attempt_id: int,
    ) -> bool:

        normalized_stage = (
            stage
            .strip()
            .lower()
        )

        current_stage = (
            conversation_state.get(
                "stage",
                "new",
            )
            .strip()
            .lower()
        )

        return (
            current_stage
            == normalized_stage
            and digit_attempt_id
            == attempt_id
            and (
                normalized_stage,
                attempt_id,
            ) not in invalid_digit_attempts
        )


    def is_digit_attempt_completed(
        stage: str,
        attempt_id: int,
    ) -> bool:

        normalized_stage = (
            stage
            .strip()
            .lower()
        )

        return (
            digit_completed_attempt
            == (
                normalized_stage,
                attempt_id,
            )
        )


    async def cancel_pending_digit_retry_prompt(
        *,
        reason: str,
    ) -> None:

        nonlocal pending_digit_retry_task

        task = pending_digit_retry_task

        if task is None:
            return

        if not task.done():

            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass

            logger.info(
                "voice_digit_retry_timer_cancelled "
                "channel_id=%s "
                "reason=%s",
                (
                    session.channel_id
                    if session is not None
                    else "unknown"
                ),
                reason,
            )

        if pending_digit_retry_task is task:
            pending_digit_retry_task = None


    async def prompt_for_incomplete_digit_after_delay(
        *,
        stage: str,
        attempt_id: int,
    ) -> None:
        """
        After a real digit-turn silence, wait briefly. If the
        caller does not resume and neither STT provider produced
        an exact-length number, invalidate the partial attempt
        and ask for a full retry.
        """

        nonlocal pending_digit_retry_task
        nonlocal digit_attempt_force_restart

        normalized_stage = (
            stage
            .strip()
            .lower()
        )

        try:

            await asyncio.sleep(
                DIGIT_INCOMPLETE_RETRY_SECONDS
            )

            if not is_current_digit_attempt(
                normalized_stage,
                attempt_id,
            ):
                return

            if is_digit_attempt_completed(
                normalized_stage,
                attempt_id,
            ):
                return

            # Mark this attempt stale before prompting. This also
            # protects us from a late Hamsa response after timeout.
            invalid_digit_attempts.add(
                (
                    normalized_stage,
                    attempt_id,
                )
            )

            digit_attempt_force_restart = True
            digit_collector.reset()

            dropped_turns = (
                discard_pending_digit_turns(
                    normalized_stage,
                    attempt_id,
                )
            )

            prompt = (
                get_incomplete_digit_prompt(
                    normalized_stage
                )
            )

            if transcript_queue is not None:

                transcript_queue.put_nowait(
                    LOCAL_TTS_PREFIX
                    + prompt
                )

            logger.warning(
                "voice_digit_incomplete_retry_requested "
                "channel_id=%s "
                "stage=%s "
                "attempt_id=%d "
                "retry_after_seconds=%.2f "
                "stale_turns_dropped=%d",
                (
                    session.channel_id
                    if session is not None
                    else "unknown"
                ),
                normalized_stage,
                attempt_id,
                DIGIT_INCOMPLETE_RETRY_SECONDS,
                dropped_turns,
            )

        except asyncio.CancelledError:
            raise

        finally:

            current_task = asyncio.current_task()

            if pending_digit_retry_task is current_task:
                pending_digit_retry_task = None


    def schedule_digit_incomplete_retry(
        *,
        stage: str,
        attempt_id: int,
    ) -> None:

        nonlocal pending_digit_retry_task

        normalized_stage = (
            stage
            .strip()
            .lower()
        )

        if (
            get_expected_digit_count(
                normalized_stage
            )
            is None
        ):
            return

        old_task = pending_digit_retry_task

        if (
            old_task is not None
            and not old_task.done()
        ):
            old_task.cancel()

        pending_digit_retry_task = (
            asyncio.create_task(
                prompt_for_incomplete_digit_after_delay(
                    stage=normalized_stage,
                    attempt_id=attempt_id,
                ),
                name=(
                    "voice-digit-incomplete-retry-"
                    f"{attempt_id}"
                ),
            )
        )

        logger.info(
            "voice_digit_retry_timer_started "
            "channel_id=%s "
            "stage=%s "
            "attempt_id=%d "
            "timeout_seconds=%.2f",
            (
                session.channel_id
                if session is not None
                else "unknown"
            ),
            normalized_stage,
            attempt_id,
            DIGIT_INCOMPLETE_RETRY_SECONDS,
        )

    async def route_digit_stage_conversation(
        *,
        provider: str,
        transcript: str,
        stage: str,
        attempt_id: int,
        turn_number: int | None = None,
    ) -> bool:

        nonlocal digit_attempt_force_restart

        normalized_stage = (
            stage
            .strip()
            .lower()
        )

        # Another provider may already have resolved
        # this digit attempt.
        if not is_current_digit_attempt(
            normalized_stage,
            attempt_id,
        ):
            return False

        # This attempt is NOT a digit attempt anymore.
        invalid_digit_attempts.add(
            (
                normalized_stage,
                attempt_id,
            )
        )

        digit_attempt_force_restart = True

        digit_collector.reset()

        await cancel_pending_digit_retry_prompt(
            reason=(
                f"{provider}_"
                "conversational_interrupt"
            )
        )

        dropped_turns = (
            discard_pending_digit_turns(
                normalized_stage,
                attempt_id,
            )
        )

        if transcript_queue is None:

            logger.error(
                "voice_conversation_route_queue_missing "
                "channel_id=%s",
                (
                    session.channel_id
                    if session is not None
                    else "unknown"
                ),
            )

            return False

        # IMPORTANT:
        # Mark this explicitly as a normal conversation.
        transcript_queue.put_nowait(
            CONVERSATION_TURN_PREFIX
            + transcript
        )

        logger.info(
            "voice_digit_stage_conversation_routed "
            "channel_id=%s "
            "provider=%s "
            "turn=%s "
            "stage=%s "
            "attempt_id=%d "
            "stale_turns_dropped=%d",
            (
                session.channel_id
                if session is not None
                else "unknown"
            ),
            provider,
            turn_number,
            normalized_stage,
            attempt_id,
            dropped_turns,
        )

        return True    


    async def complete_digit_attempt(
        *,
        provider: str,
        stage: str,
        attempt_id: int,
        digits: str,
        turn_number: int | None = None,
    ) -> bool:
        """
        First exact STT result wins.

        Hamsa and Deepgram may both produce candidates.

        Only:
            14 digits for national ID
            11 digits for phone

        are accepted.
        """

        nonlocal digit_completed_attempt
        nonlocal digit_attempt_force_restart

        normalized_stage = (
            stage
            .strip()
            .lower()
        )

        

        expected_digits = (
            get_expected_digit_count(
                normalized_stage
            )
        )

        if (
            expected_digits
            is None
        ):

            return False

        if (
            len(
                digits
            )
            != expected_digits
        ):

            return False

        if not is_valid_digit_candidate_for_stage(
            stage=normalized_stage,
            digits=digits,
        ):

            logger.info(
                "voice_digit_candidate_rejected "
                "channel_id=%s "
                "provider=%s "
                "stage=%s "
                "attempt_id=%d "
                "digits=%d "
                "reason=stage_validation",
                (
                    session.channel_id
                    if session is not None
                    else "unknown"
                ),
                provider,
                normalized_stage,
                attempt_id,
                len(
                    digits
                ),
            )

            return False


        async with digit_completion_lock:

            # ====================================================
            # Ignore result belonging to old stage/attempt.
            # ====================================================

            if not is_current_digit_attempt(
                normalized_stage,
                attempt_id,
            ):

                logger.info(
                    "voice_digit_candidate_stale "
                    "channel_id=%s "
                    "provider=%s "
                    "stage=%s "
                    "attempt_id=%d "
                    "digits=%d",
                    (
                        session.channel_id
                        if session is not None
                        else "unknown"
                    ),
                    provider,
                    normalized_stage,
                    attempt_id,
                    len(
                        digits
                    ),
                )

                return False

            # ====================================================
            # Another provider already won.
            # ====================================================

            if is_digit_attempt_completed(
                normalized_stage,
                attempt_id,
            ):

                logger.info(
                    "voice_digit_candidate_duplicate "
                    "channel_id=%s "
                    "provider=%s "
                    "stage=%s "
                    "attempt_id=%d "
                    "action=ignore",
                    (
                        session.channel_id
                        if session is not None
                        else "unknown"
                    ),
                    provider,
                    normalized_stage,
                    attempt_id,
                )

                return False

            # ====================================================
            # FIRST EXACT RESULT WINS
            # ====================================================

            await cancel_pending_digit_retry_prompt(
                reason="digit_completed"
            )

            digit_completed_attempt = (
                normalized_stage,
                attempt_id,
            )

            if (
                provider == "deepgram"
                and active_hamsa_digit_task
                is not None
                and active_hamsa_digit_owner
                == (
                    normalized_stage,
                    attempt_id,
                )
                and not active_hamsa_digit_task.done()
            ):

                active_hamsa_digit_task.cancel()

                logger.info(
                    "hamsa_digit_cancel_requested "
                    "channel_id=%s "
                    "stage=%s "
                    "attempt_id=%d "
                    "reason=deepgram_won",
                    (
                        session.channel_id
                        if session is not None
                        else "unknown"
                    ),
                    normalized_stage,
                    attempt_id,
                )

            digit_attempt_force_restart = False

            digit_collector.reset()

            dropped_turns = (
                discard_pending_digit_turns(
                    normalized_stage,
                    attempt_id,
                )
            )

            if transcript_queue is None:

                logger.error(
                    "voice_digit_completion_queue_missing "
                    "channel_id=%s "
                    "provider=%s",
                    (
                        session.channel_id
                        if session is not None
                        else "unknown"
                    ),
                    provider,
                )

                return False

            transcript_queue.put_nowait(
                digits
            )

            logger.info(
                "voice_digit_arbitration_winner "
                "channel_id=%s "
                "provider=%s "
                "stage=%s "
                "attempt_id=%d "
                "turn=%s "
                "digits=%d "
                "stale_turns_dropped=%d",
                (
                    session.channel_id
                    if session is not None
                    else "unknown"
                ),
                provider,
                normalized_stage,
                attempt_id,
                turn_number,
                len(
                    digits
                ),
                dropped_turns,
            )

            return True


    async def wait_for_deepgram_normal_candidate(
        *,
        turn_number: int,
    ) -> str | None:
        """
        Wait briefly for Deepgram's final transcript
        when Hamsa fails or reaches the soft timeout.

        This is only used for normal conversational turns.

        Digit stages use the existing digit arbitration.
        """

        candidate = (
            deepgram_normal_candidates.get(
                turn_number
            )
        )

        if candidate:

            return (
                candidate.strip()
            )

        candidate_event = (
            deepgram_normal_candidate_events.get(
                turn_number
            )
        )

        if candidate_event is None:

            return None

        try:

            await asyncio.wait_for(
                candidate_event.wait(),
                timeout=(
                    DEEPGRAM_NORMAL_FALLBACK_WAIT_SECONDS
                ),
            )

        except asyncio.TimeoutError:

            logger.warning(
                "deepgram_normal_fallback_timeout "
                "channel_id=%s "
                "turn=%d "
                "wait_seconds=%.2f",
                (
                    session.channel_id
                    if session is not None
                    else "unknown"
                ),
                turn_number,
                DEEPGRAM_NORMAL_FALLBACK_WAIT_SECONDS,
            )

            return None

        candidate = (
            deepgram_normal_candidates.get(
                turn_number
            )
        )

        if not candidate:

            return None

        candidate = (
            candidate.strip()
        )

        if not is_valid_stt_transcript(
            candidate
        ):

            return None

        return candidate
    # ========================================================
    # SINGLE HAMSA WORKER
    # ========================================================

    async def hamsa_worker() -> None:
        nonlocal digit_attempt_force_restart
        nonlocal active_hamsa_digit_task
        nonlocal active_hamsa_digit_owner

        """
        Serial Hamsa worker.

        Digit stages use attempt-aware arbitration:
            Hamsa exact result
            vs
            Deepgram exact result

        First valid exact-length result wins.
        """

        if hamsa_work_queue is None:

            return

        while True:

            (
                turn_number,
                audio,
                stage_snapshot,
                detach_reason,
                attempt_id,
            ) = await hamsa_work_queue.get()

            try:

                if hamsa_primary is None:

                    logger.error(
                        "hamsa_primary_not_ready "
                        "turn=%d",
                        turn_number,
                    )

                    continue

                eos_enabled = (
                    detach_reason
                    != "max_duration"
                )

                expected_digits = (
                    get_expected_digit_count(
                        stage_snapshot
                    )
                )

                sensitive_stage = (
                    expected_digits
                    is not None
                )

                # ====================================================
                # Do not spend a Hamsa request on an old attempt.
                # ====================================================

                if (
                    sensitive_stage
                    and not is_current_digit_attempt(
                        stage_snapshot,
                        attempt_id,
                    )
                ):

                    logger.info(
                        "hamsa_stale_digit_turn_skipped "
                        "channel_id=%s "
                        "turn=%d "
                        "stage=%s "
                        "attempt_id=%d",
                        (
                            session.channel_id
                            if session is not None
                            else "unknown"
                        ),
                        turn_number,
                        stage_snapshot,
                        attempt_id,
                    )

                    continue

                if (
                    sensitive_stage
                    and is_digit_attempt_completed(
                        stage_snapshot,
                        attempt_id,
                    )
                ):

                    logger.info(
                        "hamsa_completed_digit_turn_skipped "
                        "channel_id=%s "
                        "turn=%d "
                        "stage=%s "
                        "attempt_id=%d",
                        (
                            session.channel_id
                            if session is not None
                            else "unknown"
                        ),
                        turn_number,
                        stage_snapshot,
                        attempt_id,
                    )

                    continue

                logger.info(
                    "hamsa_primary_started "
                    "channel_id=%s "
                    "turn=%d "
                    "stage=%s "
                    "attempt_id=%d "
                    "reason=%s "
                    "eos_enabled=%s "
                    "sensitive=%s "
                    "audio_bytes=%d "
                    "queue_size=%d",
                    (
                        session.channel_id
                        if session is not None
                        else "unknown"
                    ),
                    turn_number,
                    stage_snapshot,
                    attempt_id,
                    detach_reason,
                    eos_enabled,
                    sensitive_stage,
                    len(
                        audio
                    ),
                    hamsa_work_queue.qsize(),
                )

                try:

                    # ====================================================
                    # Normal conversation:
                    #
                    # Do not allow a stuck Hamsa request to block
                    # the whole call for 20 seconds.
                    # ====================================================

                    if expected_digits is None:

                        try:


                            hamsa_processing_event = (
                                asyncio.Event()
                            )


                            def on_hamsa_status(
                                status: str,
                            ) -> None:

                                normalized_status = (
                                    status
                                    .strip()
                                    .upper()
                                )

                                if normalized_status in {
                                    "[THINKING]",
                                    "[PROCESSING]",
                                    "[TRANSCRIBING]",
                                }:

                                    hamsa_processing_event.set()

                                    logger.info(
                                        "hamsa_processing_status_detected "
                                        "channel_id=%s "
                                        "turn=%d "
                                        "stage=%s "
                                        "status=%s",
                                        (
                                            session.channel_id
                                            if session is not None
                                            else "unknown"
                                        ),
                                        turn_number,
                                        stage_snapshot,
                                        normalized_status,
                                    )

                            allow_early_deepgram = (
                                stage_snapshot
                                not in CRITICAL_DUAL_STT_STAGES
                                and stage_snapshot
                                not in NAME_DUAL_STT_STAGES
                            )

                            loop = asyncio.get_running_loop()

                            hamsa_budget_seconds = (
                                HAMSA_FAST_NORMAL_BUDGET_SECONDS
                                if allow_early_deepgram
                                else HAMSA_NORMAL_SOFT_TIMEOUT_SECONDS
                            )

                            hamsa_deadline = (
                                loop.time()
                                + hamsa_budget_seconds
                            )
                            hamsa_task = (
                                asyncio.create_task(
                                    hamsa_primary.transcribe(
                                        audio,
                                        eos_enabled=eos_enabled,
                                        sensitive=False,
                                        on_status=on_hamsa_status,
                                    ),
                                    name=(
                                        "hamsa-normal-turn-"
                                        f"{turn_number}"
                                    ),
                                )
                            )

                            transcript = ""

                            # ====================================================
                            # Critical confirmation stages keep the existing
                            # Hamsa-first safety behavior.
                            # ====================================================
                            processing_wait_task: (
                                asyncio.Task | None
                            ) = None

                            deepgram_wait_task: (
                                asyncio.Task | None
                            ) = None

                            try:

                                # ====================================================
                                # Normal conversation:
                                #
                                # Race:
                                #   Hamsa final transcript
                                #       vs
                                #   Hamsa processing status
                                #
                                # We do NOT cancel Hamsa.
                                # ====================================================

                                if allow_early_deepgram:

                                    processing_wait_task = (
                                        asyncio.create_task(
                                            hamsa_processing_event.wait(),
                                            name=(
                                                "hamsa-processing-status-"
                                                f"{turn_number}"
                                            ),
                                        )
                                    )

                                    remaining = max(
                                        0.0,
                                        hamsa_deadline
                                        - loop.time(),
                                    )

                                    done, _ = await asyncio.wait(
                                        {
                                            hamsa_task,
                                            processing_wait_task,
                                        },
                                        timeout=remaining,
                                        return_when=(
                                            asyncio.FIRST_COMPLETED
                                        ),
                                    )

                                    # ================================================
                                    # Hamsa completed normally.
                                    # ================================================

                                    if hamsa_task in done:

                                        transcript = (
                                            hamsa_task.result()
                                        )

                                    # ================================================
                                    # Hamsa entered THINKING / PROCESSING.
                                    #
                                    # Give already-running streaming Deepgram a short
                                    # chance to provide the final transcript.
                                    # ================================================

                                    elif (
                                        processing_wait_task
                                        in done
                                    ):

                                        candidate_event = (
                                            deepgram_normal_candidate_events.get(
                                                turn_number
                                            )
                                        )

                                        if candidate_event is not None:

                                            deepgram_wait_task = (
                                                asyncio.create_task(
                                                    candidate_event.wait(),
                                                    name=(
                                                        "deepgram-early-fallback-"
                                                        f"{turn_number}"
                                                    ),
                                                )
                                            )

                                            remaining = max(
                                                0.0,
                                                min(
                                                    DEEPGRAM_NORMAL_FALLBACK_WAIT_SECONDS,
                                                    hamsa_deadline
                                                    - loop.time(),
                                                ),
                                            )

                                            done, _ = await asyncio.wait(
                                                {
                                                    hamsa_task,
                                                    deepgram_wait_task,
                                                },
                                                timeout=remaining,
                                                return_when=(
                                                    asyncio.FIRST_COMPLETED
                                                ),
                                            )

                                            if hamsa_task in done:

                                                transcript = (
                                                    hamsa_task.result()
                                                )

                                            elif (
                                                deepgram_wait_task
                                                in done
                                            ):

                                                candidate = (
                                                    deepgram_normal_candidates.get(
                                                        turn_number
                                                    )
                                                )

                                                if (
                                                    candidate
                                                    and is_valid_stt_transcript(
                                                        candidate
                                                    )
                                                ):

                                                    transcript = (
                                                        candidate.strip()
                                                    )

                                                    # ====================================================
                                                    # Deepgram already resolved this turn.
                                                    #
                                                    # Do not leave the old Hamsa request running because
                                                    # Hamsa uses one persistent WebSocket and one request
                                                    # lock. A stale request can block or reset a later turn.
                                                    # ====================================================

                                                    if not hamsa_task.done():

                                                        hamsa_task.cancel()

                                                        try:

                                                            await hamsa_task

                                                        except asyncio.CancelledError:

                                                            pass

                                                        except Exception:

                                                            logger.error(
                                                                "hamsa_stale_request_cleanup_failed "
                                                                "channel_id=%s "
                                                                "turn=%d "
                                                                "%s "
                                                                "stage=%s",
                                                                (
                                                                    session.channel_id
                                                                    if session is not None
                                                                    else "unknown"
                                                                ),
                                                                turn_number,
                                                                exception_fields(),
                                                                conversation_state.get("stage", "new"),
                                                            )

                                                    logger.info(
                                                        "voice_stt_early_fallback_selected "
                                                        "channel_id=%s "
                                                        "turn=%d "
                                                        "stage=%s "
                                                        "primary=hamsa "
                                                        "fallback=deepgram "
                                                        "reason=hamsa_processing "
                                                        "hamsa_action=cancel_stale_request",
                                                        (
                                                            session.channel_id
                                                            if session is not None
                                                            else "unknown"
                                                        ),
                                                        turn_number,
                                                        stage_snapshot,
                                                    )
                                # ====================================================
                                # If nobody won yet, give Hamsa the REST of its
                                # original 3-second budget.
                                #
                                # asyncio.shield is critical:
                                # timeout must NOT cancel the persistent Hamsa request.
                                # ====================================================

                                if not transcript:

                                    remaining = max(
                                        0.0,
                                        hamsa_deadline
                                        - loop.time(),
                                    )

                                    if remaining > 0:

                                        try:

                                            transcript = (
                                                await asyncio.wait_for(
                                                    asyncio.shield(
                                                        hamsa_task
                                                    ),
                                                    timeout=remaining,
                                                )
                                            )

                                        except asyncio.TimeoutError:

                                            transcript = ""

                                    if (
                                        not transcript
                                        and not hamsa_task.done()
                                    ):

                                        logger.warning(
                                            "hamsa_normal_latency_budget_exceeded "
                                            "channel_id=%s "
                                            "turn=%d "
                                            "stage=%s "
                                            "budget_seconds=%.2f "
                                            "action=immediate_deepgram_fallback",
                                            (
                                                session.channel_id
                                                if session is not None
                                                else "unknown"
                                            ),
                                            turn_number,
                                            stage_snapshot,
                                            hamsa_budget_seconds,
                                        )

                                        hamsa_task.cancel()

                                        async def cleanup_hamsa_after_fallback(
                                            task: asyncio.Task,
                                            turn: int,
                                        ) -> None:

                                            # --------------------------------------------
                                            # Finish cancellation first.
                                            # --------------------------------------------

                                            try:

                                                await task

                                            except asyncio.CancelledError:

                                                pass

                                            except Exception:

                                                logger.error(
                                                    "hamsa_background_cleanup_failed "
                                                    "channel_id=%s "
                                                    "turn=%d "
                                                    "%s "
                                                    "stage=%s",
                                                    (
                                                        session.channel_id
                                                        if session is not None
                                                        else "unknown"
                                                    ),
                                                    turn,
                                                    exception_fields(),
                                                    conversation_state.get("stage", "new"),
                                                )

                                            # --------------------------------------------
                                            # Preconnect a fresh Hamsa socket while
                                            # Deepgram / MedMind continue the caller path.
                                            # --------------------------------------------

                                            try:

                                                if hamsa_primary is not None:

                                                    await hamsa_primary.start()

                                                logger.info(
                                                    "hamsa_background_reconnect_ready "
                                                    "channel_id=%s "
                                                    "turn=%d",
                                                    (
                                                        session.channel_id
                                                        if session is not None
                                                        else "unknown"
                                                    ),
                                                    turn,
                                                )

                                            except Exception:

                                                logger.warning(
                                                    "hamsa_background_reconnect_failed "
                                                    "channel_id=%s "
                                                    "turn=%d",
                                                    (
                                                        session.channel_id
                                                        if session is not None
                                                        else "unknown"
                                                    ),
                                                    turn,
                                                )

                                        recovery_task = asyncio.create_task(
                                            cleanup_hamsa_after_fallback(
                                                hamsa_task,
                                                turn_number,
                                            ),
                                            name=(
                                                "hamsa-background-recovery-"
                                                f"{turn_number}"
                                            ),
                                        )

                                        hamsa_drain_tasks.add(
                                            recovery_task
                                        )

                                        recovery_task.add_done_callback(
                                            hamsa_drain_tasks.discard
                                        )

                            finally:

                                if (
                                    processing_wait_task
                                    is not None
                                    and not processing_wait_task.done()
                                ):
                                    processing_wait_task.cancel()

                                if (
                                    deepgram_wait_task
                                    is not None
                                    and not deepgram_wait_task.done()
                                ):
                                    deepgram_wait_task.cancel()        

                        except asyncio.TimeoutError:

                            logger.warning(
                                "hamsa_normal_soft_timeout "
                                "channel_id=%s "
                                "turn=%d "
                                "stage=%s "
                                "timeout_seconds=%.2f "
                                "action=try_deepgram",
                                (
                                    session.channel_id
                                    if session is not None
                                    else "unknown"
                                ),
                                turn_number,
                                stage_snapshot,
                                HAMSA_NORMAL_SOFT_TIMEOUT_SECONDS,
                            )

                            transcript = ""

                    else:

                        try:

                            digit_hamsa_task = (
                                asyncio.create_task(
                                    hamsa_primary.transcribe(
                                        audio,
                                        eos_enabled=eos_enabled,
                                        sensitive=True,
                                    ),
                                    name=(
                                        "hamsa-digit-turn-"
                                        f"{turn_number}"
                                    ),
                                )
                            )

                            active_hamsa_digit_task = (
                                digit_hamsa_task
                            )

                            active_hamsa_digit_owner = (
                                stage_snapshot
                                .strip()
                                .lower(),
                                attempt_id,
                            )

                            try:

                                transcript = (
                                    await asyncio.wait_for(
                                        digit_hamsa_task,
                                        timeout=(
                                            HAMSA_DIGIT_SOFT_TIMEOUT_SECONDS
                                        ),
                                    )
                                )

                            except asyncio.CancelledError:

                                # Deepgram already completed this exact
                                # digit attempt, so this Hamsa request is stale.
                                if is_digit_attempt_completed(
                                    stage_snapshot,
                                    attempt_id,
                                ):

                                    logger.info(
                                        "hamsa_digit_request_cancelled_after_"
                                        "arbitration "
                                        "channel_id=%s "
                                        "turn=%d "
                                        "stage=%s "
                                        "attempt_id=%d",
                                        (
                                            session.channel_id
                                            if session is not None
                                            else "unknown"
                                        ),
                                        turn_number,
                                        stage_snapshot,
                                        attempt_id,
                                    )

                                    transcript = ""

                                    # Pre-warm the fresh persistent connection while
                                    # MedMind/TTS handle the already accepted digits.
                                    try:

                                        await hamsa_primary.start()

                                    except Exception:

                                        logger.warning(
                                            "hamsa_digit_reconnect_failed "
                                            "channel_id=%s "
                                            "turn=%d",
                                            (
                                                session.channel_id
                                                if session is not None
                                                else "unknown"
                                            ),
                                            turn_number,
                                        )

                                else:

                                    raise

                            finally:

                                if (
                                    active_hamsa_digit_task
                                    is digit_hamsa_task
                                ):

                                    active_hamsa_digit_task = None
                                    active_hamsa_digit_owner = None

                        except asyncio.TimeoutError:

                            logger.warning(
                                "hamsa_digit_soft_timeout "
                                "channel_id=%s "
                                "turn=%d "
                                "stage=%s "
                                "attempt_id=%d "
                                "timeout_seconds=%.2f "
                                "action=continue_digit_arbitration",
                                (
                                    session.channel_id
                                    if session is not None
                                    else "unknown"
                                ),
                                turn_number,
                                stage_snapshot,
                                attempt_id,
                                HAMSA_DIGIT_SOFT_TIMEOUT_SECONDS,
                            )

                            transcript = ""

                except asyncio.CancelledError:

                    raise

                except Exception:

                    logger.error(
                        "hamsa_primary_processing_failed "
                        "channel_id=%s "
                        "turn=%d "
                        "%s "
                        "stage=%s",
                        (
                            session.channel_id
                            if session is not None
                            else "unknown"
                        ),
                        turn_number,
                        exception_fields(),
                        conversation_state.get("stage", "new"),
                    )

                    transcript = ""

                transcript = (
                    transcript.strip()
                )

                # ============================================================
                # Patient Name Dual-STT Arbitration
                # ============================================================

                if (
                    expected_digits is None
                    and stage_snapshot in NAME_DUAL_STT_STAGES
                ):

                    deepgram_name_candidate = (
                        await wait_for_deepgram_normal_candidate(
                            turn_number=turn_number,
                        )
                    )

                    name_decision = (
                        resolve_name_stage_transcript(
                            stage=stage_snapshot,
                            hamsa_transcript=transcript,
                            deepgram_transcript=(
                                deepgram_name_candidate
                            ),
                        )
                    )
                    if name_decision is None:

                        logger.error(
                            "voice_name_stt_arbitration_missing_decision "
                            "channel_id=%s "
                            "turn=%d "
                            "stage=%s",
                            (
                                session.channel_id
                                if session is not None
                                else "unknown"
                            ),
                            turn_number,
                            stage_snapshot,
                        )

                        if transcript_queue is not None:
                            transcript_queue.put_nowait(
                                LOCAL_TTS_PREFIX
                                + (
                                    "مسمعتش الاسم كويس، "
                                    "ممكن تقوله تاني؟"
                                )
                            )

                        continue

                    logger.info(
                        "voice_name_stt_arbitration "
                        "channel_id=%s "
                        "turn=%d "
                        "stage=%s "
                        "action=%s "
                        "provider=%s "
                        "reason=%s "
                        "hamsa_chars=%d "
                        "deepgram_chars=%d",
                        (
                            session.channel_id
                            if session is not None
                            else "unknown"
                        ),
                        turn_number,
                        stage_snapshot,
                        name_decision.action,
                        name_decision.provider or "none",
                        name_decision.reason,
                        len(transcript),
                        len(deepgram_name_candidate or ""),
                    )

                    if name_decision.action == "retry":

                        if transcript_queue is not None:

                            transcript_queue.put_nowait(
                                LOCAL_TTS_PREFIX
                                + (
                                    "مسمعتش الاسم كويس، "
                                    "ممكن تقوله تاني؟"
                                )
                            )

                        continue

                    transcript = (
                        name_decision.transcript or ""
                    )

                if (
                    expected_digits is None
                    and not is_valid_stt_transcript(
                        transcript
                    )
                ):

                    if (
                        stage_snapshot
                        in CRITICAL_DUAL_STT_STAGES
                    ):

                        logger.warning(
                            "voice_critical_hamsa_unavailable "
                            "channel_id=%s "
                            "turn=%d "
                            "stage=%s "
                            "action=block_and_reconfirm",
                            (
                                session.channel_id
                                if session is not None
                                else "unknown"
                            ),
                            turn_number,
                            stage_snapshot,
                        )

                        if transcript_queue is not None:

                            transcript_queue.put_nowait(
                                LOCAL_TTS_PREFIX
                                + get_critical_stt_retry_prompt(
                                    stage_snapshot
                                )
                            )

                        continue

                    deepgram_fallback = (
                        await wait_for_deepgram_normal_candidate(
                            turn_number=turn_number,
                        )
                    )

                    if deepgram_fallback:

                        transcript = (
                            deepgram_fallback
                        )

                        logger.info(
                            "voice_stt_fallback_selected "
                            "channel_id=%s "
                            "turn=%d "
                            "stage=%s "
                            "primary=hamsa "
                            "fallback=deepgram",
                            (
                                session.channel_id
                                if session is not None
                                else "unknown"
                            ),
                            turn_number,
                            stage_snapshot,
                        )

                # ====================================================
                # Validation
                # ====================================================

                if not is_valid_stt_transcript(
                    transcript
                ):

                    logger.warning(
                        "hamsa_primary_invalid_transcript "
                        "channel_id=%s "
                        "turn=%d "
                        "stage=%s "
                        "attempt_id=%d "
                        "sensitive=%s",
                        (
                            session.channel_id
                            if session is not None
                            else "unknown"
                        ),
                        turn_number,
                        stage_snapshot,
                        attempt_id,
                        sensitive_stage,
                    )

                    continue

                # ====================================================
                # Digit Stage
                # ====================================================

                if expected_digits is not None:

                    # Deepgram may have won while Hamsa was running.
                    if is_digit_attempt_completed(
                        stage_snapshot,
                        attempt_id,
                    ):

                        logger.info(
                            "hamsa_result_ignored_after_"
                            "digit_completion "
                            "channel_id=%s "
                            "turn=%d "
                            "stage=%s "
                            "attempt_id=%d",
                            (
                                session.channel_id
                                if session is not None
                                else "unknown"
                            ),
                            turn_number,
                            stage_snapshot,
                            attempt_id,
                        )

                        continue

                    # New attempt may already have started.
                    if not is_current_digit_attempt(
                        stage_snapshot,
                        attempt_id,
                    ):

                        logger.info(
                            "hamsa_stale_result_ignored "
                            "channel_id=%s "
                            "turn=%d "
                            "stage=%s "
                            "attempt_id=%d",
                            (
                                session.channel_id
                                if session is not None
                                else "unknown"
                            ),
                            turn_number,
                            stage_snapshot,
                            attempt_id,
                        )

                        continue

                    detected_digits = (
                        extract_spoken_digits(
                            transcript
                        )
                    )

                    has_digit_evidence = (
                        len(detected_digits) > 0
                    )

                    normalized_digit_stage = (
                        stage_snapshot
                        .strip()
                        .lower()
                    )

                    has_partial_digit_attempt = (
                        digit_collector.stage
                        == normalized_digit_stage
                        and digit_collector.attempt_id
                        == attempt_id
                        and bool(
                            digit_collector.buffer
                        )
                    )

                    if (
                        not has_digit_evidence
                        and not is_digit_entry_utterance(
                            transcript
                        )
                        and not has_partial_digit_attempt
                    ):
                        await route_digit_stage_conversation(
                            provider="hamsa",
                            transcript=transcript,
                            stage=stage_snapshot,
                            attempt_id=attempt_id,
                            turn_number=turn_number,
                        )

                        continue

                    # ====================================================
                    # REAL DIGIT INPUT
                    # ====================================================

                    (
                        completed_digits,
                        collected_count,
                        expected_count,
                    ) = digit_collector.consume(
                        stage=stage_snapshot,
                        attempt_id=attempt_id,
                        transcript=transcript,
                    )

                    if completed_digits is None:

                        logger.info(
                            "voice_digit_collection_partial "
                            "channel_id=%s "
                            "provider=hamsa "
                            "turn=%d "
                            "stage=%s "
                            "attempt_id=%d "
                            "collected=%d "
                            "expected=%d",
                            (
                                session.channel_id
                                if session is not None
                                else "unknown"
                            ),
                            turn_number,
                            stage_snapshot,
                            attempt_id,
                            collected_count,
                            expected_count,
                        )

                        if (
                            detach_reason == "silence"
                            and not hamsa_utterance_active
                            and not barge_in_speech_active
                        ):

                            schedule_digit_incomplete_retry(
                                stage=stage_snapshot,
                                attempt_id=attempt_id,
                            )

                        else:

                            logger.info(
                                "voice_digit_retry_not_scheduled "
                                "channel_id=%s "
                                "turn=%d "
                                "stage=%s "
                                "attempt_id=%d "
                                "reason=speech_active_or_not_silence",
                                (
                                    session.channel_id
                                    if session is not None
                                    else "unknown"
                                ),
                                turn_number,
                                stage_snapshot,
                                attempt_id,
                            )

                        continue

                    if (
                        collected_count
                        != expected_count
                    ):

                        logger.warning(
                            "voice_digit_collection_"
                            "length_mismatch "
                            "channel_id=%s "
                            "provider=hamsa "
                            "turn=%d "
                            "stage=%s "
                            "attempt_id=%d "
                            "collected=%d "
                            "expected=%d "
                            "action=reject",
                            (
                                session.channel_id
                                if session is not None
                                else "unknown"
                            ),
                            turn_number,
                            stage_snapshot,
                            attempt_id,
                            collected_count,
                            expected_count,
                        )

                        digit_attempt_force_restart = (
                            True
                        )

                        continue

                    await complete_digit_attempt(
                        provider="hamsa",
                        stage=stage_snapshot,
                        attempt_id=attempt_id,
                        digits=completed_digits,
                        turn_number=turn_number,
                    )

                    continue

                # ====================================================
                # Normal Conversational Stage
                # ====================================================

                digit_collector.reset()

                if (
                    stage_snapshot
                    in CRITICAL_DUAL_STT_STAGES
                ):

                    deepgram_candidate = (
                        await wait_for_deepgram_normal_candidate(
                            turn_number=turn_number,
                        )
                    )

                    if (
                        deepgram_candidate
                        and critical_stt_actions_disagree(
                            hamsa_transcript=transcript,
                            deepgram_transcript=deepgram_candidate,
                            stage=stage_snapshot,
                        )
                    ):

                        logger.warning(
                            "voice_critical_stt_disagreement "
                            "channel_id=%s "
                            "turn=%d "
                            "stage=%s "
                            "hamsa_action=%s "
                            "deepgram_action=%s "
                            "action=block_and_reconfirm",

                            (
                                session.channel_id
                                if session is not None
                                else "unknown"
                            ),

                            turn_number,
                            stage_snapshot,

                            classify_confirmation_action(
                                transcript,
                                stage=stage_snapshot,
                            ),

                            classify_confirmation_action(
                                deepgram_candidate,
                                stage=stage_snapshot,
                            ),
                        )

                        if transcript_queue is not None:

                            transcript_queue.put_nowait(
                                LOCAL_TTS_PREFIX
                                + get_critical_stt_retry_prompt(
                                    stage_snapshot
                                )
                            )

                        # CRITICAL
                        # Don't send either transcript to MedMind.
                        continue

                if transcript_queue is not None:

                    transcript_queue.put_nowait(
                        transcript
                    )

                logger.info(
                    "hamsa_primary_transcript_queued "
                    "channel_id=%s "
                    "turn=%d "
                    "transcript_chars=%d",
                    (
                        session.channel_id
                        if session is not None
                        else "unknown"
                    ),
                    turn_number,
                    len(transcript),
                )

            finally:

                # ====================================================
                # Close normal-turn fallback state.
                # ====================================================

                if (
                    get_expected_digit_count(
                        stage_snapshot
                    )
                    is None
                ):

                    closed_normal_turns.add(
                        turn_number
                    )

                    deepgram_normal_candidates.pop(
                        turn_number,
                        None,
                    )

                    deepgram_normal_candidate_events.pop(
                        turn_number,
                        None,
                    )

                hamsa_work_queue.task_done()

    # ========================================================
    # Detach Current Audio
    #
    # This function NEVER calls Hamsa directly.
    #
    # It only:
    #
    # buffer -> snapshot -> queue
    # ========================================================

    async def enqueue_current_hamsa_turn(
        *,
        reason: str,
        keep_active: bool,
        finalize_deepgram: bool,
    ) -> int | None:

        nonlocal hamsa_turn_number
        nonlocal hamsa_utterance_active

        if (
            session is None
            or hamsa_primary is None
            or hamsa_work_queue is None
        ):

            return None

        if (
            not hamsa_utterance_active
            or not hamsa_utterance_audio
        ):

            return None

        # ====================================================
        # New turn number
        # ====================================================

        hamsa_turn_number += (
            1
        )

        turn_number = (
            hamsa_turn_number
        )

        # ====================================================
        # Snapshot Audio
        # ====================================================

        audio = bytes(
            hamsa_utterance_audio
        )

        hamsa_utterance_audio.clear()

        # ====================================================
        # Hard split:
        #
        # keep_active=True
        #
        # Caller is still speaking.
        #
        # Natural silence:
        #
        # keep_active=False
        # ====================================================

        if (
            not keep_active
        ):

            hamsa_utterance_active = (
                False
            )

        stage_snapshot = (
            conversation_state.get(
                "stage",
                "new",
            )
        )

        if (
            get_expected_digit_count(
                stage_snapshot
            )
            is not None
        ):

            attempt_snapshot = (
                digit_attempt_id
            )

        else:

            attempt_snapshot = (
                0
            )

        # ====================================================
        # Prepare Deepgram fallback for normal turns.
        #
        # Digit stages use digit arbitration instead.
        # ====================================================

        if (
            get_expected_digit_count(
                stage_snapshot
            )
            is None
        ):

            deepgram_normal_candidate_events[
                turn_number
            ] = (
                asyncio.Event()
            )

            deepgram_normal_candidates.pop(
                turn_number,
                None,
            )

            closed_normal_turns.discard(
                turn_number
            )


        logger.info(
            "voice_turn_detached "
            "channel_id=%s "
            "turn=%d "
            "stage=%s "
            "attempt_id=%d "
            "reason=%s "
            "audio_bytes=%d "
            "keep_active=%s",
            session.channel_id,
            turn_number,
            stage_snapshot,
            attempt_snapshot,
            reason,
            len(
                audio
            ),
            keep_active,
        )

        # ====================================================
        # QUEUE
        #
        # Never create multiple Hamsa tasks here.
        # ====================================================

        hamsa_work_queue.put_nowait(
            (
                turn_number,
                audio,
                stage_snapshot,
                reason,
                attempt_snapshot,
            )
        )

        logger.info(
            "hamsa_turn_queued "
            "channel_id=%s "
            "turn=%d "
            "stage=%s "
            "attempt_id=%d "
            "reason=%s "
            "queue_size=%d",
            session.channel_id,
            turn_number,
            stage_snapshot,
            attempt_snapshot,
            reason,
            hamsa_work_queue.qsize(),
        )

        # ====================================================
        # Deepgram only finalizes on real VAD end.
        #
        # Hard Hamsa split keeps Deepgram continuous.
        # ====================================================

        if (
            finalize_deepgram
        ):

            schedule_deepgram_finalize(
                session.channel_id,
                owner=(
                    turn_number,
                    str(
                        stage_snapshot
                    )
                    .strip()
                    .lower(),
                    attempt_snapshot,
                ),
            )

        return (
            turn_number
        )

    # ========================================================
    # Silence Grace
    # ========================================================

    async def finalize_after_turn_grace() -> None:

        nonlocal pending_turn_finalize_task


        try:

            current_stage = (
                conversation_state.get(
                    "stage",
                    "new",
                )
            )

            grace_seconds = (
                get_turn_end_grace_seconds(
                    current_stage
                )
            )

            logger.info(
                "voice_turn_end_grace_started "
                "channel_id=%s "
                "stage=%s "
                "grace_ms=%d",
                (
                    session.channel_id
                    if session is not None
                    else "unknown"
                ),
                current_stage,
                int(
                    grace_seconds
                    * 1000
                ),
            )

            # ====================================================
            # ONLY THIS SLEEP may be cancelled if speech resumes.
            # ====================================================

            await asyncio.sleep(
                grace_seconds
            )

            # ====================================================
            # Grace has ended.
            #
            # Remove the task reference BEFORE audio detach.
            #
            # Therefore new speech cannot cancel Hamsa queueing.
            # ====================================================

            current_task = (
                asyncio.current_task()
            )

            if (
                pending_turn_finalize_task
                is current_task
            ):

                pending_turn_finalize_task = (
                    None
                )

            turn_number = (
                await enqueue_current_hamsa_turn(
                    reason="silence",
                    keep_active=False,
                    finalize_deepgram=True,
                )
            )

            logger.info(
                "voice_turn_end_grace_completed "
                "channel_id=%s "
                "turn=%s "
                "stage=%s",
                (
                    session.channel_id
                    if session is not None
                    else "unknown"
                ),
                turn_number,
                current_stage,
            )

        except asyncio.CancelledError:

            logger.info(
                "voice_turn_end_grace_cancelled "
                "channel_id=%s "
                "reason=speech_resumed",
                (
                    session.channel_id
                    if session is not None
                    else "unknown"
                ),
            )

            raise

        finally:

            current_task = (
                asyncio.current_task()
            )

            if (
                pending_turn_finalize_task
                is current_task
            ):

                pending_turn_finalize_task = (
                    None
                )

    # ========================================================
    # HARD MAX DIGIT CHUNK
    # ========================================================

    async def maybe_split_long_digit_utterance(
        *,
        vad_events: list[
            dict
        ],
    ) -> None:
        """
        During national ID / phone collection:

        if caller keeps speaking continuously for ~4 sec:

            detach current Hamsa chunk
            queue it
            keep capturing next audio

        No need to wait for VAD silence.

        Deepgram remains continuous.
        """

        if (
            session is None
            or session.audio_format
            != "slin24"
        ):

            return

        if (
            not hamsa_utterance_active
            or not hamsa_utterance_audio
        ):

            return

        current_stage = (
            conversation_state.get(
                "stage",
                "new",
            )
        )

        max_audio_bytes = (
            get_digit_max_audio_bytes(
                stage=current_stage,
                sample_rate=(
                    session.sample_rate
                ),
            )
        )

        # Not a digit stage.
        if (
            max_audio_bytes
            is None
        ):

            return

        # ====================================================
        # Natural VAD end wins.
        #
        # Avoid hard split and normal split in same frame.
        # ====================================================

        if any(
            "end" in event
            for event in vad_events
        ):

            return

        if (
            len(
                hamsa_utterance_audio
            )
            < max_audio_bytes
        ):

            return

        logger.info(
            "voice_digit_hard_split_triggered "
            "channel_id=%s "
            "stage=%s "
            "audio_bytes=%d "
            "max_bytes=%d "
            "max_seconds=%.2f",
            session.channel_id,
            current_stage,
            len(
                hamsa_utterance_audio
            ),
            max_audio_bytes,
            DIGIT_MAX_UTTERANCE_SECONDS,
        )

        # ====================================================
        # Caller still speaking.
        #
        # Keep capture active.
        #
        # New incoming frames create the next chunk.
        # ====================================================

        await (
            enqueue_current_hamsa_turn(
                reason="max_duration",
                keep_active=True,
                finalize_deepgram=False,
            )
        )

    async def cancel_barge_in_guard(
    *,
    reason: str,
) -> None:

        nonlocal barge_in_guard_task

        task = (
            barge_in_guard_task
        )

        if (
            task is None
            or task.done()
        ):

            barge_in_guard_task = None

            return

        task.cancel()

        try:

            await task

        except asyncio.CancelledError:

            pass

        finally:

            barge_in_guard_task = None

        logger.debug(
            "voice_barge_in_guard_cancelled "
            "channel_id=%s "
            "reason=%s",
            (
                session.channel_id
                if session is not None
                else "unknown"
            ),
            reason,
        )


    # ========================================================
    # Barge-in Guard
    # ========================================================

    async def run_barge_in_guard(
        *,
        expected_correlation_id: str,
    ) -> None:

        nonlocal barge_in_speech_active

        try:

            # ----------------------------------------------------
            # Require sustained caller speech.
            # ----------------------------------------------------

            await asyncio.sleep(
                BARGE_IN_MIN_SPEECH_SECONDS
            )

            if not barge_in_speech_active:
                return

            if not BARGE_IN_ENABLED:
                return

            # ----------------------------------------------------
            # Playback must still be active.
            # ----------------------------------------------------

            if not conversation_state.get(
                PLAYBACK_ACTIVE_KEY,
                False,
            ):
                return

            current_correlation_id = (
                conversation_state.get(
                    PLAYBACK_CORRELATION_KEY
                )
            )

            if (
                not current_correlation_id
                or
                str(
                    current_correlation_id
                )
                != expected_correlation_id
            ):
                return

            # ----------------------------------------------------
            # Do not interrupt terminal prompts.
            # ----------------------------------------------------

            current_stage = str(
                conversation_state.get(
                    "stage",
                    "new",
                )
            )

            if (
                current_stage
                in TERMINAL_CALL_STAGES
            ):

                logger.info(
                    "voice_barge_in_ignored "
                    "channel_id=%s "
                    "stage=%s "
                    "reason=terminal_stage",
                    (
                        session.channel_id
                        if session is not None
                        else "unknown"
                    ),
                    current_stage,
                )

                return

            loop = (
                asyncio.get_running_loop()
            )

            now = (
                loop.time()
            )

            # ----------------------------------------------------
            # Initial playback protection.
            # ----------------------------------------------------

            playback_started_at = (
                conversation_state.get(
                    PLAYBACK_STARTED_AT_KEY
                )
            )

            if playback_started_at is not None:

                playback_age = (
                    now
                    - float(
                        playback_started_at
                    )
                )

                remaining_protection = (
                    BARGE_IN_INITIAL_PROTECTION_SECONDS
                    - playback_age
                )

                if remaining_protection > 0:

                    await asyncio.sleep(
                        remaining_protection
                    )

                    if not barge_in_speech_active:
                        return

                    if not conversation_state.get(
                        PLAYBACK_ACTIVE_KEY,
                        False,
                    ):
                        return

                    if (
                        str(
                            conversation_state.get(
                                PLAYBACK_CORRELATION_KEY,
                                "",
                            )
                        )
                        != expected_correlation_id
                    ):
                        return

                    now = (
                        loop.time()
                    )

            # ----------------------------------------------------
            # Cooldown.
            # ----------------------------------------------------

            last_barge_in_at = (
                conversation_state.get(
                    LAST_BARGE_IN_AT_KEY
                )
            )

            if last_barge_in_at is not None:

                if (
                    now
                    - float(
                        last_barge_in_at
                    )
                    < BARGE_IN_COOLDOWN_SECONDS
                ):

                    logger.info(
                        "voice_barge_in_ignored "
                        "channel_id=%s "
                        "stage=%s "
                        "reason=cooldown",
                        (
                            session.channel_id
                            if session is not None
                            else "unknown"
                        ),
                        current_stage,
                    )

                    return

            # ====================================================
            # BARGE-IN CONFIRMED
            # ====================================================

            await flush_media(
                websocket,
                send_lock=media_send_lock,
            )

            conversation_state[
                PLAYBACK_ACTIVE_KEY
            ] = False

            conversation_state.pop(
                PLAYBACK_CORRELATION_KEY,
                None,
            )

            conversation_state.pop(
                PLAYBACK_STARTED_AT_KEY,
                None,
            )

            conversation_state[
                LAST_BARGE_IN_AT_KEY
            ] = now

            logger.info(
                "voice_barge_in_triggered "
                "channel_id=%s "
                "stage=%s "
                "interrupted_correlation_id=%s "
                "min_speech_ms=%d",
                (
                    session.channel_id
                    if session is not None
                    else "unknown"
                ),
                current_stage,
                expected_correlation_id,
                int(
                    BARGE_IN_MIN_SPEECH_SECONDS
                    * 1000
                ),
            )

        except asyncio.CancelledError:

            raise

        except Exception as exc:

            logger.error(
                "voice_barge_in_failed "
                "channel_id=%s "
                "%s "
                "stage=%s",
                (
                    session.channel_id
                    if session is not None
                    else "unknown"
                ),
                exception_fields(),
                conversation_state.get("stage", "new"),
            )
        
    # ========================================================
    # Main WebSocket Loop
    # ========================================================

    try:

        while True:

            if media_authorization is None:
                try:
                    message = await asyncio.wait_for(
                        websocket.receive(),
                        timeout=max(
                            0.0,
                            media_auth_deadline
                            - event_loop.time(),
                        ),
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "media_auth_rejected "
                        "reason=auth_timeout "
                        "client=%s",
                        client,
                    )
                    await websocket.close(
                        code=POLICY_VIOLATION_CLOSE_CODE
                    )
                    break
            else:
                message = (
                    await websocket.receive()
                )

            message_type = (
                message.get(
                    "type"
                )
            )

            if (
                message_type
                == "websocket.disconnect"
            ):

                break

            # ====================================================
            # Binary Audio
            # ====================================================

            binary_audio = (
                message.get(
                    "bytes"
                )
            )

            if (
                binary_audio
                is not None
            ):

                if (
                    session is None
                    or vad is None
                    or hamsa_primary
                    is None
                ):

                    logger.warning(
                        "audio_received_before_"
                        "media_pipeline_ready "
                        "bytes=%d",
                        len(
                            binary_audio
                        ),
                    )

                    continue

                # ====================================================
                # Session Metrics
                # ====================================================

                session.record_audio(
                    binary_audio
                )

                # ====================================================
                # Deepgram Live Fallback
                # ====================================================

                if stt is not None:

                    try:

                        await send_or_buffer_deepgram_audio(
                            binary_audio
                        )

                    except Exception:

                        logger.error(
                            "deepgram_shadow_audio_failed "
                            "channel_id=%s "
                            "%s "
                            "stage=%s",
                            session.channel_id,
                            exception_fields(),
                            conversation_state.get("stage", "new"),
                        )

                # ====================================================
                # Hamsa Raw Audio Capture
                # ====================================================

                if (
                    session.audio_format
                    == "slin24"
                ):

                    if (
                        hamsa_utterance_active
                    ):

                        hamsa_utterance_audio.extend(
                            binary_audio
                        )

                    else:

                        hamsa_preroll.extend(
                            binary_audio
                        )

                        max_preroll_bytes = int(
                            session.sample_rate
                            * 2
                            * HAMSA_PREROLL_SECONDS
                        )

                        if (
                            len(
                                hamsa_preroll
                            )
                            > max_preroll_bytes
                        ):

                            del hamsa_preroll[
                                :-max_preroll_bytes
                            ]

                # ====================================================
                # Convert to PCM16/8k for Silero
                # ====================================================

                if (
                    session.audio_format
                    == "ulaw"
                ):

                    pcm16_audio = (
                        ulaw_to_pcm16(
                            binary_audio
                        )
                    )

                elif (
                    session.audio_format
                    == "slin24"
                ):

                    if slin24_vad_resampler is None:

                        logger.error(
                            "slin24_vad_resampler_missing "
                            "channel_id=%s",
                            session.channel_id,
                        )

                        continue

                    pcm16_audio = (
                        slin24_vad_resampler.convert(
                            binary_audio
                        )
                    )

                else:

                    logger.error(
                        "unsupported_vad_"
                        "audio_format "
                        "format=%s",
                        session.audio_format,
                    )

                    continue


                # ====================================================
                # FAST PRE-VAD BARGE-IN
                #
                # Do not wait for Silero speech_start before stopping
                # outbound TTS.
                #
                # IMPORTANT:
                # - Fast energy detection is disabled only during the
                #   tiny initial echo-prone playback window.
                # - Silero VAD ALWAYS continues to receive the frame.
                # - Terminal prompts remain non-bargeable.
                # ====================================================

                if (
                    BARGE_IN_ENABLED
                    and FAST_BARGE_IN_ENABLED
                    and conversation_state.get(
                        PLAYBACK_ACTIVE_KEY,
                        False,
                    )
                ):

                    current_stage = str(
                        conversation_state.get(
                            "stage",
                            "new",
                        )
                    )

                    if (
                        current_stage
                        not in TERMINAL_CALL_STAGES
                    ):

                        playback_started_at = (
                            conversation_state.get(
                                PLAYBACK_STARTED_AT_KEY
                            )
                        )

                        now = (
                            asyncio
                            .get_running_loop()
                            .time()
                        )

                        playback_age = 0.0
                        fast_barge_in_allowed = True

                        if playback_started_at is not None:

                            playback_age = (
                                now
                                - float(
                                    playback_started_at
                                )
                            )

                            if (
                                playback_age
                                < FAST_BARGE_IN_ECHO_PROTECTION_SECONDS
                            ):

                                fast_barge_in_allowed = False
                                fast_barge_in_active_frames = 0

                        if fast_barge_in_allowed:

                            fast_rms = (
                                calculate_pcm16_rms(
                                    pcm16_audio
                                )
                            )

                            if (
                                fast_rms
                                >= FAST_BARGE_IN_RMS_THRESHOLD
                            ):

                                fast_barge_in_active_frames += 1

                            else:

                                fast_barge_in_active_frames = 0

                            if (
                                fast_barge_in_active_frames
                                >= FAST_BARGE_IN_REQUIRED_FRAMES
                            ):

                                interrupted_correlation_id = (
                                    conversation_state.get(
                                        PLAYBACK_CORRELATION_KEY
                                    )
                                )

                                if interrupted_correlation_id:

                                    await flush_media(
                                        websocket,
                                        send_lock=media_send_lock,
                                    )

                                    # FLUSH_MEDIA does not produce
                                    # MEDIA_BUFFERING_COMPLETED.
                                    conversation_state[
                                        PLAYBACK_ACTIVE_KEY
                                    ] = False

                                    conversation_state.pop(
                                        PLAYBACK_CORRELATION_KEY,
                                        None,
                                    )

                                    conversation_state.pop(
                                        PLAYBACK_STARTED_AT_KEY,
                                        None,
                                    )

                                    conversation_state[
                                        LAST_BARGE_IN_AT_KEY
                                    ] = now

                                    fast_barge_in_active_frames = 0

                                    await cancel_barge_in_guard(
                                        reason=(
                                            "fast_energy_trigger"
                                        )
                                    )

                                    logger.info(
                                        "voice_fast_barge_in_triggered "
                                        "channel_id=%s "
                                        "stage=%s "
                                        "correlation_id=%s "
                                        "rms=%.2f "
                                        "threshold=%.2f "
                                        "frames=%d "
                                        "playback_age_ms=%d",
                                        session.channel_id,
                                        current_stage,
                                        interrupted_correlation_id,
                                        fast_rms,
                                        FAST_BARGE_IN_RMS_THRESHOLD,
                                        FAST_BARGE_IN_REQUIRED_FRAMES,
                                        int(
                                            playback_age
                                            * 1000
                                        ),
                                    )

                    else:

                        fast_barge_in_active_frames = 0

                else:

                    fast_barge_in_active_frames = 0


                # ====================================================
                # Silero VAD
                #
                # Still responsible for:
                # speech start/end
                # Hamsa capture
                # Deepgram logical utterance
                # ====================================================

                vad_events = (
                    vad.feed_pcm16(
                        pcm16_audio
                    )
                )

                # ====================================================
                # Process VAD Events
                # ====================================================

                for (
                    vad_event
                ) in (
                    vad_events
                ):

                    # ================================================
                    # Speech START
                    # ================================================

                    if (
                        "start"
                        in vad_event
                    ):

                        barge_in_speech_active = True

                        # ====================================================
                        # Potential Barge-in
                        # ====================================================

                        if (
                            BARGE_IN_ENABLED
                            and conversation_state.get(
                                PLAYBACK_ACTIVE_KEY,
                                False,
                            )
                        ):

                            current_stage = str(
                                conversation_state.get(
                                    "stage",
                                    "new",
                                )
                            )

                            active_correlation_id = (
                                conversation_state.get(
                                    PLAYBACK_CORRELATION_KEY
                                )
                            )

                            if (
                                active_correlation_id
                                and current_stage
                                not in TERMINAL_CALL_STAGES
                            ):

                                if (
                                    barge_in_guard_task
                                    is None
                                    or barge_in_guard_task.done()
                                ):

                                    barge_in_guard_task = (
                                        asyncio.create_task(
                                            run_barge_in_guard(
                                                expected_correlation_id=
                                                    str(
                                                        active_correlation_id
                                                    ),
                                            ),
                                            name=(
                                                "voice-barge-in-guard"
                                            ),
                                        )
                                    )

                                    logger.info(
                                        "voice_barge_in_candidate "
                                        "channel_id=%s "
                                        "stage=%s "
                                        "correlation_id=%s",
                                        session.channel_id,
                                        current_stage,
                                        active_correlation_id,
                                    )

                        # --------------------------------------------
                        # Cancel only pending silence grace.
                        #
                        # Do NOT cancel Hamsa worker.
                        # --------------------------------------------

                        if (
                            pending_turn_finalize_task
                            is not None
                        ):

                            await (
                                cancel_pending_turn_finalize()
                            )

                        # --------------------------------------------
                        # Start capture
                        # --------------------------------------------

                        if (
                            not hamsa_utterance_active
                        ):

                            current_stage = (
                                conversation_state.get(
                                    "stage",
                                    "new",
                                )
                            )

                            normalized_stage = (
                                current_stage
                                .strip()
                                .lower()
                            )

                            expected_digits = (
                                get_expected_digit_count(
                                    normalized_stage
                                )
                            )

                            if expected_digits is not None:

                                await cancel_pending_digit_retry_prompt(
                                    reason="speech_resumed"
                                )

                                completed_current_attempt = (
                                    digit_completed_attempt
                                    == (
                                        normalized_stage,
                                        digit_attempt_id,
                                    )
                                )

                                should_start_new_attempt = (
                                    digit_attempt_stage
                                    != normalized_stage
                                    or completed_current_attempt
                                    or digit_attempt_force_restart
                                )

                                if should_start_new_attempt:

                                    digit_attempt_id += 1

                                    digit_attempt_stage = (
                                        normalized_stage
                                    )

                                    digit_attempt_force_restart = (
                                        False
                                    )

                                    digit_completed_attempt = (
                                        None
                                    )

                                    digit_collector.reset()

                                    logger.info(
                                        "voice_digit_attempt_started "
                                        "channel_id=%s "
                                        "stage=%s "
                                        "attempt_id=%d "
                                        "expected=%d",
                                        session.channel_id,
                                        normalized_stage,
                                        digit_attempt_id,
                                        expected_digits,
                                    )

                                else:

                                    logger.info(
                                        "voice_digit_attempt_resumed "
                                        "channel_id=%s "
                                        "stage=%s "
                                        "attempt_id=%d "
                                        "expected=%d",
                                        session.channel_id,
                                        normalized_stage,
                                        digit_attempt_id,
                                        expected_digits,
                                    )

                            hamsa_utterance_audio.clear()

                            hamsa_utterance_audio.extend(
                                hamsa_preroll
                            )

                            hamsa_preroll.clear()

                            hamsa_utterance_active = (
                                True
                            )

                        # --------------------------------------------
                        # Deepgram shadow logical utterance
                        # --------------------------------------------

                        if stt is not None:

                            if deepgram_shadow_ready:

                                stt.begin_utterance()

                            else:

                                pending_deepgram_utterance_start = True

                                logger.info(
                                    "deepgram_utterance_start_deferred_until_ready "
                                    "channel_id=%s",
                                    session.channel_id,
                                )

                        logger.info(
                            "vad_speech_started "
                            "connection_id=%s "
                            "sample=%s "
                            "stage=%s",
                            session.connection_id,
                            vad_event[
                                "start"
                            ],
                            conversation_state.get(
                                "stage",
                                "new",
                            ),
                        )

                    # ================================================
                    # Speech END
                    # ================================================

                    if (
                        "end"
                        in vad_event
                    ):
                        barge_in_speech_active = False

                        await cancel_barge_in_guard(
                            reason="speech_ended"
                        )

                        logger.info(
                            "vad_speech_ended "
                            "connection_id=%s "
                            "sample=%s "
                            "stage=%s",
                            session.connection_id,
                            vad_event[
                                "end"
                            ],
                            conversation_state.get(
                                "stage",
                                "new",
                            ),
                        )

                        if (
                            pending_turn_finalize_task
                            is None
                            or (
                                pending_turn_finalize_task
                                .done()
                            )
                        ):

                            pending_turn_finalize_task = (
                                asyncio.create_task(
                                    finalize_after_turn_grace(),
                                    name=(
                                        "voice-turn-"
                                        "finalize-grace"
                                    ),
                                )
                            )

                # ====================================================
                # HARD SPLIT CHECK
                #
                # Run AFTER VAD events.
                #
                # If Silero naturally ended this frame,
                # natural silence handling wins.
                # ====================================================

                await (
                    maybe_split_long_digit_utterance(
                        vad_events=(
                            vad_events
                        ),
                    )
                )

                continue

            # ====================================================
            # Asterisk JSON Control Message
            # ====================================================

            control_message = (
                message.get(
                    "text"
                )
            )

            if (
                control_message
                is None
            ):

                continue

            logger.info(
                "asterisk_control_received "
                "message_chars=%d",
                len(control_message),
            )

            try:

                event = (
                    json.loads(
                        control_message
                    )
                )

            except json.JSONDecodeError:

                logger.warning(
                    "invalid_asterisk_"
                    "control_json "
                    "message_chars=%d",
                    len(control_message),
                )

                continue

            # ====================================================
            # MEDIA_BUFFERING_COMPLETED
            #
            # If this correlation id belongs to a terminal reply,
            # the caller has heard the complete final message.
            # Now it is safe to close the media websocket.
            # Asterisk Dial(WebSocket/...) will return and the
            # dialplan Hangup() will end the phone call.
            # ====================================================

            if (
                event.get(
                    "event"
                )
                == "MEDIA_BUFFERING_COMPLETED"
            ):

                completed_correlation_id = str(
                    event.get(
                        "correlation_id",
                        "",
                    )
                )

                # ====================================================
                # Normal playback completion.
                # ====================================================

                active_playback_correlation_id = (
                    conversation_state.get(
                        PLAYBACK_CORRELATION_KEY
                    )
                )

                if (
                    active_playback_correlation_id
                    and
                    completed_correlation_id
                    == str(
                        active_playback_correlation_id
                    )
                ):

                    conversation_state[
                        PLAYBACK_ACTIVE_KEY
                    ] = False

                    conversation_state.pop(
                        PLAYBACK_CORRELATION_KEY,
                        None,
                    )

                    conversation_state.pop(
                        PLAYBACK_STARTED_AT_KEY,
                        None,
                    )

                    logger.info(
                        "voice_playback_completed "
                        "channel_id=%s "
                        "correlation_id=%s",
                        (
                            session.channel_id
                            if session is not None
                            else "unknown"
                        ),
                        completed_correlation_id,
                    )

                pending_correlation_id = (
                    conversation_state.get(
                        PENDING_HANGUP_CORRELATION_KEY
                    )
                )

                pending_terminal_stage = (
                    conversation_state.get(
                        PENDING_HANGUP_STAGE_KEY
                    )
                )

                if (
                    pending_correlation_id
                    and completed_correlation_id
                    == pending_correlation_id
                ):

                    logger.info(
                        "voice_terminal_playback_completed "
                        "channel_id=%s "
                        "stage=%s "
                        "correlation_id=%s "
                        "action=close_call",
                        (
                            session.channel_id
                            if session is not None
                            else "unknown"
                        ),
                        pending_terminal_stage,
                        completed_correlation_id,
                    )

                    conversation_state.pop(
                        PENDING_HANGUP_CORRELATION_KEY,
                        None,
                    )

                    conversation_state.pop(
                        PENDING_HANGUP_STAGE_KEY,
                        None,
                    )

                    try:

                        await websocket.close(
                            code=1000,
                            reason=(
                                "terminal_stage_completed"
                            ),
                        )

                    except Exception:

                        logger.exception(
                            "voice_terminal_websocket_close_failed "
                            "channel_id=%s "
                            "stage=%s",
                            (
                                session.channel_id
                                if session is not None
                                else "unknown"
                            ),
                            pending_terminal_stage,
                        )

                    break

                continue

            # ====================================================
            # MEDIA_START
            # ====================================================

            if (
                event.get(
                    "event"
                )
                == "MEDIA_START"
            ):

                try:
                    media_authorization = (
                        authorize_media_start(
                            event
                        )
                    )
                except MediaAuthError as exc:
                    logger.warning(
                        "media_auth_rejected "
                        "reason=%s "
                        "client=%s",
                        exc.reason,
                        client,
                    )
                    await websocket.close(
                        code=POLICY_VIOLATION_CLOSE_CODE
                    )
                    break

                audio_format = (
                    str(
                        event.get(
                            "format",
                            "",
                        )
                    )
                    .lower()
                )

                if (
                    audio_format
                    not in {
                        "ulaw",
                        "slin24",
                    }
                ):

                    logger.error(
                        "unsupported_audio_format "
                        "format=%s",
                        audio_format,
                    )

                    continue
                # ====================================================
                # Audio Parameters
                # ====================================================

                if (
                    audio_format
                    == "ulaw"
                ):

                    sample_rate = (
                        8000
                    )

                    default_frame_size = (
                        160
                    )

                    deepgram_encoding = (
                        "mulaw"
                    )

                    deepgram_sample_rate = (
                        8000
                    )

                else:

                    sample_rate = (
                        24000
                    )

                    default_frame_size = (
                        960
                    )

                    deepgram_encoding = (
                        "linear16"
                    )

                    deepgram_sample_rate = (
                        24000
                    )

                # ====================================================
                # Session
                # ====================================================

                session = (
                    VoiceSession(
                        connection_id=str(
                            event[
                                "connection_id"
                            ]
                        ),
                        channel_id=str(
                            event[
                                "channel_id"
                            ]
                        ),
                        channel=str(
                            event[
                                "channel"
                            ]
                        ),
                        audio_format=(
                            audio_format
                        ),
                        sample_rate=(
                            sample_rate
                        ),
                        optimal_frame_size=int(
                            event.get(
                                "optimal_frame_size",
                                default_frame_size,
                            )
                        ),
                        ptime_ms=int(
                            event.get(
                                "ptime",
                                20,
                            )
                        ),
                    )
                )

                channel_variables = (
                    event.get(
                        "channel_variables"
                    )
                    or {}
                )

                raw_tenant_id = (
                    channel_variables.get(
                        "MEDMIND_TENANT_ID"
                    )
                )

                if raw_tenant_id is not None:

                    candidate_tenant_id = (
                        str(
                            raw_tenant_id
                        )
                        .strip()
                    )

                    if candidate_tenant_id:

                        call_tenant_id = (
                            candidate_tenant_id
                        )

                        logger.info(
                            "voice_tenant_received "
                            "channel_id=%s "
                            "source=asterisk "
                            "tenant_id=%s",
                            session.channel_id,
                            call_tenant_id,
                        )

                # ====================================================
                # VAD
                # ====================================================

                vad = (
                    StreamingVAD()
                )

                if (
                    session.audio_format
                    == "slin24"
                ):

                    slin24_vad_resampler = (
                        create_slin24_vad_resampler()
                    )

                # ====================================================
                # Queues
                # ====================================================

                transcript_queue = (
                    asyncio.Queue()
                )

                hamsa_work_queue = (
                    asyncio.Queue()
                )

                # ====================================================
                # Deepgram Callback
                # ====================================================

                def on_deepgram_shadow_transcript(
                    transcript: str,
                    is_final: bool,
                    owner: Any,
                ) -> None:

                    if not is_final:

                        return

                    if (
                        not isinstance(
                            owner,
                            tuple,
                        )
                        or len(owner) != 3
                    ):

                        logger.warning(
                            "deepgram_final_missing_owner "
                            "channel_id=%s "
                            "action=ignore",
                            session.channel_id,
                        )

                        return

                    (
                        candidate_turn,
                        stage_snapshot,
                        attempt_snapshot,
                    ) = owner    

                    transcript = (
                        transcript.strip()
                    )

                    if not transcript:

                        return

                    expected_digits = (
                        get_expected_digit_count(
                            stage_snapshot
                        )
                    )

                    if expected_digits is not None:

                        current_digit_stage = (
                            digit_attempt_stage
                        )

                        if (
                            current_digit_stage
                            != stage_snapshot
                        ):

                            logger.info(
                                "deepgram_stale_stage_transcript_ignored "
                                "channel_id=%s "
                                "current_stage=%s "
                                "digit_attempt_stage=%s",
                                session.channel_id,
                                stage_snapshot,
                                current_digit_stage,
                            )

                            return

                    if expected_digits is not None:

                        detected_digits = (
                            extract_spoken_digits(
                                transcript
                            )
                        )

                        detected_count = len(
                            detected_digits
                        )

                        # No digit evidence:
                        # this may be a genuine side question.
                        if detected_count == 0:

                            return

                        # Partial digit result.
                        # Never route it to the backend as conversation.
                        if detected_count < expected_digits:

                            logger.info(
                                "deepgram_digit_partial_ignored "
                                "channel_id=%s "
                                "stage=%s "
                                "attempt_id=%d "
                                "digits_detected=%d "
                                "expected=%d",
                                session.channel_id,
                                stage_snapshot,
                                attempt_snapshot,
                                detected_count,
                                expected_digits,
                            )

                            return

                        # Too many digits also must not win.
                        if detected_count > expected_digits:

                            logger.info(
                                "deepgram_digit_overflow_ignored "
                                "channel_id=%s "
                                "stage=%s "
                                "attempt_id=%d "
                                "digits_detected=%d "
                                "expected=%d",
                                session.channel_id,
                                stage_snapshot,
                                attempt_snapshot,
                                detected_count,
                                expected_digits,
                            )

                            return

                        if not is_valid_digit_candidate_for_stage(
                            stage=stage_snapshot,
                            digits=detected_digits,
                        ):

                            logger.info(
                                "deepgram_digit_candidate_rejected "
                                "channel_id=%s "
                                "stage=%s "
                                "attempt_id=%d "
                                "reason=stage_validation",
                                session.channel_id,
                                stage_snapshot,
                                attempt_snapshot,
                            )

                            return

                        def schedule_digit_candidate() -> None:

                            asyncio.create_task(
                                complete_digit_attempt(
                                    provider="deepgram",
                                    stage=stage_snapshot,
                                    attempt_id=attempt_snapshot,
                                    digits=detected_digits,
                                    turn_number=None,
                                )
                            )

                        event_loop.call_soon_threadsafe(
                            schedule_digit_candidate
                        )

                        return
                    
                    candidate_transcript = (
                        transcript
                    )


                    def store_normal_candidate() -> None:

                        if (
                            candidate_turn <= 0
                            or candidate_turn
                            in closed_normal_turns
                        ):

                            return

                        deepgram_normal_candidates[
                            candidate_turn
                        ] = (
                            candidate_transcript
                        )

                        candidate_event = (
                            deepgram_normal_candidate_events.get(
                                candidate_turn
                            )
                        )

                        if candidate_event is not None:

                            candidate_event.set()

                        logger.info(
                            "deepgram_normal_fallback_candidate "
                            "channel_id=%s "
                            "turn=%d "
                            "stage=%s "
                            "transcript_chars=%d",
                            session.channel_id,
                            candidate_turn,
                            stage_snapshot,
                            len(candidate_transcript),
                        )

                    event_loop.call_soon_threadsafe(
                        store_normal_candidate
                    )

                # ====================================================
                # Tenant
                # ====================================================

                # Chosen and allow-listed in authorize_media_start():
                # MEDMIND_TENANT_ID channel variable, else VOICE_TENANT_ID,
                # and always one of VOICE_ALLOWED_TENANT_IDS. No hard-coded
                # fallback: an unknown tenant never reaches this point.
                tenant_id = (
                    media_authorization.tenant_id
                )

                tenant_source = (
                    media_authorization.tenant_source
                )

                logger.info(
                    "voice_tenant_selected "
                    "channel_id=%s "
                    "tenant_id=%s "
                    "source=%s",
                    session.channel_id,
                    tenant_id,
                    tenant_source,
                )

                # ====================================================
                # STT Configuration
                # ====================================================

                primary_stt_name = (
                    os.getenv(
                        "VOICE_STT_PRIMARY",
                        "hamsa",
                    )
                    .strip()
                    .lower()
                )

                shadow_stt_name = (
                    os.getenv(
                        "VOICE_STT_SHADOW",
                        "deepgram",
                    )
                    .strip()
                    .lower()
                )

                logger.info(
                    "voice_stt_configuration "
                    "channel_id=%s "
                    "primary=%s "
                    "shadow=%s",
                    session.channel_id,
                    primary_stt_name,
                    shadow_stt_name,
                )

                if (
                    primary_stt_name
                    != "hamsa"
                ):

                    raise RuntimeError(
                        "Production voice runtime "
                        "requires "
                        "VOICE_STT_PRIMARY=hamsa"
                    )

                if (
                    shadow_stt_name
                    != "deepgram"
                ):

                    raise RuntimeError(
                        "Production voice runtime "
                        "requires "
                        "VOICE_STT_SHADOW=deepgram"
                    )

                if (
                    session.audio_format
                    != "slin24"
                ):

                    raise RuntimeError(
                        "Hamsa primary currently "
                        "requires "
                        "Asterisk format=slin24"
                    )

                # ====================================================
                # Hamsa PRIMARY
                # ====================================================

                hamsa_primary = (
                    HamsaSTT(
                        sample_rate=24000,
                        language="ar",
                        model="s3",
                    )
                )

                # ====================================================
                # Deepgram LIVE FALLBACK
                # ====================================================

                stt_language = (
                    os.getenv(
                        "VOICE_STT_LANGUAGE",
                        "ar-EG",
                    )
                )

                stt = (
                    DeepgramStreamingSTT(
                        language=(
                            stt_language
                        ),
                        encoding=(
                            deepgram_encoding
                        ),
                        sample_rate=(
                            deepgram_sample_rate
                        ),
                        on_transcript_with_owner=(
                            on_deepgram_shadow_transcript
                        ),
                    )
                )

                # ====================================================
                # Start production STT providers concurrently
                # ====================================================

                deepgram_start_task = (
                    asyncio.create_task(
                        start_deepgram_shadow(
                            stt,
                            channel_id=(
                                session.channel_id
                            ),
                            connection_id=(
                                session.connection_id
                            ),
                            language=(
                                stt_language
                            ),
                            encoding=(
                                deepgram_encoding
                            ),
                            sample_rate=(
                                deepgram_sample_rate
                            ),
                        ),
                        name=(
                            "deepgram-shadow-start-"
                            f"{session.channel_id}"
                        ),
                    )
                )

                hamsa_preconnect_task = (
                    asyncio.create_task(
                        start_hamsa_primary(
                            hamsa_primary,
                            channel_id=(
                                session.channel_id
                            ),
                        ),
                        name=(
                            "hamsa-primary-start-"
                            f"{session.channel_id}"
                        ),
                    )
                )

                # ====================================================
                # SINGLE Hamsa Worker
                # ====================================================

                hamsa_worker_task = (
                    asyncio.create_task(
                        hamsa_worker(),
                        name=(
                            "hamsa-worker-"
                            f"{session.channel_id}"
                        ),
                    )
                )

                # ====================================================
                # MedMind / TTS Consumer
                # ====================================================

                transcript_consumer_task = (
                    asyncio.create_task(
                        consume_final_transcripts(
                            transcript_queue,
                            websocket=websocket,
                            channel_id=session.channel_id,
                            tenant_id=tenant_id,
                            audio_format=session.audio_format,
                            conversation_state=conversation_state,
                            media_send_lock=media_send_lock,
                        ),
                        name=(
                            "voice-transcript-"
                            f"{session.channel_id}"
                        ),
                    )
                )

                def log_transcript_consumer_result(
                    task: asyncio.Task,
                ) -> None:

                    if task.cancelled():
                        return

                    try:

                        exception = (
                            task.exception()
                        )

                    except asyncio.CancelledError:

                        return

                    if exception is not None:

                        # Class, code and source location only: the
                        # message or traceback may quote caller speech.
                        logger.error(
                            "voice_transcript_consumer_crashed "
                            "channel_id=%s "
                            "%s "
                            "stage=%s",
                            session.channel_id,
                            exception_fields(
                                exception
                            ),
                            conversation_state.get("stage", "new"),
                        )


                transcript_consumer_task.add_done_callback(
                    log_transcript_consumer_result
                )

                # ====================================================
                # Optional Test Transcript
                # ====================================================

                test_transcript = (
                    os.getenv(
                        "VOICE_TEST_TRANSCRIPT"
                    )
                )

                if (
                    test_transcript
                ):

                    await (
                        transcript_queue.put(
                            test_transcript
                        )
                    )

                    logger.info(
                        "voice_test_transcript_injected "
                        "channel_id=%s "
                        "transcript_chars=%d",
                        session.channel_id,
                        len(test_transcript),
                    )

                # ====================================================
                # Ready
                # ====================================================

                logger.info(
                    "voice_session_started "
                    "connection_id=%s "
                    "channel_id=%s "
                    "format=%s "
                    "sample_rate=%d "
                    "frame_size=%d "
                    "ptime_ms=%d",
                    session.connection_id,
                    session.channel_id,
                    session.audio_format,
                    session.sample_rate,
                    session.optimal_frame_size,
                    session.ptime_ms,
                )

                logger.info(
                    "vad_ready "
                    "connection_id=%s "
                    "sample_rate=%d",
                    session.connection_id,
                    8000,
                )

                logger.info(
                    "hamsa_worker_ready "
                    "channel_id=%s "
                    "mode=single_serial_worker "
                    "digit_max_utterance_seconds=%.2f",
                    session.channel_id,
                    DIGIT_MAX_UTTERANCE_SECONDS,
                )

    except WebSocketDisconnect:

        logger.info(
            "asterisk_websocket_disconnected "
            "client=%s",
            client,
        )

    except Exception:

        logger.exception(
            "asterisk_websocket_error "
            "client=%s",
            client,
        )

        raise

    finally:
        # ====================================================
        # Stop Barge-in Guard
        # ====================================================

        try:

            barge_in_speech_active = False

            await cancel_barge_in_guard(
                reason="session_shutdown"
            )

        except Exception:

            logger.error(
                "barge_in_guard_shutdown_error "
                "%s "
                "stage=%s",
                exception_fields(),
                conversation_state.get("stage", "new")
            )
        # ====================================================
        # Stop Digit Retry Timer
        # ====================================================

        try:

            await cancel_pending_digit_retry_prompt(
                reason="session_shutdown"
            )

        except Exception:

            logger.error(
                "digit_retry_timer_shutdown_error "
                "%s "
                "stage=%s",
                exception_fields(),
                conversation_state.get("stage", "new")
            )

        # ====================================================
        # Stop Grace Timer
        # ====================================================

        try:

            await (
                cancel_pending_turn_finalize()
            )

        except Exception:

            logger.error(
                "turn_finalize_grace_"
                "shutdown_error "
                "%s "
                "stage=%s",
                exception_fields(),
                conversation_state.get("stage", "new")
            )

        # ====================================================
        # Stop Deepgram Startup
        # ====================================================

        if (
            deepgram_start_task
            is not None
            and not deepgram_start_task.done()
        ):

            deepgram_start_task.cancel()

            await asyncio.gather(
                deepgram_start_task,
                return_exceptions=True,
            )

        # ====================================================
        # Stop Hamsa Preconnect
        # ====================================================

        if (
            hamsa_preconnect_task
            is not None
            and not hamsa_preconnect_task.done()
        ):

            hamsa_preconnect_task.cancel()

            await asyncio.gather(
                hamsa_preconnect_task,
                return_exceptions=True,
            )
            
        # ====================================================
        # Stop Deepgram Finalize Tasks
        # ====================================================

        if (
            deepgram_finalize_tasks
        ):

            for (
                task
            ) in list(
                deepgram_finalize_tasks
            ):

                if (
                    not task.done()
                ):

                    task.cancel()

            await asyncio.gather(
                *deepgram_finalize_tasks,
                return_exceptions=True,
            )

        # ====================================================
        # Close Deepgram
        # ====================================================

        if (
            stt is not None
        ):

            try:

                await (
                    stt.close()
                )

            except Exception:

                logger.error(
                    "deepgram_fallback_shutdown_error "
                    "%s "
                    "stage=%s",
                    exception_fields(),
                    conversation_state.get("stage", "new")
                )

        # ====================================================
        # Stop Hamsa Worker
        # ====================================================

        if (
            hamsa_worker_task
            is not None
        ):

            hamsa_worker_task.cancel()

            await asyncio.gather(
                hamsa_worker_task,
                return_exceptions=True,
            )

        # ====================================================
        # Drain Background Hamsa Requests
        # ====================================================

        if hamsa_drain_tasks:

            pending_hamsa_drains = list(
                hamsa_drain_tasks
            )

            try:

                await asyncio.wait_for(
                    asyncio.gather(
                        *pending_hamsa_drains,
                        return_exceptions=True,
                    ),
                    timeout=2.0,
                )

            except asyncio.TimeoutError:

                logger.warning(
                    "hamsa_drain_shutdown_timeout "
                    "pending=%d",
                    len(
                        [
                            task
                            for task
                            in pending_hamsa_drains
                            if not task.done()
                        ]
                    ),
                )    

        # ====================================================
        # Close Hamsa Persistent STT Connection
        # ====================================================

        if (
            hamsa_primary
            is not None
        ):

            try:

                await (
                    hamsa_primary.close()
                )

            except Exception:

                logger.error(
                    "hamsa_primary_shutdown_error "
                    "%s "
                    "stage=%s",
                    exception_fields(),
                    conversation_state.get("stage", "new")
                )    

        # ====================================================
        # Drain MedMind Queue
        # ====================================================

        if (
            transcript_queue
            is not None
        ):

            try:

                await asyncio.wait_for(
                    transcript_queue.join(),
                    timeout=30.0,
                )

            except TimeoutError:

                logger.warning(
                    "transcript_queue_"
                    "drain_timeout"
                )

        # ====================================================
        # Stop MedMind Consumer
        # ====================================================

        if (
            transcript_consumer_task
            is not None
        ):

            transcript_consumer_task.cancel()

            await asyncio.gather(
                transcript_consumer_task,
                return_exceptions=True,
            )

        # ========================================================
        # Post-call processing
        #
        # Only for an authenticated call, and only with the tenant
        # verified by authorize_media_start(). A rejected or
        # unauthenticated connection has no verified tenant (and no
        # armed event), so it never reaches the post-call client.
        # ========================================================

        if media_authorization is not None:

            post_call_client = (
                PostCallClient()
            )

            try:

                await dispatch_post_call_event(
                    conversation_state=
                        conversation_state,

                    tenant_id=
                        media_authorization.tenant_id,

                    channel_id=(
                        session.channel_id
                        if session is not None
                        else "unknown"
                    ),

                    client=
                        post_call_client,
                )

            finally:

                await (
                    post_call_client.close()
                )
        # ====================================================
        # Reset VAD
        # ====================================================

        if (
            vad is not None
        ):

            vad.reset()

        if (
            slin24_vad_resampler
            is not None
        ):

            slin24_vad_resampler.reset()    

        # ====================================================
        # Final Session Metrics
        # ====================================================

        if (
            session is not None
        ):

            logger.info(
                "voice_session_closed "
                "connection_id=%s "
                "frames=%d "
                "bytes=%d "
                "duration_seconds=%.2f",
                session.connection_id,
                session.frames_received,
                session.bytes_received,
                session.audio_duration_seconds,
            )

        logger.info(
            "asterisk_media_session_closed "
            "client=%s",
            client,
        )
