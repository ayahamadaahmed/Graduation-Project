from __future__ import annotations

import time

from voice_gateway.session import (
    VoiceSession,
)


def make_session() -> VoiceSession:
    return VoiceSession(
        connection_id="connection-test",
        channel_id="channel-test",
        channel="WebSocket/test",
        audio_format="slin24",
        sample_rate=24000,
        optimal_frame_size=960,
        ptime_ms=20,
    )


def test_audio_accounting() -> None:
    session = make_session()

    session.record_audio(
        b"\x00" * 960
    )

    session.record_audio(
        b"\x00" * 960
    )

    assert session.frames_received == 2
    assert session.bytes_received == 1920
    assert session.audio_duration_ms == 40
    assert (
        session.audio_duration_seconds
        == 0.04
    )


def test_turn_ids_are_sequential() -> None:
    session = make_session()

    first = session.start_turn()

    session.finish_turn()

    second = session.start_turn()

    assert first.number == 1
    assert second.number == 2

    assert (
        first.turn_id
        == "channel-test:1"
    )

    assert (
        second.turn_id
        == "channel-test:2"
    )


def test_turn_timing_metrics() -> None:
    session = make_session()

    turn = session.start_turn()

    turn.mark_speech_started()

    time.sleep(0.001)

    turn.mark_speech_ended()

    time.sleep(0.001)

    turn.mark_stt_completed(
        provider="hamsa",
        reason="primary_final",
    )

    time.sleep(0.001)

    turn.mark_backend_completed(
        route="provider_rag",
        stage="new",
    )

    time.sleep(0.001)

    turn.mark_tts_first_audio()

    session.finish_turn()

    metrics = turn.metrics()

    assert metrics["stt_provider"] == "hamsa"

    assert (
        metrics["stt_reason"]
        == "primary_final"
    )

    assert (
        metrics["backend_route"]
        == "provider_rag"
    )

    assert (
        metrics["speech_ms"]
        is not None
    )

    assert metrics["stt_ms"] is not None

    assert (
        metrics["backend_ms"]
        is not None
    )

    assert (
        metrics["tts_first_audio_ms"]
        is not None
    )

    assert (
        metrics["end_to_first_audio_ms"]
        is not None
    )


def test_new_turn_closes_stale_turn() -> None:
    session = make_session()

    first = session.start_turn()

    second = session.start_turn()

    assert first.failed is True

    assert (
        first.failure_stage
        == "superseded"
    )

    assert (
        session.active_turn
        is second
    )

    assert (
        len(
            session.completed_turns
        )
        == 1
    )


def test_finish_without_active_turn() -> None:
    session = make_session()

    assert session.finish_turn() is None