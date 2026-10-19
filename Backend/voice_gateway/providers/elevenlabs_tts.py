from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator

import httpx

from voice_gateway.log_safety import (
    exception_fields,
    install_log_safety,
)


logger = logging.getLogger(
    "medmind.voice_gateway.elevenlabs_tts"
)
install_log_safety(logger)


class ElevenLabsTTS:
    """
    ElevenLabs TTS provider.

    Supported modes:

    1. Non-stream:
        synthesize_pcm24k()

    2. True streaming:
        stream_pcm24k()

    Audio format:
        PCM16 signed little-endian
        mono
        24 kHz

    Compatible with:
        Asterisk slin24

    Streaming reliability:
        - Retry transient network failures only before
          the first audio chunk is emitted.
        - Never retry after audio playback has started,
          because replaying the request could duplicate
          spoken audio for the caller.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        voice_id: str | None = None,
        model_id: str | None = None,
    ) -> None:

        # ====================================================
        # Credentials / model configuration
        # ====================================================

        self._api_key = (
            api_key
            or os.getenv(
                "ELEVENLABS_API_KEY"
            )
        )

        self._voice_id = (
            voice_id
            or os.getenv(
                "ELEVENLABS_VOICE_ID"
            )
        )

        self._model_id = (
            model_id
            or os.getenv(
                "ELEVENLABS_MODEL_ID",
                "eleven_multilingual_v2",
            )
        )

        self._language_code = (
            os.getenv(
                "ELEVENLABS_LANGUAGE_CODE",
                "ar",
            )
        )

        self._output_format = (
            os.getenv(
                "ELEVENLABS_OUTPUT_FORMAT",
                "pcm_24000",
            )
        )

        if not self._api_key:

            raise RuntimeError(
                "ELEVENLABS_API_KEY is missing"
            )

        if not self._voice_id:

            raise RuntimeError(
                "ELEVENLABS_VOICE_ID is missing"
            )

        # ====================================================
        # Network reliability configuration
        # ====================================================

        self._connect_timeout_seconds = float(
            os.getenv(
                "ELEVENLABS_CONNECT_TIMEOUT_SECONDS",
                "3.0",
            )
        )

        self._stream_max_attempts = max(
            1,
            int(
                os.getenv(
                    "ELEVENLABS_STREAM_MAX_ATTEMPTS",
                    "2",
                )
            ),
        )

        self._stream_retry_delay_seconds = float(
            os.getenv(
                "ELEVENLABS_STREAM_RETRY_DELAY_SECONDS",
                "0.35",
            )
        )

        # ====================================================
        # Force IPv4
        #
        # Current network has a broken IPv6/NAT64 TLS path
        # to api.elevenlabs.io.
        #
        # Binding to 0.0.0.0 forces IPv4 sockets while
        # preserving normal DNS resolution.
        # ====================================================

        self._sync_transport = (
            httpx.HTTPTransport(
                local_address="0.0.0.0",
            )
        )

        self._async_transport = (
            httpx.AsyncHTTPTransport(
                local_address="0.0.0.0",
            )
        )

        # ====================================================
        # Non-stream client
        # ====================================================

        self._client = httpx.Client(
            transport=self._sync_transport,
            timeout=httpx.Timeout(
                30.0,
                connect=(
                    self._connect_timeout_seconds
                ),
            ),
        )

        # ====================================================
        # True streaming client
        # ====================================================

        self._async_client = (
            httpx.AsyncClient(
                transport=self._async_transport,
                timeout=httpx.Timeout(
                    30.0,
                    connect=(
                        self._connect_timeout_seconds
                    ),
                ),
            )
        )

    # ========================================================
    # Shared payload
    # ========================================================

    def _build_payload(
        self,
        text: str,
    ) -> dict:

        return {
            "text":
                text,

            "model_id":
                self._model_id,

            "language_code":
                self._language_code,

            "voice_settings": {

                "stability":
                    0.5,

                "similarity_boost":
                    0.75,

                "style":
                    0.0,

                "use_speaker_boost":
                    True,

                "speed":
                    1.0,
            },
        }

    # ========================================================
    # Non-stream TTS
    # ========================================================

    def synthesize_pcm24k(
        self,
        text: str,
    ) -> bytes:

        clean_text = (
            text.strip()
        )

        if not clean_text:

            raise ValueError(
                "TTS text cannot be empty"
            )

        url = (
            "https://api.elevenlabs.io"
            f"/v1/text-to-speech/"
            f"{self._voice_id}"
        )

        headers = {

            "xi-api-key":
                self._api_key,

            "Content-Type":
                "application/json",

            "Accept":
                "audio/pcm",
        }

        params = {

            "output_format":
                self._output_format,
        }

        payload = (
            self._build_payload(
                clean_text
            )
        )

        started_at = (
            time.perf_counter()
        )

        try:

            response = (
                self._client.post(
                    url,
                    headers=headers,
                    params=params,
                    json=payload,
                )
            )

        except httpx.RequestError as exc:

            logger.error(
                "elevenlabs_tts_network_error "
                "%s",
                exception_fields(),
            )

            raise

        # ====================================================
        # HTTP error handling
        # ====================================================

        if response.is_error:

            logger.error(
                "elevenlabs_tts_http_error "
                "status=%s "
                "body_bytes=%d",
                response.status_code,
                len(
                    response.content
                ),
            )

            response.raise_for_status()

        pcm24k = (
            response.content
        )

        # ====================================================
        # Validate PCM response
        # ====================================================

        if not pcm24k:

            raise RuntimeError(
                "ElevenLabs returned empty audio"
            )

        if (
            len(pcm24k) % 2
            != 0
        ):

            raise RuntimeError(
                "ElevenLabs returned invalid "
                "PCM16 byte alignment"
            )

        total_ms = (
            (
                time.perf_counter()
                - started_at
            )
            * 1000
        )

        duration_seconds = (
            len(pcm24k)
            / (
                24000
                * 2
            )
        )

        logger.info(
            "elevenlabs_tts_pcm24k_generated "
            "mode=non_stream "
            "model=%s "
            "text_chars=%d "
            "pcm24k_bytes=%d "
            "duration_seconds=%.2f "
            "total_ms=%.2f "
            "content_type=%s",
            self._model_id,
            len(clean_text),
            len(pcm24k),
            duration_seconds,
            total_ms,
            response.headers.get(
                "content-type"
            ),
        )

        return pcm24k

    # ========================================================
    # TRUE STREAMING TTS
    # ========================================================

    async def stream_pcm24k(
        self,
        text: str,
    ) -> AsyncIterator[bytes]:
        """
        Yield PCM audio progressively as ElevenLabs
        generates it.

        Reliability policy:

        1. If a transient network error happens before
           any audio is emitted, retry the request.

        2. If audio has already been emitted, never
           retry from the beginning.

           Retrying at that point could make the caller
           hear duplicated speech.

        3. HTTP errors are not automatically retried.
           Authentication errors, quota errors, invalid
           requests, etc. should reach the orchestrator.
        """

        clean_text = (
            text.strip()
        )

        if not clean_text:

            raise ValueError(
                "TTS text cannot be empty"
            )

        # ====================================================
        # Endpoint
        # ====================================================

        url = (
            "https://api.elevenlabs.io"
            f"/v1/text-to-speech/"
            f"{self._voice_id}"
            "/stream"
        )

        headers = {

            "xi-api-key":
                self._api_key,

            "Content-Type":
                "application/json",

            "Accept":
                "audio/pcm",
        }

        params = {

            "output_format":
                self._output_format,
        }

        payload = (
            self._build_payload(
                clean_text
            )
        )

        # ====================================================
        # Metrics
        # ====================================================

        started_at = (
            time.perf_counter()
        )

        first_chunk_ms: float | None = (
            None
        )

        total_bytes = 0
        chunk_count = 0

        # ====================================================
        # Bounded retry loop
        # ====================================================

        for attempt in range(
            1,
            self._stream_max_attempts + 1,
        ):

            audio_started = False
            pcm_remainder = b""

            try:

                logger.info(
                    "elevenlabs_tts_stream_attempt "
                    "model=%s "
                    "attempt=%d "
                    "max_attempts=%d "
                    "connect_timeout_seconds=%.2f",
                    self._model_id,
                    attempt,
                    self._stream_max_attempts,
                    self._connect_timeout_seconds,
                )

                async with (
                    self._async_client.stream(
                        "POST",
                        url,
                        headers=headers,
                        params=params,
                        json=payload,
                    )
                ) as response:

                    # ========================================
                    # HTTP error handling
                    #
                    # Read body before entering media loop.
                    # ========================================

                    if response.is_error:

                        error_bytes = (
                            await response.aread()
                        )

                        logger.error(
                            "elevenlabs_tts_stream_http_error "
                            "status=%s "
                            "body_bytes=%d",
                            response.status_code,
                            len(
                                error_bytes
                            ),
                        )

                        response.raise_for_status()

                    logger.info(
                        "elevenlabs_tts_stream_open "
                        "model=%s "
                        "attempt=%d "
                        "content_type=%s",
                        self._model_id,
                        attempt,
                        response.headers.get(
                            "content-type"
                        ),
                    )

                    async for chunk in (
                        response.aiter_raw()
                    ):

                        if not chunk:
                            continue

                        # HTTP chunk boundaries are not guaranteed
                        # to match PCM16 sample boundaries.
                        combined = (
                            pcm_remainder
                            + chunk
                        )

                        aligned_length = (
                            len(combined)
                            - (
                                len(combined)
                                % 2
                            )
                        )

                        if aligned_length == 0:

                            pcm_remainder = (
                                combined
                            )

                            continue

                        pcm_chunk = (
                            combined[
                                :aligned_length
                            ]
                        )

                        pcm_remainder = (
                            combined[
                                aligned_length:
                            ]
                        )

                        audio_started = True

                        if (
                            first_chunk_ms
                            is None
                        ):

                            first_chunk_ms = (
                                (
                                    time.perf_counter()
                                    - started_at
                                )
                                * 1000
                            )

                            logger.info(
                                "elevenlabs_tts_"
                                "first_chunk "
                                "model=%s "
                                "attempt=%d "
                                "bytes=%d "
                                "first_chunk_ms=%.2f",
                                self._model_id,
                                attempt,
                                len(
                                    pcm_chunk
                                ),
                                first_chunk_ms,
                            )

                        chunk_count += 1

                        total_bytes += (
                            len(
                                pcm_chunk
                            )
                        )

                        yield pcm_chunk
   
                if pcm_remainder:

                    raise RuntimeError(
                        "ElevenLabs returned "
                        "misaligned PCM16 stream"
                    )
                # ============================================
                # Streaming request ended cleanly.
                # ============================================

                if not audio_started:

                    raise RuntimeError(
                        "ElevenLabs returned "
                        "an empty audio stream"
                    )

                total_ms = (
                    (
                        time.perf_counter()
                        - started_at
                    )
                    * 1000
                )

                logger.info(
                    "elevenlabs_tts_stream_completed "
                    "model=%s "
                    "attempt=%d "
                    "chunks=%d "
                    "bytes=%d "
                    "first_chunk_ms=%.2f "
                    "total_ms=%.2f",
                    self._model_id,
                    attempt,
                    chunk_count,
                    total_bytes,
                    (
                        first_chunk_ms
                        if first_chunk_ms
                        is not None
                        else -1.0
                    ),
                    total_ms,
                )

                # Streaming completed successfully.
                return

            # =================================================
            # Transient network failures
            # =================================================

            except httpx.RequestError as exc:

                # --------------------------------------------
                # Audio already reached the caller.
                #
                # NEVER retry from the beginning.
                # --------------------------------------------

                if audio_started:

                    logger.error(
                        "elevenlabs_tts_stream_"
                        "network_error_after_audio "
                        "attempt=%d "
                        "retry=false "
                        "%s",
                        attempt,
                        exception_fields(),
                    )

                    raise

                # --------------------------------------------
                # No audio emitted.
                #
                # Retry is safe from the caller's perspective.
                # --------------------------------------------

                if (
                    attempt
                    >= self._stream_max_attempts
                ):

                    logger.error(
                        "elevenlabs_tts_stream_"
                        "network_error "
                        "attempt=%d "
                        "max_attempts=%d "
                        "retry=false "
                        "%s",
                        attempt,
                        self._stream_max_attempts,
                        exception_fields(),
                    )

                    raise

                retry_delay = (
                    self._stream_retry_delay_seconds
                    * attempt
                )

                logger.warning(
                    "elevenlabs_tts_stream_"
                    "network_retry "
                    "error_type=%s "
                    "attempt=%d "
                    "next_attempt=%d "
                    "delay_seconds=%.2f",
                    type(exc).__name__,
                    attempt,
                    attempt + 1,
                    retry_delay,
                )

                await asyncio.sleep(
                    retry_delay
                )

        # ====================================================
        # Defensive fallback
        #
        # Normally unreachable.
        # ====================================================

        raise RuntimeError(
            "ElevenLabs stream exited "
            "without completing"
        )

    # ========================================================
    # Close synchronous client
    # ========================================================

    def close(
        self,
    ) -> None:

        self._client.close()

    # ========================================================
    # Close asynchronous client
    # ========================================================

    async def aclose(
        self,
    ) -> None:

        await (
            self._async_client.aclose()
        )