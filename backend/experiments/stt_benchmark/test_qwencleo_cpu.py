from __future__ import annotations

import time
import wave
from pathlib import Path

import torch
from qwencleo_asr import QwenCleoASR


AUDIO_PATH = Path(
    "experiments/stt_benchmark/v0_1/audio/legacy_cancel_test.wav"
)


def get_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / wav.getframerate()


def main() -> None:

    if not AUDIO_PATH.exists():
        raise FileNotFoundError(AUDIO_PATH)

    duration = get_duration(AUDIO_PATH)

    print()
    print("=" * 60)
    print("QwenCleo-ASR Egyptian Benchmark")
    print("=" * 60)

    print(f"Audio:    {AUDIO_PATH}")
    print(f"Duration: {duration:.3f} sec")
    print(f"CUDA:     {torch.cuda.is_available()}")
    print("Device:   CPU")
    print("Expected: عايز ألغي الحجز")

    print()
    print("Loading / first transcription...")
    print("First run can download the model and take a long time.")
    print()

    # QwenCleo defaults to a CUDA device,
    # so we explicitly force CPU.
    asr = QwenCleoASR(
        device="cpu",
        dtype="float32",
        default_language="Arabic",
    )

    # --------------------------------------------------------
    # First call
    # Includes lazy model loading.
    # --------------------------------------------------------

    first_started = time.perf_counter()

    first_result = asr.transcribe(
        str(AUDIO_PATH),
        normalize=False,
    )

    first_elapsed = (
        time.perf_counter()
        - first_started
    )

    print()
    print("=" * 60)
    print("FIRST RESULT")
    print("=" * 60)
    print(f"Transcript: {first_result.text}")
    print(f"Total time: {first_elapsed:.2f} sec")

    # --------------------------------------------------------
    # Warm inference
    # Model is already loaded now.
    # --------------------------------------------------------

    print()
    print("Running second/warm transcription...")

    warm_started = time.perf_counter()

    warm_result = asr.transcribe(
        str(AUDIO_PATH),
        normalize=False,
    )

    warm_elapsed = (
        time.perf_counter()
        - warm_started
    )

    rtf = (
        warm_elapsed / duration
        if duration > 0
        else 0.0
    )

    print()
    print("=" * 60)
    print("WARM RESULT")
    print("=" * 60)
    print(f"Expected:   عايز ألغي الحجز")
    print(f"Transcript: {warm_result.text}")
    print(f"Inference:  {warm_elapsed * 1000:.2f} ms")
    print(f"RTF:        {rtf:.3f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
