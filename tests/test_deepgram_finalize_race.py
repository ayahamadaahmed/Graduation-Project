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


@pytest.mark.asyncio
async def test_finalize_ack_can_arrive_during_send(
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

    class FakeConnection:

        async def send_finalize(
            self,
        ) -> None:

            # Simulate Deepgram listener receiving
            # the ACK before send_finalize()
            # has returned to finalize().
            stt._handle_message(
                _finalize_message(
                    "عايزة أحجز بكرة"
                )
            )

    stt._connection = FakeConnection()

    stt.begin_utterance()

    await stt.finalize()

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

    assert (
        stt._finalize_flush_task
        is None
    )

    assert stt._final_parts == []