from __future__ import annotations

import asyncio
import json

import pytest

from voice_gateway.transport.asterisk_media import (
    AsteriskMediaSendError,
    MAX_MEDIA_CHUNK_BYTES,
    flush_media,
    send_media_audio,
    send_media_chunk,
    start_media_buffering,
)


class FakeWebSocket:

    def __init__(
        self,
        *,
        delay_seconds: float = 0.0,
    ) -> None:

        self.delay_seconds = (
            delay_seconds
        )

        self.text_messages: list[str] = []
        self.binary_messages: list[bytes] = []

    async def send_text(
        self,
        message: str,
    ) -> None:

        if self.delay_seconds:
            await asyncio.sleep(
                self.delay_seconds
            )

        self.text_messages.append(
            message
        )

    async def send_bytes(
        self,
        audio: bytes,
    ) -> None:

        if self.delay_seconds:
            await asyncio.sleep(
                self.delay_seconds
            )

        self.binary_messages.append(
            audio
        )


@pytest.mark.asyncio
async def test_start_media_buffering_command(
) -> None:

    websocket = FakeWebSocket()

    await start_media_buffering(
        websocket,  # type: ignore[arg-type]
    )

    assert len(
        websocket.text_messages
    ) == 1

    payload = json.loads(
        websocket.text_messages[0]
    )

    assert payload == {
        "command":
            "START_MEDIA_BUFFERING",
    }


@pytest.mark.asyncio
async def test_send_media_chunk_splits_large_audio(
) -> None:

    websocket = FakeWebSocket()

    audio = (
        b"x"
        * (
            MAX_MEDIA_CHUNK_BYTES
            * 2
            + 123
        )
    )

    await send_media_chunk(
        websocket,  # type: ignore[arg-type]
        audio,
    )

    assert len(
        websocket.binary_messages
    ) == 3

    assert len(
        websocket.binary_messages[0]
    ) == MAX_MEDIA_CHUNK_BYTES

    assert len(
        websocket.binary_messages[1]
    ) == MAX_MEDIA_CHUNK_BYTES

    assert len(
        websocket.binary_messages[2]
    ) == 123

    assert (
        b"".join(
            websocket.binary_messages
        )
        == audio
    )


@pytest.mark.asyncio
async def test_empty_media_chunk_is_ignored(
) -> None:

    websocket = FakeWebSocket()

    await send_media_chunk(
        websocket,  # type: ignore[arg-type]
        b"",
    )

    assert (
        websocket.binary_messages
        == []
    )


@pytest.mark.asyncio
async def test_flush_media_command(
) -> None:

    websocket = FakeWebSocket()

    await flush_media(
        websocket,  # type: ignore[arg-type]
    )

    payload = json.loads(
        websocket.text_messages[0]
    )

    assert payload == {
        "command":
            "FLUSH_MEDIA",
    }


@pytest.mark.asyncio
async def test_media_write_timeout(
) -> None:

    websocket = FakeWebSocket(
        delay_seconds=0.05
    )

    with pytest.raises(
        AsteriskMediaSendError
    ):
        await start_media_buffering(
            websocket,  # type: ignore[arg-type]
            timeout_seconds=0.001,
        )


@pytest.mark.asyncio
async def test_complete_audio_send_sequence(
) -> None:

    websocket = FakeWebSocket()

    correlation_id = (
        await send_media_audio(
            websocket,  # type: ignore[arg-type]
            b"\x00" * 2000,
        )
    )

    assert correlation_id

    assert len(
        websocket.text_messages
    ) == 2

    start_payload = json.loads(
        websocket.text_messages[0]
    )

    stop_payload = json.loads(
        websocket.text_messages[1]
    )

    assert start_payload[
        "command"
    ] == "START_MEDIA_BUFFERING"

    assert stop_payload[
        "command"
    ] == "STOP_MEDIA_BUFFERING"

    assert stop_payload[
        "correlation_id"
    ] == correlation_id

    assert (
        b"".join(
            websocket.binary_messages
        )
        == b"\x00" * 2000
    )


@pytest.mark.asyncio
async def test_shared_lock_serializes_writes(
) -> None:

    websocket = FakeWebSocket(
        delay_seconds=0.005
    )

    send_lock = asyncio.Lock()

    await asyncio.gather(
        start_media_buffering(
            websocket,  # type: ignore[arg-type]
            send_lock=send_lock,
        ),
        flush_media(
            websocket,  # type: ignore[arg-type]
            send_lock=send_lock,
        ),
    )

    assert len(
        websocket.text_messages
    ) == 2