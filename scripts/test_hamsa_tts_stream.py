from __future__ import annotations

import io
import os
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


import httpx

from voice_gateway.config import (
    load_environment,
)


load_environment()


# ============================================================
# Configuration
# ============================================================

HAMSA_TTS_STREAM_URL = (
    "https://api.tryhamsa.com/v1/realtime/tts-stream"
)

HAMSA_TTS_SPEAKER = "Samir"

HAMSA_TTS_DIALECT = "egy"

HAMSA_TTS_SAMPLE_RATE = "16k"

HAMSA_TTS_SAMPLE_RATE_HZ = 16000


# PCM16:
#
# 16,000 samples / second
# 2 bytes / sample
# 20 ms audio frame
#
# 16000 * 0.020 * 2 = 640 bytes
#
PLAYABLE_FRAME_BYTES = 640


TEST_TEXT = (
    "تمام، المواعيد المتاحة يوم السبت، "
    "الساعة اتناشر الضهر، "
    "واتناشر ونص الضهر."
)


# ============================================================
# WAV Helper
# ============================================================

def pcm16_to_wav(
    pcm16_audio: bytes,
    *,
    sample_rate: int,
) -> bytes:

    buffer = io.BytesIO()

    with wave.open(
        buffer,
        "wb",
    ) as wav_file:

        wav_file.setnchannels(
            1
        )

        wav_file.setsampwidth(
            2
        )

        wav_file.setframerate(
            sample_rate
        )

        wav_file.writeframes(
            pcm16_audio
        )

    return buffer.getvalue()


# ============================================================
# Main
# ============================================================

def main() -> None:

    # ========================================================
    # API Key
    # ========================================================

    api_key = (
        os.getenv(
            "HAMSA_API_KEY",
            "",
        )
        .strip()
    )

    if not api_key:

        raise RuntimeError(
            "HAMSA_API_KEY is not configured."
        )

    # ========================================================
    # Output
    # ========================================================

    output_dir = (
        PROJECT_ROOT
        / "artifacts"
        / "hamsa_tts"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        output_dir
        / "samir_stream_test.wav"
    )

    # ========================================================
    # Request
    # ========================================================

    payload = {
        "text":
            TEST_TEXT,

        "speaker":
            HAMSA_TTS_SPEAKER,

        "dialect":
            HAMSA_TTS_DIALECT,

        "mulaw":
            False,

        "sampleRate":
            HAMSA_TTS_SAMPLE_RATE,

        "expressiveness":
            1,
    }

    headers = {
        "Authorization":
            f"Token {api_key}",

        "Content-Type":
            "application/json",
    }

    # ========================================================
    # Start
    # ========================================================

    print(
        "HAMSA_TTS_STREAM_TEST_START"
    )

    print(
        f"speaker={HAMSA_TTS_SPEAKER}"
    )

    print(
        f"dialect={HAMSA_TTS_DIALECT}"
    )

    print(
        f"sample_rate={HAMSA_TTS_SAMPLE_RATE}"
    )

    print(
        f"playable_frame_bytes={PLAYABLE_FRAME_BYTES}"
    )

    print(
        "----------------------------------------"
    )

    started_at = (
        time.perf_counter()
    )

    # ========================================================
    # Timing State
    # ========================================================

    first_response_at: float | None = None

    first_playable_audio_at: float | None = None

    # ========================================================
    # Audio State
    # ========================================================

    chunks: list[bytes] = []

    chunk_sizes: list[int] = []

    playable_buffer = bytearray()

    chunk_count = 0

    # ========================================================
    # HTTP Streaming Request
    # ========================================================

    with httpx.Client(
        timeout=httpx.Timeout(
            30.0,
            connect=10.0,
        ),
    ) as client:

        with client.stream(
            "POST",
            HAMSA_TTS_STREAM_URL,
            json=payload,
            headers=headers,
        ) as response:

            # ==================================================
            # Response Headers
            # ==================================================

            headers_received_at = (
                time.perf_counter()
            )

            headers_ms = (
                headers_received_at
                - started_at
            ) * 1000

            print(
                f"status_code={response.status_code}"
            )

            print(
                "content_type="
                f"{response.headers.get('content-type')}"
            )

            print(
                "transfer_encoding="
                f"{response.headers.get('transfer-encoding')}"
            )

            print(
                f"headers_ms={headers_ms:.2f}"
            )

            print(
                "----------------------------------------"
            )

            # ==================================================
            # Error Handling
            # ==================================================

            if response.status_code != 200:

                error_body = (
                    response.read()
                )

                print(
                    "HAMSA_TTS_STREAM_FAILED"
                )

                print(
                    error_body.decode(
                        "utf-8",
                        errors="replace",
                    )
                )

                response.raise_for_status()

            # ==================================================
            # Stream Audio
            # ==================================================

            for chunk in response.iter_bytes():

                if not chunk:
                    continue

                now = (
                    time.perf_counter()
                )

                chunk_length = (
                    len(chunk)
                )

                chunk_sizes.append(
                    chunk_length
                )

                # ==============================================
                # First HTTP/audio bytes received
                #
                # IMPORTANT:
                #
                # This does NOT necessarily mean we already
                # have enough PCM for playback.
                # ==============================================

                if first_response_at is None:

                    first_response_at = now

                    first_response_ms = (
                        first_response_at
                        - started_at
                    ) * 1000

                    print(
                        "FIRST_RESPONSE_BYTES"
                    )

                    print(
                        f"first_response_ms="
                        f"{first_response_ms:.2f}"
                    )

                    print(
                        f"first_chunk_bytes="
                        f"{chunk_length}"
                    )

                    print(
                        "first_chunk_hex="
                        f"{chunk[:32].hex()}"
                    )

                    print(
                        "----------------------------------------"
                    )

                # ==============================================
                # First Playable PCM Frame
                #
                # PCM16 mono @ 16 kHz:
                #
                # 20 ms = 640 bytes
                #
                # Tiny network chunks are accumulated until
                # there is enough PCM for one playable frame.
                # ==============================================

                if first_playable_audio_at is None:

                    playable_buffer.extend(
                        chunk
                    )

                    if (
                        len(playable_buffer)
                        >= PLAYABLE_FRAME_BYTES
                    ):

                        first_playable_audio_at = (
                            now
                        )

                        first_playable_ms = (
                            first_playable_audio_at
                            - started_at
                        ) * 1000

                        print(
                            "FIRST_PLAYABLE_AUDIO"
                        )

                        print(
                            f"first_playable_ms="
                            f"{first_playable_ms:.2f}"
                        )

                        print(
                            "playable_buffer_bytes="
                            f"{len(playable_buffer)}"
                        )

                        print(
                            "----------------------------------------"
                        )

                # ==============================================
                # Store Complete Stream
                # ==============================================

                chunks.append(
                    chunk
                )

                chunk_count += 1

    # ========================================================
    # Stream Completed
    # ========================================================

    completed_at = (
        time.perf_counter()
    )

    total_ms = (
        completed_at
        - started_at
    ) * 1000

    audio_data = b"".join(
        chunks
    )

    # ========================================================
    # Statistics
    # ========================================================

    print(
        "STREAM_STATISTICS"
    )

    print(
        f"chunk_count={chunk_count}"
    )

    print(
        f"stream_bytes={len(audio_data)}"
    )

    print(
        f"total_ms={total_ms:.2f}"
    )

    if chunk_sizes:

        print(
            "first_10_chunk_sizes="
            f"{chunk_sizes[:10]}"
        )

        print(
            "min_chunk_bytes="
            f"{min(chunk_sizes)}"
        )

        print(
            "max_chunk_bytes="
            f"{max(chunk_sizes)}"
        )

        average_chunk_size = (
            sum(chunk_sizes)
            / len(chunk_sizes)
        )

        print(
            "average_chunk_bytes="
            f"{average_chunk_size:.2f}"
        )

    # ========================================================
    # First Response Timing
    # ========================================================

    if first_response_at is not None:

        first_response_ms = (
            first_response_at
            - started_at
        ) * 1000

        print(
            f"first_response_ms="
            f"{first_response_ms:.2f}"
        )

    else:

        print(
            "first_response_ms=None"
        )

    # ========================================================
    # First Playable Timing
    # ========================================================

    if first_playable_audio_at is not None:

        first_playable_ms = (
            first_playable_audio_at
            - started_at
        ) * 1000

        print(
            f"first_playable_ms="
            f"{first_playable_ms:.2f}"
        )

    else:

        print(
            "first_playable_ms=None"
        )

    print(
        "----------------------------------------"
    )

    # ========================================================
    # Detect WAV Header
    #
    # Hamsa currently reports:
    #
    # content-type=audio/wav
    #
    # but the streaming body we observed did not start with
    # RIFF/WAVE, so we verify instead of trusting the header.
    # ========================================================

    already_wav = (
        len(audio_data) >= 12
        and
        audio_data[0:4] == b"RIFF"
        and
        audio_data[8:12] == b"WAVE"
    )

    print(
        f"already_wav={already_wav}"
    )

    # ========================================================
    # PCM Alignment
    #
    # PCM16 requires an even number of bytes.
    # ========================================================

    pcm16_aligned = (
        len(audio_data) % 2 == 0
    )

    print(
        f"pcm16_byte_aligned={pcm16_aligned}"
    )

    if (
        not already_wav
        and
        not pcm16_aligned
    ):

        print(
            "WARNING: Raw audio byte count is not "
            "aligned to PCM16 samples."
        )

    # ========================================================
    # Write WAV
    # ========================================================

    if already_wav:

        wav_data = (
            audio_data
        )

    else:

        wav_data = (
            pcm16_to_wav(
                audio_data,
                sample_rate=
                    HAMSA_TTS_SAMPLE_RATE_HZ,
            )
        )

    output_path.write_bytes(
        wav_data
    )

    # ========================================================
    # Final Result
    # ========================================================

    print(
        "----------------------------------------"
    )

    print(
        "HAMSA_TTS_STREAM_OK"
    )

    print(
        f"saved_to={output_path}"
    )


# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":

    main()