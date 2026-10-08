import pytest

from voice_gateway.providers.elevenlabs_tts import (
    ElevenLabsTTS,
)


class FakeResponse:

    is_error = False

    headers = {
        "content-type":
            "audio/pcm",
    }

    async def aiter_raw(
        self,
    ):

        # Deliberately split PCM samples
        # across HTTP/network boundaries.
        yield b"\x01"

        yield b"\x02\x03"

        yield b"\x04"


class FakeStreamContext:

    async def __aenter__(
        self,
    ):

        return FakeResponse()

    async def __aexit__(
        self,
        exc_type,
        exc,
        tb,
    ):

        return False


class FakeAsyncClient:

    def stream(
        self,
        *args,
        **kwargs,
    ):

        return FakeStreamContext()


@pytest.mark.asyncio
async def test_stream_preserves_pcm16_alignment(
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

    await (
        original_async_client
        .aclose()
    )

    tts._async_client = (
        FakeAsyncClient()
    )

    chunks = []

    async for chunk in (
        tts.stream_pcm24k(
            "اختبار"
        )
    ):

        chunks.append(
            chunk
        )

    tts.close()

    assert chunks == [
        b"\x01\x02",
        b"\x03\x04",
    ]

    assert all(
        len(chunk) % 2 == 0
        for chunk in chunks
    )

    assert (
        b"".join(chunks)
        == b"\x01\x02\x03\x04"
    )