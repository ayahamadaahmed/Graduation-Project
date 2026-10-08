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

    async def recv(
        self,
    ) -> str:

        raise asyncio.TimeoutError

    async def close(
        self,
    ) -> None:

        self.closed = True


@pytest.mark.asyncio
async def test_failed_handshake_closes_temporary_socket(
    monkeypatch,
) -> None:

    monkeypatch.setenv(
        "HAMSA_API_KEY",
        "test-key",
    )

    stt = HamsaSTT()

    websocket = FakeWebSocket()

    async def fake_connect(
        *args,
        **kwargs,
    ):
        return websocket

    monkeypatch.setattr(
        "voice_gateway.providers.hamsa_stt.websockets.connect",
        fake_connect,
    )

    stt._connect_timeout_seconds = 0.01

    with pytest.raises(
        asyncio.TimeoutError
    ):

        await stt._ensure_connected()

    assert websocket.closed is True

    assert stt._websocket is None