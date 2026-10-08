import json

import pytest

from voice_gateway.transport.asterisk_media import (
    stop_media_buffering,
)


class FakeWebSocket:

    def __init__(
        self,
    ) -> None:

        self.text_messages: list[str] = []

    async def send_text(
        self,
        message: str,
    ) -> None:

        self.text_messages.append(
            message
        )


@pytest.mark.asyncio
async def test_stop_media_buffering_uses_given_correlation_id(
) -> None:

    websocket = (
        FakeWebSocket()
    )

    correlation_id = (
        "hamsa-stream-test-123"
    )

    returned_id = await (
        stop_media_buffering(
            websocket,
            correlation_id=
                correlation_id,
        )
    )

    assert (
        returned_id
        == correlation_id
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
            "STOP_MEDIA_BUFFERING",

        "correlation_id":
            correlation_id,
    }


@pytest.mark.asyncio
async def test_stop_media_buffering_generates_id_when_missing(
) -> None:

    websocket = (
        FakeWebSocket()
    )

    returned_id = await (
        stop_media_buffering(
            websocket
        )
    )

    assert returned_id

    payload = json.loads(
        websocket.text_messages[0]
    )

    assert (
        payload[
            "command"
        ]
        == "STOP_MEDIA_BUFFERING"
    )

    assert (
        payload[
            "correlation_id"
        ]
        == returned_id
    )