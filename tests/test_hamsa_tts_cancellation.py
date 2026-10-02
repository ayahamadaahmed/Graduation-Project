import asyncio

import pytest

from voice_gateway.providers.hamsa_tts import (
    HamsaTTS,
)


class FakeResponse:

    status_code = 200

    headers = {
        "content-type": "audio/pcm",
    }

    def __init__(
        self,
    ) -> None:

        self.first_chunk_sent = (
            asyncio.Event()
        )

    async def aiter_bytes(
        self,
    ):

        # Enough 16 kHz PCM to eventually
        # produce playable output.
        yield (
            b"\x01\x02"
            * 640
        )

        self.first_chunk_sent.set()

        # Keep HTTP response open until
        # the consumer task is cancelled.
        await asyncio.Event().wait()


class FakeStreamContext:

    def __init__(
        self,
        response: FakeResponse,
    ) -> None:

        self.response = response
        self.exited = False

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

        self.exited = True

        return False


class FakeAsyncClient:

    def __init__(
        self,
        context: FakeStreamContext,
    ) -> None:

        self.context = context

    def stream(
        self,
        *args,
        **kwargs,
    ):

        return self.context

    async def aclose(
        self,
    ) -> None:

        return None


@pytest.mark.asyncio
async def test_hamsa_stream_cancellation_closes_http_context(
    monkeypatch,
) -> None:

    monkeypatch.setenv(
        "HAMSA_API_KEY",
        "test-key",
    )

    tts = HamsaTTS()

    await tts._client.aclose()

    response = FakeResponse()

    context = FakeStreamContext(
        response
    )

    tts._client = FakeAsyncClient(
        context
    )

    received = []

    async def consume() -> None:

        async for chunk in (
            tts.stream_pcm24k(
                "اختبار إلغاء الصوت"
            )
        ):

            received.append(
                chunk
            )

    task = asyncio.create_task(
        consume()
    )

    await (
        response
        .first_chunk_sent
        .wait()
    )

    task.cancel()

    with pytest.raises(
        asyncio.CancelledError
    ):
        await task

    assert received

    assert context.exited is True

    await tts.aclose()