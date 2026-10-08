import logging

import pytest

from voice_gateway.providers.hamsa_stt import (
    HamsaSTT,
)


@pytest.mark.parametrize(
    (
        "transcript",
        "sensitive",
    ),
    [
        (
            "أنا آية أحمد وعايزة أحجز بكرة",
            False,
        ),
        (
            "29801011234567",
            True,
        ),
    ],
)
def test_hamsa_transcript_logs_never_expose_content(
    monkeypatch,
    caplog,
    transcript: str,
    sensitive: bool,
) -> None:

    monkeypatch.setenv(
        "HAMSA_API_KEY",
        "test-key",
    )

    stt = HamsaSTT(
        sample_rate=24000,
        language="ar",
        model="s3",
    )

    with caplog.at_level(
        logging.INFO,
        logger="medmind.voice_gateway.hamsa",
    ):

        stt._log_transcript(
            transcript=transcript,
            elapsed_ms=123.45,
            pcm_audio=(
                b"\x00\x00"
                * 100
            ),
            sensitive=sensitive,
            source="plain",
        )

    assert transcript not in caplog.text

    assert (
        f"characters={len(transcript)}"
        in caplog.text
    )

    assert (
        f"sensitive={sensitive}"
        in caplog.text
    )

    assert "elapsed_ms=123.45" in caplog.text

    assert "source=plain" in caplog.text