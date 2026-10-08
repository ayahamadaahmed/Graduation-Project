from __future__ import annotations

import audioop
import sys
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


# ============================================================
# Configuration
# ============================================================

INPUT_SAMPLE_RATE = 16000

OUTPUT_SAMPLE_RATE = 24000

CHANNELS = 1

SAMPLE_WIDTH = 2  # PCM16


INPUT_PATH = (
    PROJECT_ROOT
    / "artifacts"
    / "hamsa_tts"
    / "samir_stream_test.wav"
)


OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts"
    / "hamsa_tts"
    / "samir_stream_test_24k.wav"
)


# ============================================================
# Read WAV
# ============================================================

def read_pcm16_wav(
    path: Path,
) -> tuple[bytes, int]:

    with wave.open(
        str(path),
        "rb",
    ) as wav_file:

        channels = (
            wav_file.getnchannels()
        )

        sample_width = (
            wav_file.getsampwidth()
        )

        sample_rate = (
            wav_file.getframerate()
        )

        frame_count = (
            wav_file.getnframes()
        )

        print(
            f"input_channels={channels}"
        )

        print(
            f"input_sample_width={sample_width}"
        )

        print(
            f"input_sample_rate={sample_rate}"
        )

        print(
            f"input_frames={frame_count}"
        )

        if channels != CHANNELS:

            raise RuntimeError(
                f"Expected mono audio, got {channels} channels."
            )

        if sample_width != SAMPLE_WIDTH:

            raise RuntimeError(
                f"Expected PCM16, got sample width "
                f"{sample_width} bytes."
            )

        pcm_audio = (
            wav_file.readframes(
                frame_count
            )
        )

    return (
        pcm_audio,
        sample_rate,
    )


# ============================================================
# Stateful Resample Simulation
# ============================================================

def resample_pcm16_stream(
    pcm16_audio: bytes,
    *,
    input_rate: int,
    output_rate: int,
    chunk_size: int = 1369,
) -> bytes:

    """
    Simulate the real Hamsa streaming case.

    Hamsa HTTP chunks may contain an odd number of bytes.
    PCM16 samples require exactly 2 bytes per sample.

    Therefore:
    - preserve incomplete trailing byte
    - prepend it to the next HTTP chunk
    - use audioop.ratecv state across chunks
    """

    output_chunks: list[bytes] = []

    ratecv_state = None

    carry = b""

    offset = 0

    simulated_chunk_count = 0

    while offset < len(pcm16_audio):

        chunk = (
            pcm16_audio[
                offset:
                offset + chunk_size
            ]
        )

        offset += chunk_size

        simulated_chunk_count += 1

        # ====================================================
        # Add leftover byte from previous chunk
        # ====================================================

        if carry:

            chunk = (
                carry
                + chunk
            )

            carry = b""

        # ====================================================
        # PCM16 requires complete 2-byte samples
        # ====================================================

        if len(chunk) % 2 != 0:

            carry = (
                chunk[-1:]
            )

            chunk = (
                chunk[:-1]
            )

        if not chunk:

            continue

        # ====================================================
        # Stateful 16k -> 24k conversion
        # ====================================================

        converted, ratecv_state = (
            audioop.ratecv(
                chunk,
                SAMPLE_WIDTH,
                CHANNELS,
                input_rate,
                output_rate,
                ratecv_state,
            )
        )

        if converted:

            output_chunks.append(
                converted
            )

    # ========================================================
    # There should not normally be an incomplete PCM16 sample
    # at the end of the complete stream.
    # ========================================================

    if carry:

        print(
            "WARNING: incomplete trailing PCM16 byte "
            f"remaining={len(carry)}"
        )

    print(
        f"simulated_chunk_count={simulated_chunk_count}"
    )

    print(
        f"trailing_carry_bytes={len(carry)}"
    )

    return b"".join(
        output_chunks
    )


# ============================================================
# Write WAV
# ============================================================

def write_pcm16_wav(
    path: Path,
    pcm16_audio: bytes,
    *,
    sample_rate: int,
) -> None:

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
            sample_rate
        )

        wav_file.writeframes(
            pcm16_audio
        )


# ============================================================
# Main
# ============================================================

def main() -> None:

    print(
        "HAMSA_RESAMPLE_TEST_START"
    )

    print(
        f"input_path={INPUT_PATH}"
    )

    print(
        f"output_path={OUTPUT_PATH}"
    )

    print(
        "----------------------------------------"
    )

    if not INPUT_PATH.exists():

        raise FileNotFoundError(
            f"Input file not found: {INPUT_PATH}"
        )

    # ========================================================
    # Read
    # ========================================================

    input_pcm, actual_sample_rate = (
        read_pcm16_wav(
            INPUT_PATH
        )
    )

    if (
        actual_sample_rate
        != INPUT_SAMPLE_RATE
    ):

        raise RuntimeError(
            f"Expected {INPUT_SAMPLE_RATE} Hz, "
            f"got {actual_sample_rate} Hz."
        )

    print(
        f"input_pcm_bytes={len(input_pcm)}"
    )

    input_samples = (
        len(input_pcm)
        // SAMPLE_WIDTH
    )

    input_duration = (
        input_samples
        / INPUT_SAMPLE_RATE
    )

    print(
        f"input_duration_seconds="
        f"{input_duration:.3f}"
    )

    print(
        "----------------------------------------"
    )

    # ========================================================
    # Resample
    # ========================================================

    output_pcm = (
        resample_pcm16_stream(
            input_pcm,
            input_rate=
                INPUT_SAMPLE_RATE,
            output_rate=
                OUTPUT_SAMPLE_RATE,

            # Deliberately odd-sized to reproduce
            # the Hamsa HTTP stream behavior.
            chunk_size=1369,
        )
    )

    # ========================================================
    # Output Statistics
    # ========================================================

    output_samples = (
        len(output_pcm)
        // SAMPLE_WIDTH
    )

    output_duration = (
        output_samples
        / OUTPUT_SAMPLE_RATE
    )

    print(
        f"output_pcm_bytes={len(output_pcm)}"
    )

    print(
        f"output_samples={output_samples}"
    )

    print(
        f"output_duration_seconds="
        f"{output_duration:.3f}"
    )

    duration_difference_ms = (
        abs(
            output_duration
            - input_duration
        )
        * 1000
    )

    print(
        f"duration_difference_ms="
        f"{duration_difference_ms:.3f}"
    )

    print(
        "----------------------------------------"
    )

    # ========================================================
    # Write
    # ========================================================

    write_pcm16_wav(
        OUTPUT_PATH,
        output_pcm,
        sample_rate=
            OUTPUT_SAMPLE_RATE,
    )

    print(
        "HAMSA_RESAMPLE_TEST_OK"
    )

    print(
        f"saved_to={OUTPUT_PATH}"
    )


# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":

    main()