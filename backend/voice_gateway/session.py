from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class VoiceSession:
    connection_id: str
    channel_id: str
    channel: str
    audio_format: str
    sample_rate: int
    optimal_frame_size: int
    ptime_ms: int

    frames_received: int = 0
    bytes_received: int = 0

    started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def record_audio(self, audio: bytes) -> None:
        self.frames_received += 1
        self.bytes_received += len(audio)

    @property
    def audio_duration_ms(self) -> int:
        return self.frames_received * self.ptime_ms

    @property
    def audio_duration_seconds(self) -> float:
        return self.audio_duration_ms / 1000.0
