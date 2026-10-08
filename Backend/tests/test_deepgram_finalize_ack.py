import time
from types import SimpleNamespace

import pytest

from voice_gateway.providers.deepgram_stt import (
    DeepgramStreamingSTT,
)


def _finalize_message(
    transcript: str,
):
    return SimpleNamespace(
        type="Results",
        channel=SimpleNamespace(
            alternatives=[
                SimpleNamespace(
                    transcript=transcript,
                )
            ]
        ),
        is_final=True,
        speech_final=False,
        from_finalize=True,
    )


def test_from_finalize_flushes_immediately(
    monkeypatch,
) -> None:

    monkeypatch.setenv(
        "DEEPGRAM_API_KEY",
        "test-key",
    )

    received = []

    stt = DeepgramStreamingSTT(
        encoding="linear16",
        sample_rate=24000,
        on_transcript=(
            lambda text, final:
            received.append(
                (text, final)
            )
        ),
    )

    stt._utterance_active = False
    stt._finalize_pending = True
    stt._finalize_started_at = (
        time.monotonic()
    )
    stt._last_final_at = (
        time.monotonic()
    )

    stt._handle_message(
        _finalize_message(
            "عايزة أحجز بكرة"
        )
    )

    assert received == [
        (
            "عايزة أحجز بكرة",
            True,
        )
    ]

    assert (
        stt._finalize_pending
        is False
    )

    assert (
        stt._finalize_started_at
        is None
    )

    assert (
        stt._last_final_at
        is None
    )

    assert stt._final_parts == []


def test_empty_finalize_ack_flushes_existing_parts(
    monkeypatch,
) -> None:

    monkeypatch.setenv(
        "DEEPGRAM_API_KEY",
        "test-key",
    )

    received = []

    stt = DeepgramStreamingSTT(
        encoding="linear16",
        sample_rate=24000,
        on_transcript=(
            lambda text, final:
            received.append(
                (text, final)
            )
        ),
    )

    stt._final_parts = [
        "عايزة",
        "أحجز بكرة",
    ]

    stt._finalize_pending = True
    stt._finalize_started_at = (
        time.monotonic()
    )
    stt._last_final_at = (
        time.monotonic()
    )

    stt._handle_message(
        _finalize_message("")
    )

    assert received == [
        (
            "عايزة أحجز بكرة",
            True,
        )
    ]

    assert (
        stt._finalize_pending
        is False
    )

    assert stt._final_parts == []