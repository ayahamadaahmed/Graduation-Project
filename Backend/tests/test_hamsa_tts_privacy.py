import logging

import httpx
import pytest

from voice_gateway.providers.hamsa_tts import (
    HamsaTTS,
)


class FakeResponse:

    def __init__(
        self,
        *,
        status_code: int,
        body: bytes,
    ) -> None:

        self.status_code = status_code
        self._body = body

        self.headers = {
            "content-type":
                "application/json",
        }

        self.request = httpx.Request(
            "POST",
            "https://api.tryhamsa.com/test",
        )

    async def aread(
        self,
    ) -> bytes:

        return self._body

    def raise_for_status(
        self,
    ) -> None:

        response = httpx.Response(
            self.status_code,
            request=self.request,
            content=self._body,
        )

        response.raise_for_status()


class FakeStreamContext:

    def __init__(
        self,
        response,
    ) -> None:

        self.response = response

    async def __aenter__(
        self,
    ):

        return self.response

    async def __aexit__(
        self,
        exc_type,
        exc,
        tb,
    ):

        return False


class FakeAsyncClient:

    def __init__(
        self,
        response,
    ) -> None:

        self.response = response

    def stream(
        self,
        *args,
        **kwargs,
    ):

        return FakeStreamContext(
            self.response
        )


@pytest.mark.asyncio
async def test_hamsa_tts_error_does_not_log_body(
    monkeypatch,
    caplog,
) -> None:

    monkeypatch.setenv(
        "HAMSA_API_KEY",
        "test-key",
    )

    tts = HamsaTTS()

    await tts._client.aclose()

    secret_body = (
        b"patient Aya phone 01012345678"
    )

    tts._client = FakeAsyncClient(
        FakeResponse(
            status_code=400,
            body=secret_body,
        )
    )

    with caplog.at_level(
        logging.ERROR,
        logger=(
            "medmind.voice_gateway."
            "hamsa_tts"
        ),
    ):

        with pytest.raises(
            httpx.HTTPStatusError
        ):

            chunks = [
                chunk
                async for chunk in (
                    tts.stream_pcm24k(
                        "بيانات المريض"
                    )
                )
            ]

    assert secret_body.decode() not in caplog.text

    assert "status=400" in caplog.text

    assert (
        f"body_bytes={len(secret_body)}"
        in caplog.text
    )