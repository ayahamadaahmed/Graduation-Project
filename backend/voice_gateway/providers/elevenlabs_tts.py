from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncIterator

import httpx


logger = logging.getLogger(
    "medmind.voice_gateway.elevenlabs_tts"
)


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
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        voice_id: str | None = None,
        model_id: str | None = None,
    ) -> None:

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

        # ----------------------------------------------------
        # Non-stream client
        # ----------------------------------------------------

        self._client = httpx.Client(
            timeout=httpx.Timeout(
                30.0,
                connect=5.0,
            )
        )

        # ----------------------------------------------------
        # True streaming client
        # ----------------------------------------------------

        self._async_client = (
            httpx.AsyncClient(
                timeout=httpx.Timeout(
                    30.0,
                    connect=5.0,
                )
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

        clean_text = text.strip()

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

            logger.exception(
                "elevenlabs_tts_network_error "
                "error_type=%s",
                type(exc).__name__,
            )

            raise

        if response.is_error:

            logger.error(
                "elevenlabs_tts_http_error "
                "status=%s "
                "body=%s",
                response.status_code,
                response.text,
            )

            response.raise_for_status()

        pcm24k = (
            response.content
        )

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

        IMPORTANT:
            We do NOT collect all chunks.
            Each chunk is yielded immediately.
        """

        clean_text = text.strip()

        if not clean_text:

            raise ValueError(
                "TTS text cannot be empty"
            )

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

        started_at = (
            time.perf_counter()
        )

        first_chunk_ms: float | None = None

        total_bytes = 0
        chunk_count = 0

        try:

            async with (
                self._async_client.stream(
                    "POST",
                    url,
                    headers=headers,
                    params=params,
                    json=payload,
                )
            ) as response:

                # --------------------------------------------
                # Read errors before entering media loop.
                # --------------------------------------------

                if response.is_error:

                    error_bytes = (
                        await response.aread()
                    )

                    error_text = (
                        error_bytes.decode(
                            "utf-8",
                            errors="replace",
                        )
                    )

                    logger.error(
                        "elevenlabs_tts_stream_"
                        "http_error "
                        "status=%s "
                        "body=%s",
                        response.status_code,
                        error_text,
                    )

                    response.raise_for_status()

                logger.info(
                    "elevenlabs_tts_stream_open "
                    "model=%s "
                    "content_type=%s",
                    self._model_id,
                    response.headers.get(
                        "content-type"
                    ),
                )

                # ============================================
                # TRUE STREAMING
                #
                # Use raw audio bytes and immediately yield
                # them to the caller.
                # ============================================

                async for chunk in (
                    response.aiter_raw()
                ):

                    if not chunk:
                        continue

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
                            "bytes=%d "
                            "first_chunk_ms=%.2f",
                            self._model_id,
                            len(chunk),
                            first_chunk_ms,
                        )

                    chunk_count += 1

                    total_bytes += (
                        len(chunk)
                    )

                    yield chunk

        except httpx.RequestError as exc:

            logger.exception(
                "elevenlabs_tts_stream_"
                "network_error "
                "error_type=%s",
                type(exc).__name__,
            )

            raise

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
            "chunks=%d "
            "bytes=%d "
            "first_chunk_ms=%.2f "
            "total_ms=%.2f",
            self._model_id,
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

    # ========================================================
    # Close
    # ========================================================

    def close(
        self,
    ) -> None:

        self._client.close()

    async def aclose(
        self,
    ) -> None:

        await self._async_client.aclose()