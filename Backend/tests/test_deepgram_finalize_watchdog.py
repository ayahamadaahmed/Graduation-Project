import time

import pytest

import voice_gateway.providers.deepgram_stt as deepgram_module

from voice_gateway.providers.deepgram_stt import (
    DeepgramStreamingSTT,
)


@pytest.mark.asyncio
async def test_watchdog_flushes_after_final_results_settle(
    monkeypatch,
) -> None:

    monkeypatch.setenv(
        "DEEPGRAM_API_KEY",
        "test-key",
    )

    # Speed up the test only.
    monkeypatch.setattr(
        deepgram_module,
        "FINALIZE_SETTLE_DELAY_SECONDS",
        0.01,
    )

    monkeypatch.setattr(
        deepgram_module,
        "FINALIZE_MAX_WAIT_SECONDS",
        0.10,
    )

    monkeypatch.setattr(
        deepgram_module,
        "FINALIZE_WATCHDOG_INTERVAL_SECONDS",
        0.001,
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

    now = time.monotonic()

    stt._final_parts = [
        "عايزة",
        "أحجز بكرة",
    ]

    stt._utterance_active = False
    stt._finalize_pending = True
    stt._finalize_started_at = now

    # Already quiet longer than settle delay.
    stt._last_final_at = (
        now - 0.02
    )

    await stt._finalize_watchdog()

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


@pytest.mark.asyncio
async def test_watchdog_forces_flush_at_absolute_max_wait(
    monkeypatch,
) -> None:

    monkeypatch.setenv(
        "DEEPGRAM_API_KEY",
        "test-key",
    )

    # Prevent the normal settle path.
    monkeypatch.setattr(
        deepgram_module,
        "FINALIZE_SETTLE_DELAY_SECONDS",
        1.0,
    )

    # But make absolute safety limit fast.
    monkeypatch.setattr(
        deepgram_module,
        "FINALIZE_MAX_WAIT_SECONDS",
        0.01,
    )

    monkeypatch.setattr(
        deepgram_module,
        "FINALIZE_WATCHDOG_INTERVAL_SECONDS",
        0.001,
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

    now = time.monotonic()

    stt._final_parts = [
        "عايزة أحجز بكرة",
    ]

    stt._utterance_active = False
    stt._finalize_pending = True

    # Simulate a Finalize transaction that
    # has already exceeded its max wait.
    stt._finalize_started_at = (
        now - 0.02
    )

    # Recent final means normal settle
    # must NOT be the reason for flushing.
    stt._last_final_at = now

    await stt._finalize_watchdog()

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