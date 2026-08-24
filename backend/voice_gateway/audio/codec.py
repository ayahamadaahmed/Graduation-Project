from __future__ import annotations

import audioop


ULAW_SAMPLE_RATE = 8000
PCM_SAMPLE_WIDTH = 2

GEMINI_SAMPLE_RATE = 24000
SLIN24_SAMPLE_RATE = 24000



def slin24_to_pcm16_8k(
    audio: bytes,
) -> bytes:
    """
    Convert Asterisk slin24 PCM16 audio
    to PCM16 8 kHz for the current
    Silero VAD pipeline.
    """

    if not audio:
        return b""

    pcm8k, _ = audioop.ratecv(
        audio,
        PCM_SAMPLE_WIDTH,
        1,
        SLIN24_SAMPLE_RATE,
        ULAW_SAMPLE_RATE,
        None,
    )

    return pcm8k



def ulaw_to_pcm16(
    audio: bytes,
) -> bytes:
    """
    Convert G.711 μ-law 8 kHz audio from Asterisk
    to PCM16 audio for Silero VAD.
    """

    if not audio:
        return b""

    return audioop.ulaw2lin(
        audio,
        PCM_SAMPLE_WIDTH,
    )


def pcm16_24k_to_ulaw8k(
    audio: bytes,
) -> bytes:
    """
    Convert Gemini PCM16 mono 24 kHz audio
    to Asterisk G.711 μ-law mono 8 kHz.
    """

    if not audio:
        return b""

    pcm8k, _ = audioop.ratecv(
        audio,
        PCM_SAMPLE_WIDTH,
        1,
        GEMINI_SAMPLE_RATE,
        ULAW_SAMPLE_RATE,
        None,
    )

    return audioop.lin2ulaw(
        pcm8k,
        PCM_SAMPLE_WIDTH,
    )
