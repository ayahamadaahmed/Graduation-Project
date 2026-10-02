from __future__ import annotations

import asyncio
import sys
import time
import wave

from pathlib import Path


# ============================================================
# Project Root
# ============================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


from voice_gateway.providers.hamsa_tts import (
    HamsaTTS,
)


# ============================================================
# Configuration
# ============================================================

OUTPUT_SAMPLE_RATE = 24000

CHANNELS = 1

SAMPLE_WIDTH = 2

ASTERISK_FRAME_BYTES = 960


TEST_TEXT = (
    "تمام، المواعيد المتاحة يوم السبت، "
    "الساعة اتناشر الضهر، "
    "واتناشر ونص الضهر."
)


OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts"
    / "hamsa_tts"
    / "hamsa_provider_24k_test.wav"
)


# ============================================================
# Write WAV
# ============================================================

def write_pcm24k_wav(
    path: Path,
    pcm_audio: bytes,
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with wave.open(
        str(path),
        "wb",
    ) as wav_file:

        wav_file.setnchannels(
            CHANNELS
        )

        wav_file.setsampwidth(
            SAMPLE_WIDTH
        )

        wav_file.setframerate(
            OUTPUT_SAMPLE_RATE
        )

        wav_file.writeframes(
            pcm_audio
        )


# ============================================================
# Test
# ============================================================

async def main() -> None:

    print(
        "HAMSA_TTS_PROVIDER_TEST_START"
    )

    tts = HamsaTTS(
        speaker="Samir",
        dialect="egy",
    )

    chunks: list[bytes] = []

    chunk_sizes: list[int] = []

    first_chunk_at: float | None = None

    started_at = (
        time.perf_counter()
    )

    try:

        async for chunk in tts.stream_pcm24k(
            TEST_TEXT
        ):

            if not chunk:
                continue

            now = (
                time.perf_counter()
            )

            if first_chunk_at is None:

                first_chunk_at = now

                first_chunk_ms = (
                    first_chunk_at
                    - started_at
                ) * 1000

                print(
                    "FIRST_PROVIDER_AUDIO"
                )

                print(
                    f"first_chunk_ms="
                    f"{first_chunk_ms:.2f}"
                )

            chunks.append(
                chunk
            )

            chunk_sizes.append(
                len(chunk)
            )

    finally:

        await tts.aclose()

    completed_at = (
        time.perf_counter()
    )

    total_ms = (
        completed_at
        - started_at
    ) * 1000

    # ========================================================
    # Validate Output
    # ========================================================

    if not chunks:

        raise RuntimeError(
            "HamsaTTS produced no audio chunks."
        )

    print(
        "----------------------------------------"
    )

    print(
        "PROVIDER_STREAM_STATISTICS"
    )

    print(
        f"chunk_count={len(chunks)}"
    )

    print(
        f"first_10_chunk_sizes="
        f"{chunk_sizes[:10]}"
    )

    print(
        f"min_chunk_bytes="
        f"{min(chunk_sizes)}"
    )

    print(
        f"max_chunk_bytes="
        f"{max(chunk_sizes)}"
    )

    print(
        f"total_ms={total_ms:.2f}"
    )

    # ========================================================
    # Frame Validation
    #
    # Every chunk except possibly the last one should be
    # exactly 960 bytes:
    #
    # PCM16 mono @ 24kHz
    # 20 ms = 960 bytes
    # ========================================================

    full_frames = (
        chunk_sizes[:-1]
    )

    invalid_full_frames = [
        size
        for size in full_frames
        if size != ASTERISK_FRAME_BYTES
    ]

    if invalid_full_frames:

        raise RuntimeError(
            "Invalid Asterisk frame sizes found: "
            f"{invalid_full_frames[:10]}"
        )

    final_chunk_size = (
        chunk_sizes[-1]
    )

    if not (
        0
        < final_chunk_size
        <= ASTERISK_FRAME_BYTES
    ):

        raise RuntimeError(
            "Invalid final chunk size: "
            f"{final_chunk_size}"
        )

    print(
        f"full_frames_valid="
        f"{len(invalid_full_frames) == 0}"
    )

    print(
        f"final_chunk_bytes="
        f"{final_chunk_size}"
    )

    # ========================================================
    # PCM Validation
    # ========================================================

    pcm_audio = b"".join(
        chunks
    )

    if len(pcm_audio) % SAMPLE_WIDTH != 0:

        raise RuntimeError(
            "Output PCM is not aligned to PCM16 samples."
        )

    sample_count = (
        len(pcm_audio)
        // SAMPLE_WIDTH
    )

    duration_seconds = (
        sample_count
        / OUTPUT_SAMPLE_RATE
    )

    print(
        f"pcm_bytes={len(pcm_audio)}"
    )

    print(
        f"sample_count={sample_count}"
    )

    print(
        f"duration_seconds="
        f"{duration_seconds:.3f}"
    )

    # ========================================================
    # Save WAV
    # ========================================================

    write_pcm24k_wav(
        OUTPUT_PATH,
        pcm_audio,
    )

    print(
        "----------------------------------------"
    )

    print(
        "HAMSA_TTS_PROVIDER_TEST_OK"
    )

    print(
        f"saved_to={OUTPUT_PATH}"
    )


# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )