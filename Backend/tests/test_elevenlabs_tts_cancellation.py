import asyncio

import pytest

from voice_gateway.providers.elevenlabs_tts import (
    ElevenLabsTTS,
)


class FakeResponse:

    is_error = False

    headers = {
        "content-type": "audio/pcm",
    }

    def __init__(
        self,
    ) -> None:

        self.first_chunk_sent = (
            asyncio.Event()
        )

    async def aiter_raw(
        self,
    ):

        yield b"\x01\x02"

        self.first_chunk_sent.set()

        # Simulate a stream that remains open
        # until playback is cancelled.
        await asyncio.Event().wait()


class FakeStreamContext:

    def __init__(
        self,
        response: FakeResponse,
    ) -> None:

        self.response = response
        self.exited = False
        self.exit_exc_type = None

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
        self.exit_exc_type = exc_type

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


@pytest.mark.asyncio
async def test_stream_cancellation_closes_http_context(
    monkeypatch,
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

    original_async_client = (
        tts._async_client
    )

    await original_async_client.aclose()

    response = FakeResponse()

    context = FakeStreamContext(
        response
    )

    tts._async_client = FakeAsyncClient(
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

    assert received == [
        b"\x01\x02",
    ]

    # Most important assertion:
    # cancellation must unwind the HTTP stream.
    assert context.exited is True