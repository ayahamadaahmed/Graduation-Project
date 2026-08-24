from __future__ import annotations

import json
import uuid

from fastapi import WebSocket


MAX_MEDIA_CHUNK_BYTES = 32000


async def start_media_buffering(
    websocket: WebSocket,
) -> None:
    """
    Tell Asterisk that a bulk / streaming
    media transfer is starting.

    While buffering is enabled Asterisk can
    combine arbitrary binary message sizes
    into correctly timed media frames.
    """

    await websocket.send_text(
        json.dumps(
            {
                "command":
                    "START_MEDIA_BUFFERING",
            }
        )
    )


async def send_media_chunk(
    websocket: WebSocket,
    audio: bytes,
) -> None:
    """
    Send one piece of raw media.

    The audio must already match the current
    Asterisk WebSocket media format.

    For our slin24 channel:
        PCM16 signed little-endian
        mono
        24 kHz
    """

    if not audio:
        return

    # --------------------------------------------------------
    # Keep each WebSocket binary message reasonably small.
    #
    # Asterisk buffering handles framing across these
    # messages, so they do NOT need to be exactly 960 bytes.
    # --------------------------------------------------------

    for offset in range(
        0,
        len(audio),
        MAX_MEDIA_CHUNK_BYTES,
    ):
        chunk = audio[
            offset:
            offset + MAX_MEDIA_CHUNK_BYTES
        ]

        await websocket.send_bytes(
            chunk
        )


async def stop_media_buffering(
    websocket: WebSocket,
) -> str:
    """
    Finish the current buffered media transfer.

    Asterisk pads any incomplete final audio
    frame with silence and later emits
    MEDIA_BUFFERING_COMPLETED.
    """

    correlation_id = str(
        uuid.uuid4()
    )

    await websocket.send_text(
        json.dumps(
            {
                "command":
                    "STOP_MEDIA_BUFFERING",

                "correlation_id":
                    correlation_id,
            }
        )
    )

    return correlation_id


async def send_media_audio(
    websocket: WebSocket,
    audio: bytes,
) -> str:
    """
    Backward-compatible helper for sending
    a COMPLETE audio buffer.

    Non-streaming path:
        START
        -> audio
        -> STOP
    """

    if not audio:
        raise ValueError(
            "Audio buffer cannot be empty"
        )

    await start_media_buffering(
        websocket
    )

    await send_media_chunk(
        websocket,
        audio,
    )

    correlation_id = (
        await stop_media_buffering(
            websocket
        )
    )

    return correlation_id


# Backward compatibility.
send_ulaw_audio = send_media_audio