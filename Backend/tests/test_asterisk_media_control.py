from __future__ import annotations

import json

import pytest

from voice_gateway.transport.asterisk_media import (
    flush_media,
)


class FakeWebSocket:

    def __init__(
        self,
    ) -> None:

        self.text_messages: list[
            str
        ] = []

    async def send_text(
        self,
        message: str,
    ) -> None:

        self.text_messages.append(
            message
        )


@pytest.mark.asyncio
async def test_flush_media_sends_asterisk_control_command(
) -> None:

    websocket = (
        FakeWebSocket()
    )

    await flush_media(
        websocket  # type: ignore[arg-type]
    )

    assert (
        len(
            websocket.text_messages
        )
        == 1
    )

    payload = json.loads(
        websocket.text_messages[0]
    )

    assert payload == {
        "command":
            "FLUSH_MEDIA",
    }