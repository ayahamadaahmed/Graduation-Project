from __future__ import annotations

import asyncio
import audioop
import logging
import os
import time
from collections.abc import AsyncIterator

import httpx

from voice_gateway.config import load_environment


# ============================================================
# Environment
# ============================================================

load_environment()


# ============================================================
# Logging
# ============================================================

logger = logging.getLogger(
    "medmind.voice_gateway.hamsa_tts"
)


# ============================================================
# Constants
# ============================================================

HAMSA_TTS_STREAM_URL = (
    "https://api.tryhamsa.com/v1/realtime/tts-stream"
)

INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000
SAMPLE_WIDTH = 2
CHANNELS = 1

# Asterisk slin24:
#
# 24,000 samples/sec
# * 0.020 sec
# * 2 bytes/sample
#
# = 960 bytes per 20 ms frame
#
ASTERISK_FRAME_BYTES = 960


# ============================================================
# Hamsa TTS
# ============================================================


class HamsaTTS:
    """
    Hamsa realtime TTS provider.

    Input:
        text

    Hamsa output:
        raw PCM16
        mono
        16 kHz

    MedMind / Asterisk output:
        raw PCM16
        mono
        24 kHz
        slin24

    Pipeline:

        Hamsa 16k PCM
            ↓
        preserve PCM16 sample alignment
            ↓
        stateful 16k -> 24k resampling
            ↓
        buffer into 20 ms / 960-byte frames
            ↓
        Asterisk slin24
    """

    def __init__(
        self,
        *,
        speaker: str | None = None,
        dialect: str | None = None,
        expressiveness: int | None = None,
    ) -> None:

        # ====================================================
        # API Key
        # ====================================================

        self.api_key = (
            os.getenv(
                "HAMSA_API_KEY",
                "",
            )
            .strip()
        )

        if not self.api_key:
            raise RuntimeError(
                "HAMSA_API_KEY is not configured."
            )

        # ====================================================
        # Voice Configuration
        # ====================================================

        self.speaker = (
            speaker
            or os.getenv(
                "HAMSA_TTS_SPEAKER",
                "Samir",
            )
        ).strip()

        self.dialect = (
            dialect
            or os.getenv(
                "HAMSA_TTS_DIALECT",
                "egy",
            )
        ).strip()

        if expressiveness is None:
            expressiveness = int(
                os.getenv(
                    "HAMSA_TTS_EXPRESSIVENESS",
                    "1",
                )
            )

        self.expressiveness = expressiveness

        # ====================================================
        # HTTP Configuration
        # ====================================================

        self._timeout_seconds = float(
            os.getenv(
                "HAMSA_TTS_TIMEOUT_SECONDS",
                "30",
            )
        )

        self._connect_timeout_seconds = float(
            os.getenv(
                "HAMSA_TTS_CONNECT_TIMEOUT_SECONDS",
                "10",
            )
        )

        # Maximum attempts.
        #
        # 2 means:
        #   attempt 1 = normal request
        #   attempt 2 = one retry
        #
        # Retry is ONLY allowed before any audio has been
        # yielded to Asterisk.
        #
        self._max_attempts = max(
            1,
            int(
                os.getenv(
                    "HAMSA_TTS_MAX_ATTEMPTS",
                    "2",
                )
            ),
        )

        # ====================================================
        # HTTP Client
        # ====================================================

        self._client_reset_lock = asyncio.Lock()

        self._client = self._build_http_client()

        # ====================================================
        # Warm-up State
        # ====================================================

        self._warmup_lock = asyncio.Lock()
        self._warmed_up = False

        logger.info(
            "hamsa_tts_initialized "
            "speaker=%s "
            "dialect=%s "
            "input_sample_rate=%d "
            "output_sample_rate=%d "
            "expressiveness=%d "
            "max_attempts=%d",
            self.speaker,
            self.dialect,
            INPUT_SAMPLE_RATE,
            OUTPUT_SAMPLE_RATE,
            self.expressiveness,
            self._max_attempts,
        )

    # ========================================================
    # HTTP Client
    # ========================================================

    def _build_http_client(
        self,
    ) -> httpx.AsyncClient:
        """
        Create the HTTP client used by Hamsa TTS.

        Keeping this in one helper guarantees that a rebuilt
        client uses exactly the same timeout configuration as
        the original client.
        """

        return httpx.AsyncClient(
            timeout=httpx.Timeout(
                self._timeout_seconds,
                connect=self._connect_timeout_seconds,
            )
        )

    async def _reset_http_client(
        self,
        *,
        failed_client: httpx.AsyncClient | None = None,
    ) -> None:
        """
        Rebuild the Hamsa HTTP client after a transport failure.

        failed_client prevents an older failed request from
        accidentally closing a newer client that another
        coroutine may already have installed.
        """

        async with self._client_reset_lock:

            current_client = self._client

            if (
                failed_client is not None
                and current_client is not failed_client
            ):
                logger.debug(
                    "hamsa_tts_http_client_reset_skipped "
                    "reason=client_already_replaced"
                )
                return

            new_client = self._build_http_client()

            self._client = new_client

            try:
                await current_client.aclose()

            except Exception:
                logger.debug(
                    "hamsa_tts_old_client_close_failed",
                    exc_info=True,
                )

            logger.info(
                "hamsa_tts_http_client_reset"
            )

    # ========================================================
    # Headers
    # ========================================================

    def _headers(
        self,
    ) -> dict[str, str]:

        return {
            "Authorization": (
                f"Token {self.api_key}"
            ),
            "Content-Type": (
                "application/json"
            ),
        }

    # ========================================================
    # Payload
    # ========================================================

    def _payload(
        self,
        text: str,
    ) -> dict[str, object]:

        return {
            "text": text,
            "speaker": self.speaker,
            "dialect": self.dialect,
            "mulaw": False,
            "sampleRate": "16k",
            "expressiveness": self.expressiveness,
        }

    # ========================================================
    # Warm-up
    # ========================================================

    async def warmup(
        self,
    ) -> bool:
        """
        Warm the Hamsa realtime TTS path before the first
        caller-facing reply.

        The generated audio is discarded and is NEVER sent
        to Asterisk.

        This warms:
            - DNS / TCP / TLS / HTTP connection
            - Hamsa realtime TTS request path
            - provider-side synthesis path

        Warm-up failure is non-fatal.
        """

        if self._warmed_up:
            return True

        async with self._warmup_lock:

            if self._warmed_up:
                return True

            started_at = time.perf_counter()

            warmup_text = (
                os.getenv(
                    "HAMSA_TTS_WARMUP_TEXT",
                    "تمام",
                )
                .strip()
            )

            timeout_seconds = float(
                os.getenv(
                    "HAMSA_TTS_WARMUP_TIMEOUT_SECONDS",
                    "8",
                )
            )

            if not warmup_text:

                logger.warning(
                    "hamsa_tts_warmup_skipped "
                    "reason=empty_text"
                )

                return False

            stream = self.stream_pcm24k(
                warmup_text
            )

            try:

                # One playable frame is enough.
                #
                # We do NOT need to synthesize/play the
                # whole warm-up utterance.

                first_chunk = await asyncio.wait_for(
                    anext(stream),
                    timeout=timeout_seconds,
                )

                if not first_chunk:

                    logger.warning(
                        "hamsa_tts_warmup_empty_audio"
                    )

                    return False

                self._warmed_up = True

                elapsed_ms = (
                    (
                        time.perf_counter()
                        - started_at
                    )
                    * 1000
                )

                logger.info(
                    "hamsa_tts_warmup_ready "
                    "elapsed_ms=%.2f "
                    "first_chunk_bytes=%d "
                    "speaker=%s "
                    "dialect=%s",
                    elapsed_ms,
                    len(first_chunk),
                    self.speaker,
                    self.dialect,
                )

                return True

            except asyncio.TimeoutError:

                logger.warning(
                    "hamsa_tts_warmup_timeout "
                    "timeout_seconds=%.2f",
                    timeout_seconds,
                )

                return False

            except Exception as exc:

                logger.warning(
                    "hamsa_tts_warmup_failed "
                    "error_type=%s",
                    type(exc).__name__,
                    exc_info=True,
                )

                return False

            finally:

                try:
                    await stream.aclose()

                except Exception:

                    logger.debug(
                        "hamsa_tts_warmup_stream_close_failed",
                        exc_info=True,
                    )

    # ========================================================
    # Stream PCM24
    # ========================================================

    async def stream_pcm24k(
        self,
        text: str,
    ) -> AsyncIterator[bytes]:
        """
        Stream Hamsa TTS as raw PCM16 mono @ 24 kHz.

        The method intentionally exposes the same interface
        used by the existing ElevenLabs streaming path:

            async for chunk in tts.stream_pcm24k(text)

        Important:

        Hamsa HTTP chunks are network chunks, not guaranteed
        PCM sample boundaries.

        We therefore preserve:
            - incomplete PCM16 byte
            - audioop ratecv state
            - incomplete Asterisk 20 ms frame

        Reliability:

        One retry is allowed by default when a transport-level
        failure occurs BEFORE the first playable audio frame is
        yielded.

        Once audio has already been yielded, retrying from the
        beginning would duplicate caller-facing speech, so the
        original exception is raised instead.
        """

        text = text.strip()

        if not text:
            return

        max_attempts = self._max_attempts

        # ====================================================
        # Retry loop
        # ====================================================

        for attempt in range(
            1,
            max_attempts + 1,
        ):

            # Everything below belongs to exactly one provider
            # request.
            #
            # If we retry before the first yielded audio frame,
            # these states MUST begin clean again.

            pcm16_carry = b""
            resample_state = None
            asterisk_buffer = bytearray()

            input_bytes = 0
            output_bytes = 0
            network_chunks = 0
            output_frames = 0

            first_network_at: float | None = None
            first_output_at: float | None = None

            started_at = time.perf_counter()

            first_audio_yielded = False

            # Capture the exact client used by this attempt.
            #
            # If it fails, _reset_http_client() can verify
            # that it is still the active client before
            # replacing it.

            client = self._client

            try:

                # ============================================
                # Request
                # ============================================

                async with client.stream(
                    "POST",
                    HAMSA_TTS_STREAM_URL,
                    json=self._payload(
                        text
                    ),
                    headers=self._headers(),
                ) as response:

                    headers_at = time.perf_counter()

                    headers_ms = (
                        headers_at
                        - started_at
                    ) * 1000

                    logger.info(
                        "hamsa_tts_stream_connected "
                        "status=%d "
                        "content_type=%s "
                        "headers_ms=%.2f "
                        "speaker=%s "
                        "dialect=%s "
                        "attempt=%d",
                        response.status_code,
                        response.headers.get(
                            "content-type"
                        ),
                        headers_ms,
                        self.speaker,
                        self.dialect,
                        attempt,
                    )

                    # ========================================
                    # HTTP Error
                    # ========================================

                    if response.status_code != 200:

                        error_body = await response.aread()

                        logger.error(
                            "hamsa_tts_http_error "
                            "status=%d "
                            "body_bytes=%d "
                            "attempt=%d",
                            response.status_code,
                            len(
                                error_body
                            ),
                            attempt,
                        )

                        response.raise_for_status()

                    # ========================================
                    # Stream
                    # ========================================

                    async for network_chunk in (
                        response.aiter_bytes()
                    ):

                        if not network_chunk:
                            continue

                        now = time.perf_counter()

                        network_chunks += 1

                        input_bytes += len(
                            network_chunk
                        )

                        # ====================================
                        # First network bytes
                        # ====================================

                        if first_network_at is None:

                            first_network_at = now

                            first_network_ms = (
                                first_network_at
                                - started_at
                            ) * 1000

                            logger.info(
                                "hamsa_tts_first_network_audio "
                                "first_ms=%.2f "
                                "chunk_bytes=%d "
                                "attempt=%d",
                                first_network_ms,
                                len(
                                    network_chunk
                                ),
                                attempt,
                            )

                        # ====================================
                        # Restore PCM16 alignment
                        #
                        # Hamsa may return odd HTTP chunk
                        # sizes.
                        #
                        # PCM16 samples require 2 bytes.
                        # ====================================

                        if pcm16_carry:

                            network_chunk = (
                                pcm16_carry
                                + network_chunk
                            )

                            pcm16_carry = b""

                        if (
                            len(
                                network_chunk
                            )
                            % SAMPLE_WIDTH
                            != 0
                        ):

                            pcm16_carry = (
                                network_chunk[-1:]
                            )

                            network_chunk = (
                                network_chunk[:-1]
                            )

                        if not network_chunk:
                            continue

                        # ====================================
                        # Stateful 16k -> 24k
                        # ====================================

                        (
                            converted_audio,
                            resample_state,
                        ) = audioop.ratecv(
                            network_chunk,
                            SAMPLE_WIDTH,
                            CHANNELS,
                            INPUT_SAMPLE_RATE,
                            OUTPUT_SAMPLE_RATE,
                            resample_state,
                        )

                        if not converted_audio:
                            continue

                        # ====================================
                        # Asterisk frame buffer
                        # ====================================

                        asterisk_buffer.extend(
                            converted_audio
                        )

                        # ====================================
                        # Yield exact 20 ms slin24 frames
                        #
                        # 960 bytes = 20 ms
                        # @ PCM16 / 24k / mono
                        # ====================================

                        while (
                            len(
                                asterisk_buffer
                            )
                            >= ASTERISK_FRAME_BYTES
                        ):

                            output_chunk = bytes(
                                asterisk_buffer[
                                    :ASTERISK_FRAME_BYTES
                                ]
                            )

                            del asterisk_buffer[
                                :ASTERISK_FRAME_BYTES
                            ]

                            if first_output_at is None:

                                first_output_at = (
                                    time.perf_counter()
                                )

                                first_output_ms = (
                                    first_output_at
                                    - started_at
                                ) * 1000

                                logger.info(
                                    "hamsa_tts_first_playable_audio "
                                    "first_ms=%.2f "
                                    "frame_bytes=%d "
                                    "attempt=%d",
                                    first_output_ms,
                                    len(
                                        output_chunk
                                    ),
                                    attempt,
                                )

                            output_frames += 1

                            output_bytes += len(
                                output_chunk
                            )

                            # Critical:
                            #
                            # From this point onward we MUST
                            # NOT retry the utterance from the
                            # beginning because the caller has
                            # already heard audio.

                            first_audio_yielded = True

                            yield output_chunk

                # ============================================
                # Final PCM16 validation
                # ============================================

                if pcm16_carry:

                    logger.warning(
                        "hamsa_tts_incomplete_pcm16_sample "
                        "trailing_bytes=%d "
                        "attempt=%d",
                        len(
                            pcm16_carry
                        ),
                        attempt,
                    )

                # ============================================
                # Flush final resampled audio
                #
                # Asterisk can accept the final partial frame.
                # ============================================

                if asterisk_buffer:

                    final_chunk = bytes(
                        asterisk_buffer
                    )

                    output_frames += 1

                    output_bytes += len(
                        final_chunk
                    )

                    if first_output_at is None:

                        first_output_at = (
                            time.perf_counter()
                        )

                        first_output_ms = (
                            first_output_at
                            - started_at
                        ) * 1000

                        logger.info(
                            "hamsa_tts_first_playable_audio "
                            "first_ms=%.2f "
                            "frame_bytes=%d "
                            "attempt=%d",
                            first_output_ms,
                            len(
                                final_chunk
                            ),
                            attempt,
                        )

                    first_audio_yielded = True

                    yield final_chunk

                # ============================================
                # Metrics
                # ============================================

                completed_at = time.perf_counter()

                total_ms = (
                    completed_at
                    - started_at
                ) * 1000

                first_network_ms = (
                    (
                        first_network_at
                        - started_at
                    )
                    * 1000
                    if first_network_at
                    is not None
                    else None
                )

                first_output_ms = (
                    (
                        first_output_at
                        - started_at
                    )
                    * 1000
                    if first_output_at
                    is not None
                    else None
                )

                logger.info(
                    "hamsa_tts_stream_completed "
                    "speaker=%s "
                    "dialect=%s "
                    "network_chunks=%d "
                    "input_bytes=%d "
                    "output_frames=%d "
                    "output_bytes=%d "
                    "first_network_ms=%s "
                    "first_output_ms=%s "
                    "total_ms=%.2f "
                    "attempt=%d",
                    self.speaker,
                    self.dialect,
                    network_chunks,
                    input_bytes,
                    output_frames,
                    output_bytes,
                    (
                        f"{first_network_ms:.2f}"
                        if first_network_ms
                        is not None
                        else "none"
                    ),
                    (
                        f"{first_output_ms:.2f}"
                        if first_output_ms
                        is not None
                        else "none"
                    ),
                    total_ms,
                    attempt,
                )

                # Successful request.
                return

            # =================================================
            # Cancellation
            # =================================================

            except asyncio.CancelledError:

                logger.info(
                    "hamsa_tts_stream_cancelled "
                    "attempt=%d "
                    "audio_yielded=%s",
                    attempt,
                    first_audio_yielded,
                )

                raise

            # =================================================
            # Transport failure
            # =================================================

            except httpx.TransportError as exc:

                can_retry = (
                    attempt < max_attempts
                    and not first_audio_yielded
                )

                logger.warning(
                    "hamsa_tts_transport_error "
                    "error_type=%s "
                    "attempt=%d "
                    "max_attempts=%d "
                    "audio_yielded=%s "
                    "can_retry=%s",
                    type(exc).__name__,
                    attempt,
                    max_attempts,
                    first_audio_yielded,
                    can_retry,
                )

                if not can_retry:
                    raise

                # Rebuild the HTTP client so attempt 2 cannot
                # inherit a broken pooled connection.

                await self._reset_http_client(
                    failed_client=client,
                )

                logger.info(
                    "hamsa_tts_retrying "
                    "next_attempt=%d "
                    "previous_error_type=%s",
                    attempt + 1,
                    type(exc).__name__,
                )

                continue

            # =================================================
            # Non-transport HTTP errors
            # =================================================

            except httpx.HTTPStatusError as exc:

                logger.error(
                    "hamsa_tts_http_status_failure "
                    "status=%s "
                    "attempt=%d",
                    (
                        exc.response.status_code
                        if exc.response is not None
                        else "unknown"
                    ),
                    attempt,
                )

                # Do NOT blindly retry 4xx/5xx responses here.
                #
                # Authentication, quota, payload and provider
                # errors should remain visible instead of
                # doubling requests.

                raise

            # =================================================
            # Unexpected failure
            # =================================================

            except Exception as exc:

                logger.error(
                    "hamsa_tts_stream_unexpected_failure "
                    "error_type=%s "
                    "attempt=%d "
                    "audio_yielded=%s",
                    type(exc).__name__,
                    attempt,
                    first_audio_yielded,
                    exc_info=True,
                )

                raise

        # Defensive safeguard.
        #
        # Normally every branch above either returns,
        # retries or raises.

        raise RuntimeError(
            "Hamsa TTS exhausted all attempts."
        )

    # ========================================================
    # Close
    # ========================================================

    async def aclose(
        self,
    ) -> None:

        await self._client.aclose()

        logger.info(
            "hamsa_tts_closed"
        )