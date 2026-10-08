from __future__ import annotations

import math
import struct

import pytest

from voice_gateway.audio.codec import (
    StreamingPCM16Resampler,
    create_slin24_vad_resampler,
    pcm16_24k_to_ulaw8k,
    slin24_to_pcm16_8k,
    ulaw_to_pcm16,
)


def make_pcm16_tone(
    *,
    sample_rate: int,
    duration_ms: int,
    frequency_hz: float = 440.0,
) -> bytes:

    sample_count = int(
        sample_rate
        * duration_ms
        / 1000
    )

    samples = []

    for index in range(
        sample_count
    ):
        value = int(
            10000
            * math.sin(
                2
                * math.pi
                * frequency_hz
                * index
                / sample_rate
            )
        )

        samples.append(
            struct.pack(
                "<h",
                value,
            )
        )

    return b"".join(
        samples
    )


def test_slin24_20ms_becomes_8k_20ms(
) -> None:

    audio = make_pcm16_tone(
        sample_rate=24000,
        duration_ms=20,
    )

    converted = (
        slin24_to_pcm16_8k(
            audio
        )
    )

    # 8 kHz * 20 ms = 160 samples
    # 160 PCM16 samples = 320 bytes
    assert len(converted) == 320


def test_streaming_resampler_matches_whole_buffer(
) -> None:

    audio = make_pcm16_tone(
        sample_rate=24000,
        duration_ms=100,
    )

    expected = (
        slin24_to_pcm16_8k(
            audio
        )
    )

    resampler = (
        create_slin24_vad_resampler()
    )

    frame_bytes = 960

    output = bytearray()

    for offset in range(
        0,
        len(audio),
        frame_bytes,
    ):
        output.extend(
            resampler.convert(
                audio[
                    offset:
                    offset + frame_bytes
                ]
            )
        )

    assert bytes(output) == expected


def test_streaming_resampler_reset(
) -> None:

    audio = make_pcm16_tone(
        sample_rate=24000,
        duration_ms=40,
    )

    resampler = (
        create_slin24_vad_resampler()
    )

    first = resampler.convert(
        audio
    )

    resampler.reset()

    second = resampler.convert(
        audio
    )

    assert first == second


def test_resampler_rejects_invalid_rate(
) -> None:

    with pytest.raises(
        ValueError
    ):
        StreamingPCM16Resampler(
            input_rate=0,
            output_rate=8000,
        )


def test_pcm16_rejects_odd_byte_length(
) -> None:

    with pytest.raises(
        ValueError
    ):
        slin24_to_pcm16_8k(
            b"\x00"
        )


def test_ulaw_conversion_empty_input(
) -> None:

    assert (
        ulaw_to_pcm16(
            b""
        )
        == b""
    )


def test_tts_conversion_empty_input(
) -> None:

    assert (
        pcm16_24k_to_ulaw8k(
            b""
        )
        == b""
    )