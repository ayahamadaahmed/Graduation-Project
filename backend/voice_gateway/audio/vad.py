from __future__ import annotations

from typing import Any

import numpy as np
import torch
from silero_vad import VADIterator, load_silero_vad


SAMPLE_RATE = 8000

VAD_WINDOW_SAMPLES = 256
PCM16_BYTES_PER_SAMPLE = 2
VAD_WINDOW_BYTES = VAD_WINDOW_SAMPLES * PCM16_BYTES_PER_SAMPLE


class StreamingVAD:
    """
    Per-call streaming Silero VAD.

    Input:
        PCM16 little-endian mono audio at 8 kHz.

    Asterisk currently sends:
        160 samples / 320 PCM16 bytes / 20 ms.

    Silero VAD at 8 kHz requires:
        256 samples / 512 PCM16 bytes / 32 ms.

    The internal buffer bridges those two frame sizes.
    """

    def __init__(
        self,
        threshold: float = 0.5,
        min_silence_duration_ms: int = 500,
        speech_pad_ms: int = 30,
    ) -> None:
        self.model = load_silero_vad()

        self.iterator = VADIterator(
            self.model,
            threshold=threshold,
            sampling_rate=SAMPLE_RATE,
            min_silence_duration_ms=min_silence_duration_ms,
            speech_pad_ms=speech_pad_ms,
        )

        self._buffer = bytearray()

    def feed_pcm16(
        self,
        pcm16_audio: bytes,
    ) -> list[dict[str, Any]]:
        """
        Feed arbitrary-length PCM16 audio.

        Returns zero or more VAD events:
            {"start": sample_index}
            {"end": sample_index}
        """
        if not pcm16_audio:
            return []

        self._buffer.extend(pcm16_audio)

        events: list[dict[str, Any]] = []

        while len(self._buffer) >= VAD_WINDOW_BYTES:
            chunk = bytes(
                self._buffer[:VAD_WINDOW_BYTES]
            )

            del self._buffer[:VAD_WINDOW_BYTES]

            samples = np.frombuffer(
                chunk,
                dtype="<i2",
            ).astype(np.float32)

            samples /= 32768.0

            tensor = torch.from_numpy(samples)

            event = self.iterator(tensor)

            if event is not None:
                events.append(event)

        return events

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def reset(self) -> None:
        self._buffer.clear()
        self.iterator.reset_states()
