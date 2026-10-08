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
        self.recv_started = (
            asyncio.Event()
        )

    async def send(
        self,
        message: str,
    ) -> None:
        return None

    async def recv(
        self,
    ) -> str:

        self.recv_started.set()

        # Simulate a Hamsa request that
        # never returns on time.
        await asyncio.Event().wait()

        return ""

    async def close(
        self,
    ) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_cancelled_hamsa_request_resets_connection(
    monkeypatch,
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

    websocket = (
        FakeWebSocket()
    )

    stt._websocket = (
        websocket
    )

    async def fake_ensure_connected() -> None:
        return None

    monkeypatch.setattr(
        stt,
        "_ensure_connected",
        fake_ensure_connected,
    )

    task = asyncio.create_task(
        stt.transcribe(
            b"\x00\x00" * 160,
            sensitive=True,
        )
    )

    await websocket.recv_started.wait()

    task.cancel()

    with pytest.raises(
        asyncio.CancelledError
    ):
        await task

    assert (
        stt._websocket
        is None
    )

    assert (
        websocket.closed
        is True
    )