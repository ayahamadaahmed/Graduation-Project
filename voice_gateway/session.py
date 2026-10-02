from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter


def _utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


@dataclass(slots=True)
class VoiceTurn:
    """
    Privacy-safe timing state for one user turn.

    Do not store transcript text, phone numbers,
    national IDs, or other patient PII here.
    """

    number: int
    turn_id: str

    started_at: datetime = field(
        default_factory=_utc_now
    )

    started_monotonic: float = field(
        default_factory=perf_counter,
        repr=False,
    )

    speech_started_monotonic: float | None = field(
        default=None,
        repr=False,
    )

    speech_ended_monotonic: float | None = field(
        default=None,
        repr=False,
    )

    stt_completed_monotonic: float | None = field(
        default=None,
        repr=False,
    )

    backend_completed_monotonic: float | None = field(
        default=None,
        repr=False,
    )

    tts_first_audio_monotonic: float | None = field(
        default=None,
        repr=False,
    )

    completed_monotonic: float | None = field(
        default=None,
        repr=False,
    )

    stt_provider: str | None = None
    stt_reason: str | None = None

    backend_route: str | None = None
    backend_stage: str | None = None

    barge_in: bool = False
    failed: bool = False
    failure_stage: str | None = None

    def mark_speech_started(self) -> None:
        if self.speech_started_monotonic is None:
            self.speech_started_monotonic = (
                perf_counter()
            )

    def mark_speech_ended(self) -> None:
        self.speech_ended_monotonic = (
            perf_counter()
        )

    def mark_stt_completed(
        self,
        *,
        provider: str,
        reason: str | None = None,
    ) -> None:
        self.stt_completed_monotonic = (
            perf_counter()
        )

        self.stt_provider = (
            provider
        )

        self.stt_reason = (
            reason
        )

    def mark_backend_completed(
        self,
        *,
        route: str | None = None,
        stage: str | None = None,
    ) -> None:
        self.backend_completed_monotonic = (
            perf_counter()
        )

        self.backend_route = (
            route
        )

        self.backend_stage = (
            stage
        )

    def mark_tts_first_audio(self) -> None:
        if (
            self.tts_first_audio_monotonic
            is None
        ):
            self.tts_first_audio_monotonic = (
                perf_counter()
            )

    def mark_completed(self) -> None:
        self.completed_monotonic = (
            perf_counter()
        )

    def mark_failed(
        self,
        *,
        stage: str,
    ) -> None:
        self.failed = True
        self.failure_stage = stage
        self.completed_monotonic = (
            perf_counter()
        )

    @staticmethod
    def _duration_ms(
        start: float | None,
        end: float | None,
    ) -> float | None:

        if (
            start is None
            or end is None
        ):
            return None

        return round(
            max(
                0.0,
                (
                    end
                    - start
                )
                * 1000,
            ),
            2,
        )

    @property
    def speech_duration_ms(
        self,
    ) -> float | None:

        return self._duration_ms(
            self.speech_started_monotonic,
            self.speech_ended_monotonic,
        )

    @property
    def stt_after_speech_ms(
        self,
    ) -> float | None:

        return self._duration_ms(
            self.speech_ended_monotonic,
            self.stt_completed_monotonic,
        )

    @property
    def backend_ms(
        self,
    ) -> float | None:

        return self._duration_ms(
            self.stt_completed_monotonic,
            self.backend_completed_monotonic,
        )

    @property
    def tts_first_audio_ms(
        self,
    ) -> float | None:

        return self._duration_ms(
            self.backend_completed_monotonic,
            self.tts_first_audio_monotonic,
        )

    @property
    def end_to_first_audio_ms(
        self,
    ) -> float | None:

        return self._duration_ms(
            self.speech_ended_monotonic,
            self.tts_first_audio_monotonic,
        )

    @property
    def total_ms(
        self,
    ) -> float | None:

        return self._duration_ms(
            self.started_monotonic,
            self.completed_monotonic,
        )

    def metrics(self) -> dict[str, object]:
        """
        Return only operational metadata.

        No patient transcript or identity data is stored.
        """

        return {
            "turn_id":
                self.turn_id,

            "turn_number":
                self.number,

            "speech_ms":
                self.speech_duration_ms,

            "stt_ms":
                self.stt_after_speech_ms,

            "backend_ms":
                self.backend_ms,

            "tts_first_audio_ms":
                self.tts_first_audio_ms,

            "end_to_first_audio_ms":
                self.end_to_first_audio_ms,

            "total_ms":
                self.total_ms,

            "stt_provider":
                self.stt_provider,

            "stt_reason":
                self.stt_reason,

            "backend_route":
                self.backend_route,

            "backend_stage":
                self.backend_stage,

            "barge_in":
                self.barge_in,

            "failed":
                self.failed,

            "failure_stage":
                self.failure_stage,
        }


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

    turn_counter: int = 0

    active_turn: VoiceTurn | None = (
        None
    )

    completed_turns: list[VoiceTurn] = field(
        default_factory=list
    )

    started_at: datetime = field(
        default_factory=_utc_now
    )

    started_monotonic: float = field(
        default_factory=perf_counter,
        repr=False,
    )

    def record_audio(
        self,
        audio: bytes,
    ) -> None:

        self.frames_received += 1
        self.bytes_received += len(
            audio
        )

    @property
    def call_id(self) -> str:
        """
        Use the Asterisk channel ID as the stable
        call correlation identifier.
        """

        return self.channel_id

    def start_turn(self) -> VoiceTurn:
        """
        Start a new user turn.

        An existing unfinished turn is marked failed instead
        of silently disappearing.
        """

        if self.active_turn is not None:

            self.active_turn.mark_failed(
                stage="superseded"
            )

            self.completed_turns.append(
                self.active_turn
            )

        self.turn_counter += 1

        turn = VoiceTurn(
            number=self.turn_counter,
            turn_id=(
                f"{self.call_id}:"
                f"{self.turn_counter}"
            ),
        )

        self.active_turn = turn

        return turn

    def finish_turn(
        self,
    ) -> VoiceTurn | None:

        turn = self.active_turn

        if turn is None:
            return None

        if (
            turn.completed_monotonic
            is None
        ):
            turn.mark_completed()

        self.completed_turns.append(
            turn
        )

        self.active_turn = None

        return turn

    @property
    def audio_duration_ms(
        self,
    ) -> int:

        return (
            self.frames_received
            * self.ptime_ms
        )

    @property
    def audio_duration_seconds(
        self,
    ) -> float:

        return (
            self.audio_duration_ms
            / 1000.0
        )

    @property
    def session_duration_seconds(
        self,
    ) -> float:

        return round(
            max(
                0.0,
                perf_counter()
                - self.started_monotonic,
            ),
            3,
        )