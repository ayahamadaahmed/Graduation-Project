from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
import time
import wave
from typing import Any

import websockets


logger = logging.getLogger(
    "medmind.voice_gateway.hamsa"
)


HAMSA_WS_URL = (
    "wss://api.tryhamsa.com/v1/realtime/ws"
)


# ============================================================
# Hamsa control/status messages
#
# These are NOT caller transcripts.
# ============================================================

HAMSA_CONTROL_MESSAGES = {
    "[THINKING]",
    "[PROCESSING]",
    "[TRANSCRIBING]",
    "[LISTENING]",
    "[DONE]",
    "[READY]",
}


_CONTROL_MESSAGE_RE = re.compile(
    r"^\[[A-Z][A-Z0-9 _-]*\]$"
)


class HamsaSTT:
    """
    Hamsa S3 STT provider.

    Input:
        Raw PCM16 mono audio.

    Current MedMind role:
        Primary live STT provider.

    Hamsa may emit status/control messages before
    returning the actual transcription.

    These messages must never be forwarded
    to MedMind.
    """

    def __init__(
        self,
        *,
        sample_rate: int = 24000,
        language: str = "ar",
        model: str = "s3",
    ) -> None:

        api_key = os.getenv(
            "HAMSA_API_KEY"
        )

        if not api_key:

            raise RuntimeError(
                "HAMSA_API_KEY "
                "is not configured"
            )

        if sample_rate <= 0:

            raise ValueError(
                "sample_rate must be "
                "greater than zero"
            )

        self._api_key = (
            api_key
        )

        self._sample_rate = (
            sample_rate
        )

        self._language = (
            language
        )

        self._model = (
            model
        )

        self._transcribe_timeout_seconds = float(
            os.getenv(
                "HAMSA_TRANSCRIBE_TIMEOUT_SECONDS",
                "20",
            )
        )

    # ========================================================
    # Raw PCM -> WAV
    # ========================================================

    def _pcm_to_wav(
        self,
        pcm_audio: bytes,
    ) -> bytes:
        """
        Wrap raw PCM16 mono audio inside a WAV container.
        """

        buffer = (
            io.BytesIO()
        )

        with wave.open(
            buffer,
            "wb",
        ) as wav_file:

            wav_file.setnchannels(
                1
            )

            # PCM16
            wav_file.setsampwidth(
                2
            )

            wav_file.setframerate(
                self._sample_rate
            )

            wav_file.writeframes(
                pcm_audio
            )

        return (
            buffer.getvalue()
        )

    # ========================================================
    # Message Helpers
    # ========================================================

    @staticmethod
    def _normalize_text(
        value: Any,
    ) -> str:

        if value is None:

            return ""

        if isinstance(
            value,
            bytes,
        ):

            return (
                value.decode(
                    "utf-8",
                    errors="replace",
                )
                .strip()
            )

        return (
            str(
                value
            )
            .strip()
        )

    @staticmethod
    def _is_control_message(
        text: str,
    ) -> bool:
        """
        Return True when Hamsa sends a provider
        status message rather than caller speech.
        """

        normalized = (
            text.strip()
        )

        if not normalized:

            return True

        upper = (
            normalized.upper()
        )

        if (
            upper
            in HAMSA_CONTROL_MESSAGES
        ):

            return True

        # Defensive handling for provider messages:
        #
        # [THINKING]
        # [PROCESSING_AUDIO]
        # [TRANSCRIBING]
        #
        if (
            _CONTROL_MESSAGE_RE.fullmatch(
                upper
            )
        ):

            return True

        return False

    @classmethod
    def _extract_json_transcript(
        cls,
        message: dict[
            str,
            Any,
        ],
    ) -> str:
        """
        Hamsa's successful response may arrive
        as plain text.

        Support common JSON result shapes
        defensively as well.
        """

        candidates: list[Any] = [
            message.get(
                "transcript"
            ),
            message.get(
                "text"
            ),
            message.get(
                "result"
            ),
        ]

        payload = (
            message.get(
                "payload"
            )
        )

        if isinstance(
            payload,
            dict,
        ):

            candidates.extend(
                [
                    payload.get(
                        "transcript"
                    ),
                    payload.get(
                        "text"
                    ),
                    payload.get(
                        "result"
                    ),
                ]
            )

        for candidate in candidates:

            if not isinstance(
                candidate,
                str,
            ):

                continue

            text = (
                candidate.strip()
            )

            if (
                text
                and not cls._is_control_message(
                    text
                )
            ):

                return (
                    text
                )

        return ""

    # ========================================================
    # Transcript Logging
    # ========================================================

    def _log_transcript(
        self,
        *,
        transcript: str,
        elapsed_ms: float,
        pcm_audio: bytes,
        sensitive: bool,
        source: str,
    ) -> None:
        """
        Log STT result without exposing sensitive
        identifiers such as national IDs or phones.
        """

        if sensitive:

            logger.info(
                "hamsa_transcript "
                "sensitive=true "
                "characters=%d "
                "elapsed_ms=%.2f "
                "audio_bytes=%d "
                "sample_rate=%d "
                "source=%s",
                len(
                    transcript
                ),
                elapsed_ms,
                len(
                    pcm_audio
                ),
                self._sample_rate,
                source,
            )

            return

        logger.info(
            "hamsa_transcript "
            "text=%s "
            "elapsed_ms=%.2f "
            "audio_bytes=%d "
            "sample_rate=%d "
            "source=%s",
            transcript,
            elapsed_ms,
            len(
                pcm_audio
            ),
            self._sample_rate,
            source,
        )

    # ========================================================
    # Transcribe one caller audio chunk
    # ========================================================

    async def transcribe(
        self,
        pcm_audio: bytes,
        *,
        eos_enabled: bool = True,
        sensitive: bool = False,
    ) -> str:
        """
        Transcribe one PCM16 audio chunk.

        eos_enabled=True:
            Used when caller naturally stopped speaking.

        eos_enabled=False:
            Used when MedMind performs a hard audio split
            while the caller may still be speaking.

        sensitive=True:
            Transcript text is not printed in logs.
        """

        if not pcm_audio:

            return ""

        started_at = (
            time.perf_counter()
        )

        # ====================================================
        # PCM -> WAV
        # ====================================================

        wav_bytes = (
            self._pcm_to_wav(
                pcm_audio
            )
        )

        audio_base64 = (
            base64.b64encode(
                wav_bytes
            )
            .decode(
                "ascii"
            )
        )

        # ====================================================
        # WebSocket URI
        # ====================================================

        uri = (
            f"{HAMSA_WS_URL}"
            f"?api_key={self._api_key}"
        )

        try:

            async with websockets.connect(
                uri,
                max_size=None,
                open_timeout=10,
                close_timeout=5,
            ) as websocket:

                # ================================================
                # Initial Hamsa connection message
                # ================================================

                connection_message = (
                    await asyncio.wait_for(
                        websocket.recv(),
                        timeout=10.0,
                    )
                )

                logger.debug(
                    "hamsa_connected "
                    "message=%s",
                    connection_message,
                )

                # ================================================
                # Build STT request
                # ================================================

                request = {
                    "type": "stt",
                    "payload": {
                        "audioBase64": (
                            audio_base64
                        ),
                        "language": (
                            self._language
                        ),
                        "isEosEnabled": (
                            eos_enabled
                        ),
                        "eosThreshold": 0.3,
                        "model": (
                            self._model
                        ),
                    },
                }

                # ================================================
                # Send STT request
                # ================================================

                await websocket.send(
                    json.dumps(
                        request
                    )
                )

                logger.debug(
                    "hamsa_request_sent "
                    "audio_bytes=%d "
                    "sample_rate=%d "
                    "eos_enabled=%s "
                    "sensitive=%s "
                    "model=%s",
                    len(
                        pcm_audio
                    ),
                    self._sample_rate,
                    eos_enabled,
                    sensitive,
                    self._model,
                )

                # ================================================
                # Deadline
                #
                # [THINKING] and similar provider statuses do
                # NOT count as final transcripts.
                # ================================================

                deadline = (
                    time.perf_counter()
                    + self._transcribe_timeout_seconds
                )

                # ================================================
                # Receive loop
                # ================================================

                while True:

                    remaining_seconds = (
                        deadline
                        - time.perf_counter()
                    )

                    # --------------------------------------------
                    # Deadline exhausted
                    # --------------------------------------------

                    if (
                        remaining_seconds
                        <= 0
                    ):

                        logger.error(
                            "hamsa_transcription_timeout "
                            "audio_bytes=%d "
                            "timeout_seconds=%.2f "
                            "eos_enabled=%s "
                            "sensitive=%s",
                            len(
                                pcm_audio
                            ),
                            self._transcribe_timeout_seconds,
                            eos_enabled,
                            sensitive,
                        )

                        return ""

                    # --------------------------------------------
                    # Receive next provider message
                    # --------------------------------------------

                    try:

                        response = (
                            await asyncio.wait_for(
                                websocket.recv(),
                                timeout=(
                                    remaining_seconds
                                ),
                            )
                        )

                    except asyncio.TimeoutError:

                        logger.error(
                            "hamsa_transcription_timeout "
                            "audio_bytes=%d "
                            "timeout_seconds=%.2f "
                            "eos_enabled=%s "
                            "sensitive=%s",
                            len(
                                pcm_audio
                            ),
                            self._transcribe_timeout_seconds,
                            eos_enabled,
                            sensitive,
                        )

                        return ""

                    # ============================================
                    # Normalize response
                    # ============================================

                    response_text = (
                        self._normalize_text(
                            response
                        )
                    )

                    if not response_text:

                        continue

                    # ============================================
                    # Try JSON
                    # ============================================

                    try:

                        message = (
                            json.loads(
                                response_text
                            )
                        )

                    except json.JSONDecodeError:

                        # ========================================
                        # Plain-text Hamsa response
                        #
                        # Examples:
                        #
                        # [THINKING]
                        # actual caller transcript
                        # ========================================

                        if (
                            self._is_control_message(
                                response_text
                            )
                        ):

                            logger.info(
                                "hamsa_status_message "
                                "status=%s",
                                response_text,
                            )

                            continue

                        transcript = (
                            response_text.strip()
                        )

                        elapsed_ms = (
                            (
                                time.perf_counter()
                                - started_at
                            )
                            * 1000
                        )

                        self._log_transcript(
                            transcript=(
                                transcript
                            ),
                            elapsed_ms=(
                                elapsed_ms
                            ),
                            pcm_audio=(
                                pcm_audio
                            ),
                            sensitive=(
                                sensitive
                            ),
                            source="plain",
                        )

                        # IMPORTANT:
                        #
                        # This return was missing in the
                        # previous version.
                        return (
                            transcript
                        )

                    # ============================================
                    # JSON message must be object
                    # ============================================

                    if not isinstance(
                        message,
                        dict,
                    ):

                        logger.debug(
                            "hamsa_message "
                            "message=%s",
                            message,
                        )

                        continue

                    # ============================================
                    # Message Type
                    # ============================================

                    message_type = (
                        str(
                            message.get(
                                "type",
                                "",
                            )
                        )
                        .strip()
                        .lower()
                    )

                    # ============================================
                    # Provider Error
                    # ============================================

                    if (
                        message_type
                        == "error"
                    ):

                        logger.error(
                            "hamsa_error "
                            "message=%s",
                            message,
                        )

                        return ""

                    # ============================================
                    # JSON Transcript
                    # ============================================

                    json_transcript = (
                        self._extract_json_transcript(
                            message
                        )
                    )

                    if json_transcript:

                        elapsed_ms = (
                            (
                                time.perf_counter()
                                - started_at
                            )
                            * 1000
                        )

                        self._log_transcript(
                            transcript=(
                                json_transcript
                            ),
                            elapsed_ms=(
                                elapsed_ms
                            ),
                            pcm_audio=(
                                pcm_audio
                            ),
                            sensitive=(
                                sensitive
                            ),
                            source="json",
                        )

                        return (
                            json_transcript
                        )

                    # ============================================
                    # Non-result provider JSON message
                    # ============================================

                    logger.debug(
                        "hamsa_message "
                        "message=%s",
                        message,
                    )

        except asyncio.CancelledError:

            raise

        except Exception:

            logger.exception(
                "hamsa_failed "
                "audio_bytes=%d "
                "sample_rate=%d "
                "eos_enabled=%s "
                "sensitive=%s",
                len(
                    pcm_audio
                ),
                self._sample_rate,
                eos_enabled,
                sensitive,
            )

            return ""