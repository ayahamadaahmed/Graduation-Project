import logging
from types import SimpleNamespace

import pytest

from voice_gateway.providers.deepgram_stt import (
    DeepgramStreamingSTT,
)


def _message(
    transcript: str,
    *,
    is_final: bool,
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
        is_final=is_final,
        speech_final=False,
        from_finalize=False,
    )


def test_deepgram_logs_never_expose_transcript(
    monkeypatch,
    caplog,
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

    stt.begin_utterance()

    transcript = (
        "أنا آية أحمد ورقمي 01012345678"
    )

    with caplog.at_level(
        logging.DEBUG,
        logger=(
            "medmind.voice_gateway.deepgram"
        ),
    ):

        stt._handle_message(
            _message(
                transcript,
                is_final=True,
            )
        )

        stt._flush_final_transcript(
            reason="test",
        )

    assert transcript not in caplog.text

    assert (
        f"characters={len(transcript)}"
        in caplog.text
    )

    assert received == [
        (
            transcript,
            True,
        )
    ]