import audioop

import pytest

from voice_gateway.providers.hamsa_tts import (
    ASTERISK_FRAME_BYTES,
    CHANNELS,
    HamsaTTS,
    INPUT_SAMPLE_RATE,
    OUTPUT_SAMPLE_RATE,
    SAMPLE_WIDTH,
)


class FakeResponse:

    status_code = 200

    headers = {
        "content-type": "audio/pcm",
    }

    def __init__(
        self,
        chunks: list[bytes],
    ) -> None:

        self._chunks = chunks

    async def aiter_bytes(
        self,
    ):
        for chunk in self._chunks:
            yield chunk


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

    async def aclose(
        self,
    ) -> None:
        return None


@pytest.mark.asyncio
async def test_hamsa_stream_preserves_audio_across_odd_network_chunks(
    monkeypatch,
) -> None:

    monkeypatch.setenv(
        "HAMSA_API_KEY",
        "test-key",
    )

    # Valid PCM16 mono audio.
    pcm16 = (
        b"\x01\x00"
        b"\x02\x00"
        b"\x03\x00"
        b"\x04\x00"
        * 1000
    )

    # Deliberately cut through PCM16 sample boundaries.
    chunks = [
        pcm16[:1],
        pcm16[1:137],
        pcm16[137:1000],
        pcm16[1000:2501],
        pcm16[2501:],
    ]

    response = FakeResponse(
        chunks
    )

    tts = HamsaTTS()

    await tts._client.aclose()

    tts._client = FakeAsyncClient(
        response
    )

    emitted = []

    async for chunk in (
        tts.stream_pcm24k(
            "اختبار"
        )
    ):
        emitted.append(
            chunk
        )

    actual = b"".join(
        emitted
    )

    expected, _ = audioop.ratecv(
        pcm16,
        SAMPLE_WIDTH,
        CHANNELS,
        INPUT_SAMPLE_RATE,
        OUTPUT_SAMPLE_RATE,
        None,
    )

    assert actual == expected

    assert emitted

    # Every non-final frame must be exactly
    # one Asterisk 20 ms slin24 frame.
    assert all(
        len(chunk)
        == ASTERISK_FRAME_BYTES
        for chunk in emitted[:-1]
    )

    # Final frame may intentionally be partial.
    assert (
        0
        < len(emitted[-1])
        <= ASTERISK_FRAME_BYTES
    )

    # PCM16 must always remain sample-aligned.
    assert all(
        len(chunk) % SAMPLE_WIDTH == 0
        for chunk in emitted
    )

    await tts.aclose()