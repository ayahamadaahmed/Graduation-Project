from __future__ import annotations

import base64
import logging
import os

from google import genai

from voice_gateway.audio.codec import (
    pcm16_24k_to_ulaw8k,
)


logger = logging.getLogger(
    "medmind.voice_gateway.gemini_tts"
)


class GeminiTTS:
    """
    Gemini TTS provider for MedMind Voice.

    Output:
        G.711 μ-law
        mono
        8 kHz
        ready for Asterisk chan_websocket
    """

    def __init__(
        self,
        *,
        voice: str = "Kore",
    ) -> None:
        api_key = os.getenv(
            "GEMINI_API_KEY"
        )

        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not configured"
            )

        self._client = genai.Client(
            api_key=api_key,
        )

        self._voice = voice

    def synthesize_pcm24k(
    self,
    text: str,
) -> bytes:
        text = text.strip()

        if not text:
            raise ValueError(
                "TTS text cannot be empty"
            )

        interaction = (
            self._client.interactions.create(
                model=(
                    "gemini-3.1-flash-tts-preview"
                ),
                input=text,
                response_format={
                    "type": "audio",
                },
                generation_config={
                    "speech_config": [
                        {
                            "voice": self._voice,
                        }
                    ],
                },
            )
        )

        output_audio = (
            interaction.output_audio
        )

        if output_audio is None:
            raise RuntimeError(
                "Gemini returned no audio"
            )

        pcm24k = base64.b64decode(
            output_audio.data
        )

        logger.info(
            "gemini_tts_pcm24k_generated "
            "text_chars=%d pcm24k_bytes=%d",
            len(text),
            len(pcm24k),
        )

        return pcm24k


    def synthesize_ulaw(
        self,
        text: str,
    ) -> bytes:
        pcm24k = self.synthesize_pcm24k(
            text
        )

        ulaw8k = pcm16_24k_to_ulaw8k(
            pcm24k
        )

        logger.info(
            "gemini_tts_ulaw_generated "
            "pcm24k_bytes=%d "
            "ulaw8k_bytes=%d",
            len(pcm24k),
            len(ulaw8k),
        )

        return ulaw8k