from __future__ import annotations

import asyncio
import audioop
import logging
import os
import time
from collections.abc import AsyncIterator

import httpx

from voice_gateway.config import (
    load_environment,
)


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

        self.expressiveness = (
            expressiveness
        )

        # ====================================================
        # HTTP Client
        # ====================================================

        timeout_seconds = float(
            os.getenv(
                "HAMSA_TTS_TIMEOUT_SECONDS",
                "30",
            )
        )

        connect_timeout_seconds = float(
            os.getenv(
                "HAMSA_TTS_CONNECT_TIMEOUT_SECONDS",
                "10",
            )
        )

        self._client = (
            httpx.AsyncClient(
                timeout=httpx.Timeout(
                    timeout_seconds,
                    connect=
                        connect_timeout_seconds,
                ),
            )
        )

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
            "expressiveness=%d",
            self.speaker,
            self.dialect,
            INPUT_SAMPLE_RATE,
            OUTPUT_SAMPLE_RATE,
            self.expressiveness,
        )

    # ========================================================
    # Headers
    # ========================================================

    def _headers(
        self,
    ) -> dict[str, str]:

        return {
            "Authorization":
                f"Token {self.api_key}",

            "Content-Type":
                "application/json",
        }

    # ========================================================
    # Payload
    # ========================================================

    def _payload(
        self,
        text: str,
    ) -> dict[str, object]:

        return {
            "text":
                text,

            "speaker":
                self.speaker,

            "dialect":
                self.dialect,

            "mulaw":
                False,

            "sampleRate":
                "16k",

            "expressiveness":
                self.expressiveness,
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

            stream = (
                self.stream_pcm24k(
                    warmup_text
                )
            )

            try:

                # One playable frame is enough.
                # We do NOT need to synthesize/play the
                # whole warm-up utterance.
                first_chunk = (
                    await asyncio.wait_for(
                        anext(stream),
                        timeout=timeout_seconds,
                    )
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

        The method intentionally exposes the same interface used
        by the existing ElevenLabs streaming path:

            async for chunk in tts.stream_pcm24k(text)

        Important:

        Hamsa HTTP chunks are network chunks, not guaranteed
        PCM sample boundaries.

        We therefore preserve:
            - incomplete PCM16 byte
            - audioop ratecv state
            - incomplete Asterisk 20 ms frame
        """

        text = (
            text
            .strip()
        )

        if not text:

            return

        # ====================================================
        # State
        # ====================================================

        pcm16_carry = b""

        resample_state = None

        asterisk_buffer = bytearray()

        input_bytes = 0

        output_bytes = 0

        network_chunks = 0

        output_frames = 0

        first_network_at: (
            float | None
        ) = None

        first_output_at: (
            float | None
        ) = None

        started_at = (
            time.perf_counter()
        )

        # ====================================================
        # Request
        # ====================================================

        async with self._client.stream(
            "POST",
            HAMSA_TTS_STREAM_URL,
            json=self._payload(
                text
            ),
            headers=self._headers(),
        ) as response:

            headers_at = (
                time.perf_counter()
            )

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
                "dialect=%s",
                response.status_code,
                response.headers.get(
                    "content-type"
                ),
                headers_ms,
                self.speaker,
                self.dialect,
            )

            # =================================================
            # HTTP Error
            # =================================================

            if response.status_code != 200:

                error_body = (
                    await response.aread()
                )

                logger.error(
                    "hamsa_tts_http_error "
                    "status=%d "
                    "body_bytes=%d",
                    response.status_code,
                    len(
                        error_body
                    ),
                )

                response.raise_for_status()

            # =================================================
            # Stream
            # =================================================

            async for network_chunk in (
                response.aiter_bytes()
            ):

                if not network_chunk:
                    continue

                now = (
                    time.perf_counter()
                )

                network_chunks += 1

                input_bytes += (
                    len(
                        network_chunk
                    )
                )

                # =============================================
                # First network bytes
                # =============================================

                if first_network_at is None:

                    first_network_at = now

                    first_network_ms = (
                        first_network_at
                        - started_at
                    ) * 1000

                    logger.info(
                        "hamsa_tts_first_network_audio "
                        "first_ms=%.2f "
                        "chunk_bytes=%d",
                        first_network_ms,
                        len(
                            network_chunk
                        ),
                    )

                # =============================================
                # Restore PCM16 alignment
                #
                # Hamsa may return odd HTTP chunk sizes such
                # as 1369 bytes.
                #
                # PCM16 samples require 2 bytes.
                # =============================================

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
                        network_chunk[
                            -1:
                        ]
                    )

                    network_chunk = (
                        network_chunk[
                            :-1
                        ]
                    )

                if not network_chunk:
                    continue

                # =============================================
                # Stateful 16k -> 24k
                # =============================================

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

                # =============================================
                # Asterisk frame buffer
                # =============================================

                asterisk_buffer.extend(
                    converted_audio
                )

                # =============================================
                # Yield exact 20 ms slin24 frames
                #
                # 960 bytes = 20 ms @ PCM16 / 24k / mono
                # =============================================

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
                            "frame_bytes=%d",
                            first_output_ms,
                            len(
                                output_chunk
                            ),
                        )

                    output_frames += 1

                    output_bytes += (
                        len(
                            output_chunk
                        )
                    )

                    yield output_chunk

        # ====================================================
        # Final PCM16 validation
        # ====================================================

        if pcm16_carry:

            logger.warning(
                "hamsa_tts_incomplete_pcm16_sample "
                "trailing_bytes=%d",
                len(
                    pcm16_carry
                ),
            )

        # ====================================================
        # Flush final resampled audio
        #
        # Asterisk can accept the final partial frame.
        # ====================================================

        if asterisk_buffer:

            final_chunk = bytes(
                asterisk_buffer
            )

            output_frames += 1

            output_bytes += (
                len(
                    final_chunk
                )
            )

            if first_output_at is None:

                first_output_at = (
                    time.perf_counter()
                )

            yield final_chunk

        # ====================================================
        # Metrics
        # ====================================================

        completed_at = (
            time.perf_counter()
        )

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
            "total_ms=%.2f",
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