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
from typing import Any, Callable

import websockets
from websockets.protocol import State

from voice_gateway.log_safety import (
    describe_message,
    exception_fields,
    install_log_safety,
    safe_code,
)

logger = logging.getLogger(
    "medmind.voice_gateway.hamsa"
)
install_log_safety(logger)

# websockets logs the handshake request line ("> GET /...?api_key=...")
# at DEBUG. The Hamsa key travels in that query string, so the client
# logger is capped at WARNING regardless of the application log level.
logging.getLogger(
    "websockets.client"
).setLevel(
    logging.WARNING
)


def _exception_mentions(
    exc: BaseException,
    secret: str,
) -> bool:
    """True if ``secret`` appears anywhere a traceback printer could show it:
    the message or notes of ``exc``, its cause/context chain, or the members
    of an exception group."""

    if not secret:
        return False

    seen: set[int] = set()
    pending: list[BaseException] = [exc]

    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        try:
            texts = [str(current), *map(str, getattr(current, "__notes__", None) or ())]
            if any(secret in text for text in texts):
                return True
            if isinstance(current, BaseExceptionGroup):
                pending.extend(current.exceptions)
            for linked in (current.__cause__, current.__context__):
                if linked is not None:
                    pending.append(linked)
        except Exception:
            # An exception that cannot be inspected is treated as unsafe.
            return True

    return False


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

        self._benchmark_log_transcripts = (
            os.getenv(
                "STT_BENCHMARK_LOG_TRANSCRIPTS",
                "false",
            )
            .strip()
            .lower()
            in {
                "1",
                "true",
                "yes",
                "on",
            }
        )
        
        self._websocket = None

        self._connect_lock = asyncio.Lock()
        self._request_lock = asyncio.Lock()

        self._connect_timeout_seconds = float(
            os.getenv(
                "HAMSA_CONNECT_TIMEOUT_SECONDS",
                "10",
            )
        )

        self._transcribe_timeout_seconds = float(
            os.getenv(
                "HAMSA_TRANSCRIBE_TIMEOUT_SECONDS",
                "20",
            )
        )

    async def start(
    self,
) -> None:
        """
        Open one persistent Hamsa WebSocket connection.

        The same connection is reused for all STT requests
        during the phone call.
        """

        await self._ensure_connected()

    async def _ensure_connected(
    self,
) -> None:
        """
        Ensure one reusable Hamsa WebSocket connection exists.

        websockets >= 15 exposes connection state through
        websocket.state rather than websocket.closed.
        """

        websocket = self._websocket

        # ========================================================
        # Fast path:
        # Existing connection is still open.
        # ========================================================

        if (
            websocket is not None
            and websocket.state is State.OPEN
        ):
            return

        async with self._connect_lock:

            # ====================================================
            # Check again after acquiring the lock.
            # Another coroutine may already have connected.
            # ====================================================

            websocket = self._websocket

            if (
                websocket is not None
                and websocket.state is State.OPEN
            ):
                return

            # ====================================================
            # Clean up an old / broken connection.
            # ====================================================

            if websocket is not None:

                self._websocket = None

                try:

                    await websocket.close()

                except Exception:

                    logger.debug(
                        "hamsa_old_connection_close_failed "
                        "%s",
                        exception_fields(),
                    )

            # ====================================================
            # Open persistent connection.
            # ====================================================

            uri = (
                f"{HAMSA_WS_URL}"
                f"?api_key={self._api_key}"
            )

            started_at = (
                time.perf_counter()
            )

            websocket = None

            try:

                websocket = (
                    await websockets.connect(
                        uri,
                        max_size=None,
                        open_timeout=(
                            self._connect_timeout_seconds
                        ),
                        close_timeout=1,
                    )
                )

                await asyncio.wait_for(
                    websocket.recv(),
                    timeout=(
                        self._connect_timeout_seconds
                    ),
                )

            except asyncio.CancelledError:

                if websocket is not None:

                    try:

                        await websocket.close()

                    except Exception:

                        logger.debug(
                            "hamsa_cancelled_connect_close_failed "
                            "%s",
                            exception_fields(),
                        )

                raise

            except Exception as exc:

                if websocket is not None:

                    try:

                        await websocket.close()

                    except Exception:

                        logger.debug(
                            "hamsa_failed_connect_close_failed "
                            "%s",
                            exception_fields(),
                        )

                # The URI carries api_key, and some websockets errors
                # (e.g. InvalidURI) quote it. Never let that text reach
                # a traceback, in this module's logs or anywhere else.
                if _exception_mentions(exc, self._api_key):
                    raise RuntimeError(
                        "Hamsa connection failed "
                        f"({type(exc).__name__}; details withheld)"
                    ) from None

                raise


            self._websocket = (
                websocket
            )

            elapsed_ms = (
                (
                    time.perf_counter()
                    - started_at
                )
                * 1000
            )

            logger.info(
                "hamsa_persistent_connection_ready "
                "elapsed_ms=%.2f "
                "state=%s",
                elapsed_ms,
                websocket.state.name,
            )

    async def close(
    self,
) -> None:
        websocket = (
            self._websocket
        )

        self._websocket = None

        if websocket is None:
            return

        try:

            await websocket.close()

        except Exception:

            logger.error(
                "hamsa_connection_close_failed "
                "%s",
                exception_fields()
            )

        logger.info(
            "hamsa_stt_closed"
        )

    async def reset_connection(
        self,
        *,
        reason: str = "unknown",
    ) -> None:
        """
        Force-reset the current Hamsa WebSocket.

        Used when an STT request exceeds the Voice Gateway
        soft timeout. Closing the socket releases a stalled
        recv() and allows the next request to reconnect on
        a clean session.

        Important:
        Do NOT acquire _request_lock here because the stalled
        transcribe() call may currently own that lock.
        """

        async with self._connect_lock:

            websocket = self._websocket

            self._websocket = None

            if websocket is None:
                return

            logger.warning(
                "hamsa_connection_reset "
                "reason=%s "
                "state=%s",
                reason,
                (
                    websocket.state.name
                    if websocket is not None
                    else "unknown"
                ),
            )

            try:

                await websocket.close()

            except Exception:

                logger.debug(
                    "hamsa_connection_reset_close_failed "
                    "reason=%s "
                    "%s",
                    reason,
                    exception_fields(),
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
        Log STT operational metadata without storing
        caller transcript content.

        Even normal conversational turns may contain
        healthcare information or patient PII.
        """

        logger.info(
            "hamsa_transcript "
            "sensitive=%s "
            "characters=%d "
            "elapsed_ms=%.2f "
            "audio_bytes=%d "
            "sample_rate=%d "
            "source=%s",
            sensitive,
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

        # STT_BENCHMARK_LOG_TRANSCRIPTS no longer logs transcript text
        # (it could contain names, national IDs or phone numbers, on any
        # stage). It now adds word-count metadata only.
        if self._benchmark_log_transcripts:

            logger.info(
                "hamsa_benchmark_final "
                "sensitive=%s "
                "characters=%d "
                "words=%d "
                "source=%s",
                sensitive,
                len(
                    transcript
                ),
                len(
                    transcript.split()
                ),
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
        on_status: Callable[[str], None] | None = None,
    ) -> str:
        """
        Transcribe one PCM16 audio chunk using the
        persistent Hamsa WebSocket connection.

        The connection is opened once by start()
        and reused across caller turns.

        If the connection fails, it is reset so the
        next request can reconnect automatically.
        """

        if not pcm_audio:
            return ""

        started_at = time.perf_counter()

        # ========================================================
        # PCM -> WAV -> Base64
        # ========================================================

        wav_bytes = self._pcm_to_wav(
            pcm_audio
        )

        audio_base64 = (
            base64.b64encode(
                wav_bytes
            )
            .decode(
                "ascii"
            )
        )

        # ========================================================
        # Build STT request
        # ========================================================

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

        # ========================================================
        # One request at a time on the persistent socket.
        #
        # The current voice gateway already has one serial
        # Hamsa worker, but this lock also protects the provider
        # if it is reused elsewhere later.
        # ========================================================

        async with self._request_lock:

            try:

                # ====================================================
                # Make sure persistent connection exists
                # ====================================================

                await self._ensure_connected()

                websocket = (
                    self._websocket
                )

                if websocket is None:

                    logger.error(
                        "hamsa_connection_unavailable"
                    )

                    return ""

                # ====================================================
                # Send STT request
                # ====================================================

                request_started_at = (
                    time.perf_counter()
                )

                await websocket.send(
                    json.dumps(
                        request
                    )
                )

                send_elapsed_ms = (
                    (
                        time.perf_counter()
                        - request_started_at
                    )
                    * 1000
                )

                logger.debug(
                    "hamsa_request_sent "
                    "audio_bytes=%d "
                    "sample_rate=%d "
                    "eos_enabled=%s "
                    "sensitive=%s "
                    "model=%s "
                    "send_ms=%.2f",
                    len(
                        pcm_audio
                    ),
                    self._sample_rate,
                    eos_enabled,
                    sensitive,
                    self._model,
                    send_elapsed_ms,
                )

                # ====================================================
                # Deadline
                #
                # [THINKING] / [PROCESSING] etc. do not count as
                # transcripts.
                # ====================================================

                deadline = (
                    time.perf_counter()
                    + self._transcribe_timeout_seconds
                )

                # ====================================================
                # Receive loop
                # ====================================================

                while True:

                    remaining_seconds = (
                        deadline
                        - time.perf_counter()
                    )

                    if remaining_seconds <= 0:

                        logger.error(
                            "hamsa_transcription_timeout "
                            "audio_bytes=%d "
                            "timeout_seconds=%.2f "
                            "eos_enabled=%s "
                            "sensitive=%s "
                            "action=reset_connection",
                            len(
                                pcm_audio
                            ),
                            self._transcribe_timeout_seconds,
                            eos_enabled,
                            sensitive,
                        )

                        await self.reset_connection(
                            reason="transcription_timeout",
                        )

                        return ""

                    # =================================================
                    # Receive next Hamsa message
                    # =================================================

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
                            "sensitive=%s "
                            "action=reset_connection",
                            len(
                                pcm_audio
                            ),
                            self._transcribe_timeout_seconds,
                            eos_enabled,
                            sensitive,
                        )

                        await self.reset_connection(
                            reason="transcription_timeout",
                        )

                        return ""

                    # =================================================
                    # Normalize response
                    # =================================================

                    response_text = (
                        self._normalize_text(
                            response
                        )
                    )

                    if not response_text:
                        continue

                    # =================================================
                    # Try JSON
                    # =================================================

                    try:

                        message = (
                            json.loads(
                                response_text
                            )
                        )

                    except json.JSONDecodeError:

                        # =============================================
                        # Plain text provider response
                        #
                        # Could be:
                        #
                        # [THINKING]
                        # [PROCESSING]
                        # actual transcript
                        # =============================================

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

                            if on_status is not None:
                                on_status(
                                    response_text
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

                        return (
                            transcript
                        )

                    # =================================================
                    # JSON must be an object
                    # =================================================

                    if not isinstance(
                        message,
                        dict,
                    ):

                        # Shape only: provider messages may carry caller speech.
                        logger.debug(
                            "hamsa_message %s",
                            describe_message(
                                message
                            ),
                        )

                        continue

                    # =================================================
                    # Message type
                    # =================================================

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

                    # =================================================
                    # Provider error
                    # =================================================

                    if (
                        message_type
                        == "error"
                    ):

                        # Never the provider error text: shape and code only.
                        logger.error(
                            "hamsa_error %s "
                            "error_code=%s",
                            describe_message(
                                message
                            ),
                            safe_code(
                                message.get("code")
                                if message.get("code") is not None
                                else message.get("status")
                            ),
                        )

                        return ""

                    # =================================================
                    # JSON transcript
                    # =================================================

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

                    # =================================================
                    # Other Hamsa JSON/control message
                    # =================================================

                    # Shape only: provider messages may carry caller speech.
                    logger.debug(
                        "hamsa_message %s",
                        describe_message(
                            message
                        ),
                    )

            except asyncio.CancelledError:

                logger.warning(
                    "hamsa_request_cancelled "
                    "action=reset_connection"
                )

                try:

                    await self.reset_connection(
                        reason=(
                            "transcription_cancelled"
                        ),
                    )

                except Exception:

                    logger.debug(
                        "hamsa_cancel_reset_failed "
                        "%s",
                        exception_fields(),
                    )

                raise

            except Exception:

                logger.error(
                    "hamsa_persistent_request_failed "
                    "audio_bytes=%d "
                    "sample_rate=%d "
                    "eos_enabled=%s "
                    "sensitive=%s "
                    "action=reset_connection "
                    "%s",
                    len(
                        pcm_audio
                    ),
                    self._sample_rate,
                    eos_enabled,
                    sensitive,
                    exception_fields(),
                )

                # ====================================================
                # Socket may now be unusable.
                #
                # Drop it. _ensure_connected() will open a new one
                # on the next request.
                # ====================================================

                websocket = (
                    self._websocket
                )

                self._websocket = None

                if websocket is not None:

                    try:

                        await websocket.close()

                    except Exception:

                        logger.debug(
                            "hamsa_failed_socket_close_error "
                            "%s",
                            exception_fields(),
                        )

                return ""
