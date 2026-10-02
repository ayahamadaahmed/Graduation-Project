import asyncio

import pytest

from websockets.protocol import State

from voice_gateway.providers.hamsa_stt import (
    HamsaSTT,
)


class FakeWebSocket:

    def __init__(
        self,
    ) -> None:

        self.state = State.OPEN
        self.closed = False

    async def send(
        self,
        message: str,
    ) -> None:

        return None

    async def recv(
        self,
    ) -> str:

        await asyncio.Event().wait()

        return ""

    async def close(
        self,
    ) -> None:

        self.closed = True


@pytest.mark.asyncio
async def test_internal_timeout_resets_connection(
    monkeypatch,
) -> None:

    monkeypatch.setenv(
        "HAMSA_API_KEY",
        "test-key",
    )

    stt = HamsaSTT(
        sample_rate=24000,
    )

    websocket = FakeWebSocket()

    stt._websocket = websocket

    stt._transcribe_timeout_seconds = (
        0.01
    )

    async def fake_ensure_connected() -> None:
        return None

    monkeypatch.setattr(
        stt,
        "_ensure_connected",
        fake_ensure_connected,
    )

    result = await stt.transcribe(
        b"\x00\x00" * 160,
        sensitive=True,
    )

    assert result == ""

    assert stt._websocket is None

    assert websocket.closed is True