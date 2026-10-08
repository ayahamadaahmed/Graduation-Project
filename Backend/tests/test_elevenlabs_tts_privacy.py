import logging

import httpx
import pytest

from voice_gateway.providers.elevenlabs_tts import (
    ElevenLabsTTS,
)


class FakeSyncClient:

    def __init__(
        self,
        response,
    ) -> None:
        self.response = response

    def post(
        self,
        *args,
        **kwargs,
    ):
        return self.response


def test_non_stream_http_error_does_not_log_body(
    monkeypatch,
    caplog,
) -> None:

    monkeypatch.setenv(
        "ELEVENLABS_API_KEY",
        "test-key",
    )

    monkeypatch.setenv(
        "ELEVENLABS_VOICE_ID",
        "test-voice",
    )

    tts = ElevenLabsTTS()

    secret_body = (
        "patient Aya phone 01012345678"
    )

    request = httpx.Request(
        "POST",
        "https://api.elevenlabs.io/test",
    )

    response = httpx.Response(
        400,
        request=request,
        content=secret_body.encode(),
    )

    tts._client.close()

    tts._client = FakeSyncClient(
        response
    )

    with caplog.at_level(
        logging.ERROR,
        logger=(
            "medmind.voice_gateway."
            "elevenlabs_tts"
        ),
    ):

        with pytest.raises(
            httpx.HTTPStatusError
        ):
            tts.synthesize_pcm24k(
                "بيانات المريض"
            )

    assert secret_body not in caplog.text

    assert "status=400" in caplog.text

    assert (
        f"body_bytes={len(secret_body.encode())}"
        in caplog.text
    )