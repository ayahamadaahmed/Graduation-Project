from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import unicodedata
import wave
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from voice_gateway.audio.codec import (
    pcm16_24k_to_ulaw8k,
    slin24_to_pcm16_8k,
    ulaw_to_pcm16,
)
from voice_gateway.audio.vad import StreamingVAD
from voice_gateway.config import load_environment
from voice_gateway.medmind_client import MedMindClient
from voice_gateway.providers.deepgram_stt import DeepgramStreamingSTT
from voice_gateway.providers.elevenlabs_tts import ElevenLabsTTS
from voice_gateway.providers.gemini_tts import GeminiTTS
from voice_gateway.providers.hamsa_stt import HamsaSTT
from voice_gateway.session import VoiceSession
from voice_gateway.transport.asterisk_media import (
    send_media_audio,
    send_media_chunk,
    start_media_buffering,
    stop_media_buffering,
)


# ============================================================
# Environment
# ============================================================

load_environment()


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

DEFAULT_TURN_END_GRACE_SECONDS = 0.50

DIGIT_TURN_END_GRACE_SECONDS = 0.30


# Maximum continuous audio that Hamsa receives while
# collecting long digit sequences.
#
# Example:
#
# User says:
# 1 2 3 4 5 6 7 8 9 1 2 3 4 5
#
# We do NOT wait for all 14 digits in one WAV.
#
# Instead:
#
# ~4 sec -> Hamsa chunk 1
# ~4 sec -> Hamsa chunk 2
#
# DigitCollector joins the transcripts.
DIGIT_MAX_UTTERANCE_SECONDS = 4.0


# Small amount of audio before Silero speech_start.
#
# This prevents clipping the first syllable / first digit.
HAMSA_PREROLL_SECONDS = 0.25
HAMSA_NORMAL_SOFT_TIMEOUT_SECONDS = float(
    os.getenv(
        "VOICE_HAMSA_NORMAL_SOFT_TIMEOUT_SECONDS",
        "3.0",
    )
)
HAMSA_DIGIT_SOFT_TIMEOUT_SECONDS = float(
    os.getenv(
        "VOICE_HAMSA_DIGIT_SOFT_TIMEOUT_SECONDS",
        "3.0",
    )
)
DEEPGRAM_NORMAL_FALLBACK_WAIT_SECONDS = float(
    os.getenv(
        "VOICE_DEEPGRAM_NORMAL_FALLBACK_WAIT_SECONDS",
        "1.0",
    )
)

# Caller may pause briefly while reading a long number.
# If no more speech arrives before this timer expires,
# ask for the whole number again instead of staying silent.
DIGIT_INCOMPLETE_RETRY_SECONDS = float(
    os.getenv(
        "VOICE_DIGIT_INCOMPLETE_RETRY_SECONDS",
        "3.0",
    )
)

# Internal queue marker for TTS-only prompts that must not
# be sent to the MedMind backend.
LOCAL_TTS_PREFIX = "__MEDMIND_LOCAL_TTS__::"

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


def get_turn_end_grace_seconds(
    stage: str | None,
) -> float:

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

    return "".join(
        digits
    )


# ============================================================
# Digit Collector
# ============================================================

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
            "elevenlabs",
        )
        .strip()
        .lower()
    )

    if (
        provider_name
        == "elevenlabs"
    ):

        provider = (
            ElevenLabsTTS()
        )

    elif (
        provider_name
        == "gemini"
    ):

        provider = (
            GeminiTTS(
                voice="Kore",
            )
        )

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
        str,
    ],
) -> None:

    medmind = (
        MedMindClient()
    )

    (
        tts_provider_name,
        tts,
    ) = (
        create_tts_provider()
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

    session_id = (
        f"voice-{channel_id}"
    )

    try:

        while True:

            transcript = (
                await transcript_queue.get()
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

                    logger.info(
                        "voice_final_transcript_received "
                        "channel_id=%s "
                        "stage=%s "
                        "sensitive=true "
                        "digits=%d",
                        channel_id,
                        current_stage,
                        digit_count,
                    )

                else:

                    logger.info(
                        "voice_final_transcript_received "
                        "channel_id=%s "
                        "stage=%s "
                        "text=%s",
                        channel_id,
                        current_stage,
                        transcript,
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
                            )
                        )

                    except Exception:

                        logger.exception(
                            "voice_medmind_request_failed "
                            "channel_id=%s",
                            channel_id,
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
                        "reply=%s",
                        channel_id,
                        result.get(
                            "stage"
                        ),
                        reply,
                    )

                else:

                    logger.info(
                        "voice_medmind_reply "
                        "channel_id=%s "
                        "intent=%s "
                        "stage=%s "
                        "language=%s "
                        "reply=%s",
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
                        reply,
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
                # True ElevenLabs Streaming
                # ====================================================

                use_true_streaming = (
                    tts_provider_name
                    == "elevenlabs"
                    and audio_format
                    == "slin24"
                    and tts_streaming_enabled
                )

                if (
                    use_true_streaming
                ):

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

                    stream_started_at = (
                        asyncio
                        .get_running_loop()
                        .time()
                    )

                    try:

                        logger.info(
                            "voice_tts_stream_started "
                            "channel_id=%s "
                            "provider=elevenlabs "
                            "format=%s",
                            channel_id,
                            audio_format,
                        )

                        await (
                            start_media_buffering(
                                websocket
                            )
                        )

                        buffering_started = (
                            True
                        )

                        async for (
                            audio_chunk
                        ) in (
                            tts.stream_pcm24k(
                                reply
                            )
                        ):

                            if (
                                not audio_chunk
                            ):

                                continue

                            await (
                                send_media_chunk(
                                    websocket,
                                    audio_chunk,
                                )
                            )

                            audio_chunks += (
                                1
                            )

                            total_audio_bytes += (
                                len(
                                    audio_chunk
                                )
                            )

                        correlation_id = (
                            await (
                                stop_media_buffering(
                                    websocket
                                )
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
                            "provider=elevenlabs "
                            "format=%s "
                            "chunks=%d "
                            "bytes=%d "
                            "elapsed_ms=%.2f "
                            "correlation_id=%s",
                            channel_id,
                            audio_format,
                            audio_chunks,
                            total_audio_bytes,
                            elapsed_ms,
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

                    except Exception as exc:

                        logger.exception(
                            "voice_tts_stream_failed "
                            "channel_id=%s "
                            "provider=elevenlabs "
                            "error_type=%s",
                            channel_id,
                            type(
                                exc
                            ).__name__,
                        )

                        if (
                            buffering_started
                            and not buffering_stopped
                        ):

                            try:

                                await (
                                    stop_media_buffering(
                                        websocket
                                    )
                                )

                            except Exception:

                                logger.exception(
                                    "voice_tts_stream_"
                                    "buffer_stop_failed "
                                    "channel_id=%s",
                                    channel_id,
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
                                reply,
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
                                    reply,
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
                                    reply,
                                )
                            )

                    else:

                        raise RuntimeError(
                            "Unsupported outbound "
                            "audio format: "
                            f"{audio_format}"
                        )

                except Exception as exc:

                    logger.exception(
                        "voice_tts_failed "
                        "channel_id=%s "
                        "provider=%s "
                        "error_type=%s",
                        channel_id,
                        tts_provider_name,
                        type(
                            exc
                        ).__name__,
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
                        )
                    )

                except Exception as exc:

                    logger.exception(
                        "voice_audio_send_failed "
                        "channel_id=%s "
                        "provider=%s "
                        "error_type=%s",
                        channel_id,
                        tts_provider_name,
                        type(
                            exc
                        ).__name__,
                    )

                    continue

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
        # Close MedMind
        # ====================================================

        try:

            await medmind.close()

        except Exception:

            logger.exception(
                "medmind_client_shutdown_error"
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

                logger.exception(
                    "voice_tts_async_provider_"
                    "shutdown_error "
                    "provider=%s",
                    tts_provider_name,
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

                logger.exception(
                    "voice_tts_provider_"
                    "shutdown_error "
                    "provider=%s",
                    tts_provider_name,
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

    # ========================================================
    # Session / VAD
    # ========================================================

    session: (
        VoiceSession
        | None
    ) = None

    vad: (
        StreamingVAD
        | None
    ) = None

    # ========================================================
    # STT Providers
    #
    # Hamsa:
    #   PRIMARY
    #
    # Deepgram:
    #   SHADOW
    # ========================================================

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

    # ========================================================
    # Hamsa Work Queue
    #
    # IMPORTANT:
    #
    # Old:
    #
    # Turn 1 -> Hamsa task
    # Turn 2 -> Hamsa task
    # Turn 3 -> Hamsa task
    #
    # Could run simultaneously.
    #
    # New:
    #
    # Turns -> Queue -> ONE Hamsa Worker
    #
    # Only one Hamsa request runs at a time.
    # ========================================================

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

    deepgram_start_task: (
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

    # ========================================================
    # Conversation State
    # ========================================================

    conversation_state: dict[
        str,
        str,
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
    # ========================================================
    # Debug WAV
    # ========================================================

    debug_wav: (
        wave.Wave_write
        | None
    ) = None

    debug_wav_path: (
        Path
        | None
    ) = None

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

        try:

            logger.info(
                "deepgram_shadow_starting "
                "channel_id=%s",
                channel_id,
            )

            await (
                shadow_stt.start()
            )

            deepgram_shadow_ready = (
                True
            )

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

            logger.exception(
                "deepgram_shadow_start_failed "
                "channel_id=%s",
                channel_id,
            )

    # ========================================================
    # Deepgram Finalize
    # ========================================================

    async def finalize_deepgram_shadow_turn(
        channel_id: str,
    ) -> None:

        if (
            stt is None
            or not deepgram_shadow_ready
        ):

            return

        try:

            await (
                stt.finalize()
            )

        except asyncio.CancelledError:

            raise

        except Exception:

            logger.exception(
                "deepgram_shadow_finalize_failed "
                "channel_id=%s",
                channel_id,
            )

    def schedule_deepgram_finalize(
        channel_id: str,
    ) -> None:

        if (
            stt is None
            or not deepgram_shadow_ready
        ):

            return

        task = (
            asyncio.create_task(
                finalize_deepgram_shadow_turn(
                    channel_id
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

                            transcript = (
                                await asyncio.wait_for(
                                    hamsa_primary.transcribe(
                                        audio,
                                        eos_enabled=eos_enabled,
                                        sensitive=False,
                                    ),
                                    timeout=(
                                        HAMSA_NORMAL_SOFT_TIMEOUT_SECONDS
                                    ),
                                )
                            )

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

                    # ====================================================
                    # Digit stage:
                    #
                    # Keep the existing Hamsa digit behavior.
                    # Deepgram competes through Digit Arbitration.
                    # ====================================================

                    else:

                        try:

                            transcript = (
                                await asyncio.wait_for(
                                    hamsa_primary.transcribe(
                                        audio,
                                        eos_enabled=eos_enabled,
                                        sensitive=True,
                                    ),
                                    timeout=(
                                        HAMSA_DIGIT_SOFT_TIMEOUT_SECONDS
                                    ),
                                )
                            )

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

                    logger.exception(
                        "hamsa_primary_processing_failed "
                        "channel_id=%s "
                        "turn=%d",
                        (
                            session.channel_id
                            if session is not None
                            else "unknown"
                        ),
                        turn_number,
                    )

                    transcript = ""

                transcript = (
                    transcript.strip()
                )

                if (
                    expected_digits is None
                    and not is_valid_stt_transcript(
                        transcript
                    )
                ):

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

                        digit_attempt_force_restart = True

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

                if transcript_queue is not None:

                    transcript_queue.put_nowait(
                        transcript
                    )

                logger.info(
                    "hamsa_primary_transcript_queued "
                    "channel_id=%s "
                    "turn=%d "
                    "text=%s",
                    (
                        session.channel_id
                        if session is not None
                        else "unknown"
                    ),
                    turn_number,
                    transcript,
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
                session.channel_id
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

            expected_digits = (
                get_expected_digit_count(
                    current_stage
                )
            )

            if (
                turn_number is not None
                and expected_digits is not None
            ):

                schedule_digit_incomplete_retry(
                    stage=current_stage,
                    attempt_id=digit_attempt_id,
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

    # ========================================================
    # Main WebSocket Loop
    # ========================================================

    try:

        while True:

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
                # Debug WAV
                # ====================================================

                if (
                    debug_wav
                    is not None
                ):

                    debug_wav.writeframesraw(
                        binary_audio
                    )

                # ====================================================
                # Deepgram Shadow
                # ====================================================

                if (
                    stt is not None
                    and deepgram_shadow_ready
                ):

                    try:

                        await (
                            stt.send_audio(
                                binary_audio
                            )
                        )

                    except Exception:

                        logger.exception(
                            "deepgram_shadow_audio_failed "
                            "channel_id=%s",
                            session.channel_id,
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

                    pcm16_audio = (
                        slin24_to_pcm16_8k(
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

                        if (
                            stt is not None
                            and deepgram_shadow_ready
                        ):

                            stt.begin_utterance()

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
                "message=%s",
                control_message,
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
                    "message=%s",
                    control_message,
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

                # ====================================================
                # Debug Recording
                # ====================================================

                if (
                    os.getenv(
                        "VOICE_DEBUG_RECORD_AUDIO",
                        "0",
                    )
                    == "1"
                    and session.audio_format
                    == "slin24"
                ):

                    debug_dir = (
                        Path(
                            __file__
                        )
                        .resolve()
                        .parents[1]
                        / "artifacts"
                        / "voice_audio"
                        / "inbound"
                    )

                    debug_dir.mkdir(
                        parents=True,
                        exist_ok=True,
                    )

                    debug_wav_path = (
                        debug_dir
                        / (
                            "inbound_"
                            f"{session.channel_id}"
                            ".wav"
                        )
                    )

                    debug_wav = (
                        wave.open(
                            str(
                                debug_wav_path
                            ),
                            "wb",
                        )
                    )

                    debug_wav.setnchannels(
                        1
                    )

                    debug_wav.setsampwidth(
                        2
                    )

                    debug_wav.setframerate(
                        24000
                    )

                    logger.info(
                        "voice_debug_recording_started "
                        "channel_id=%s "
                        "path=%s",
                        session.channel_id,
                        debug_wav_path,
                    )

                # ====================================================
                # VAD
                # ====================================================

                vad = (
                    StreamingVAD()
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
                ) -> None:

                    if not is_final:

                        return

                    transcript = (
                        transcript.strip()
                    )

                    if not transcript:

                        return

                    stage_snapshot = (
                        conversation_state.get(
                            "stage",
                            "new",
                        )
                        .strip()
                        .lower()
                    )

                    expected_digits = (
                        get_expected_digit_count(
                            stage_snapshot
                        )
                    )

                    # ====================================================
                    # Digit Stage
                    # ====================================================

                    if expected_digits is not None:

                        detected_digits = (
                            extract_spoken_digits(
                                transcript
                            )
                        )

                        detected_count = len(
                            detected_digits
                        )

                        attempt_snapshot = (
                            digit_attempt_id
                        )

                        logger.info(
                            "deepgram_shadow_digit_candidate "
                            "channel_id=%s "
                            "stage=%s "
                            "attempt_id=%d "
                            "sensitive=true "
                            "digits_detected=%d "
                            "expected=%d "
                            "exact=%s",
                            session.channel_id,
                            stage_snapshot,
                            attempt_snapshot,
                            detected_count,
                            expected_digits,
                            (
                                detected_count
                                == expected_digits
                            ),
                        )

                        # ------------------------------------------------
                        # Only an exact candidate enters arbitration.
                        # ------------------------------------------------

                        if (
                            detected_count
                            != expected_digits
                        ):

                            return

                        def schedule_digit_candidate() -> None:

                            asyncio.create_task(
                                complete_digit_attempt(
                                    provider="deepgram",
                                    stage=stage_snapshot,
                                    attempt_id=attempt_snapshot,
                                    digits=detected_digits,
                                    turn_number=None,
                                ),
                                name=(
                                    "deepgram-digit-candidate-"
                                    f"{session.channel_id}-"
                                    f"{attempt_snapshot}"
                                ),
                            )

                        event_loop.call_soon_threadsafe(
                            schedule_digit_candidate
                        )

                        return

                    candidate_turn = (
                        hamsa_turn_number
                    )

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
                            "text=%s",
                            session.channel_id,
                            candidate_turn,
                            stage_snapshot,
                            candidate_transcript,
                        )


                    event_loop.call_soon_threadsafe(
                        store_normal_candidate
                    )

                # ====================================================
                # Tenant
                # ====================================================

                tenant_id = (
                    os.getenv(
                        "VOICE_TENANT_ID",
                        "clinic-001",
                    )
                )

                logger.info(
                    "voice_tenant_selected "
                    "channel_id=%s "
                    "tenant_id=%s",
                    session.channel_id,
                    tenant_id,
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
                        "Current benchmark phase "
                        "requires "
                        "VOICE_STT_PRIMARY=hamsa"
                    )

                if (
                    shadow_stt_name
                    != "deepgram"
                ):

                    raise RuntimeError(
                        "Current benchmark phase "
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

                logger.info(
                    "hamsa_primary_ready "
                    "channel_id=%s "
                    "model=s3 "
                    "sample_rate=24000",
                    session.channel_id,
                )

                # ====================================================
                # Deepgram SHADOW
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
                        on_transcript=(
                            on_deepgram_shadow_transcript
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
                            websocket=(
                                websocket
                            ),
                            channel_id=(
                                session.channel_id
                            ),
                            tenant_id=(
                                tenant_id
                            ),
                            audio_format=(
                                session.audio_format
                            ),
                            conversation_state=(
                                conversation_state
                            ),
                        ),
                        name=(
                            "voice-transcript-"
                            f"{session.channel_id}"
                        ),
                    )
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
                        "text=%s",
                        session.channel_id,
                        test_transcript,
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

                # ====================================================
                # Start Deepgram in Background
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

                # ====================================================
                # Optional Outbound Test
                # ====================================================

                if (
                    os.getenv(
                        "VOICE_OUTBOUND_ECHO_TEST",
                        "0",
                    )
                    == "1"
                ):

                    test_file = (
                        Path(
                            __file__
                        )
                        .resolve()
                        .parents[1]
                        / "artifacts"
                        / "voice_audio"
                        / "tts"
                        / "elevenlabs_debug.pcm"
                    )

                    if (
                        not test_file.exists()
                    ):

                        raise RuntimeError(
                            "Outbound test file "
                            "not found: "
                            f"{test_file}"
                        )

                    pcm24k = (
                        test_file.read_bytes()
                    )

                    logger.info(
                        "outbound_pcm_test_loaded "
                        "path=%s "
                        "bytes=%d",
                        test_file,
                        len(
                            pcm24k
                        ),
                    )

                    if (
                        session.audio_format
                        == "slin24"
                    ):

                        test_audio = (
                            pcm24k
                        )

                    elif (
                        session.audio_format
                        == "ulaw"
                    ):

                        test_audio = (
                            pcm16_24k_to_ulaw8k(
                                pcm24k
                            )
                        )

                    else:

                        raise RuntimeError(
                            "Unsupported outbound "
                            "test format: "
                            f"{session.audio_format}"
                        )

                    correlation_id = (
                        await send_media_audio(
                            websocket,
                            test_audio,
                        )
                    )

                    logger.info(
                        "outbound_pcm_test_sent "
                        "channel_id=%s "
                        "format=%s "
                        "bytes=%d "
                        "correlation_id=%s",
                        session.channel_id,
                        session.audio_format,
                        len(
                            test_audio
                        ),
                        correlation_id,
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
        # Stop Digit Retry Timer
        # ====================================================

        try:

            await cancel_pending_digit_retry_prompt(
                reason="session_shutdown"
            )

        except Exception:

            logger.exception(
                "digit_retry_timer_shutdown_error"
            )

        # ====================================================
        # Stop Grace Timer
        # ====================================================

        try:

            await (
                cancel_pending_turn_finalize()
            )

        except Exception:

            logger.exception(
                "turn_finalize_grace_"
                "shutdown_error"
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

                logger.exception(
                    "deepgram_shadow_shutdown_error"
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

        # ====================================================
        # Reset VAD
        # ====================================================

        if (
            vad is not None
        ):

            vad.reset()

        # ====================================================
        # Debug WAV
        # ====================================================

        if (
            debug_wav
            is not None
        ):

            try:

                debug_wav.close()

                logger.info(
                    "voice_debug_recording_saved "
                    "channel_id=%s "
                    "path=%s",
                    (
                        session.channel_id
                        if session is not None
                        else "unknown"
                    ),
                    debug_wav_path,
                )

            except Exception:

                logger.exception(
                    "voice_debug_recording_"
                    "close_failed"
                )

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
