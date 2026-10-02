from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable

from fastapi import WebSocket


MAX_MEDIA_CHUNK_BYTES = 32000

DEFAULT_MEDIA_SEND_TIMEOUT_SECONDS = 5.0


class AsteriskMediaSendError(RuntimeError):
    """
    Raised when a media/control write to Asterisk cannot
    complete within the configured time budget.
    """


async def _run_send(
    send_factory: Callable[
        [],
        Awaitable[None],
    ],
    *,
    operation: str,
    timeout_seconds: float,
    send_lock: asyncio.Lock | None,
) -> None:
    """
    Execute one WebSocket write with:

    - optional serialization
    - bounded timeout
    - deterministic transport error
    """

    if timeout_seconds <= 0:
        raise ValueError(
            "timeout_seconds must be greater than zero"
        )

    async def execute() -> None:
        try:
            await asyncio.wait_for(
                send_factory(),
                timeout=timeout_seconds,
            )

        except asyncio.TimeoutError as exc:
            raise AsteriskMediaSendError(
                f"Asterisk media write timed out: "
                f"{operation}"
            ) from exc

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            raise AsteriskMediaSendError(
                f"Asterisk media write failed: "
                f"{operation}"
            ) from exc

    if send_lock is None:
        await execute()
        return

    async with send_lock:
        await execute()


async def _send_text(
    websocket: WebSocket,
    payload: dict[str, object],
    *,
    operation: str,
    timeout_seconds: float,
    send_lock: asyncio.Lock | None,
) -> None:

    message = json.dumps(
        payload,
        separators=(",", ":"),
    )

    await _run_send(
        lambda: websocket.send_text(
            message
        ),
        operation=operation,
        timeout_seconds=timeout_seconds,
        send_lock=send_lock,
    )


async def _send_bytes(
    websocket: WebSocket,
    audio: bytes,
    *,
    operation: str,
    timeout_seconds: float,
    send_lock: asyncio.Lock | None,
) -> None:

    await _run_send(
        lambda: websocket.send_bytes(
            audio
        ),
        operation=operation,
        timeout_seconds=timeout_seconds,
        send_lock=send_lock,
    )


async def start_media_buffering(
    websocket: WebSocket,
    *,
    send_lock: asyncio.Lock | None = None,
    timeout_seconds: float = (
        DEFAULT_MEDIA_SEND_TIMEOUT_SECONDS
    ),
) -> None:
    """
    Tell Asterisk that a streaming media transfer
    is starting.

    A shared send_lock can later be supplied by the
    per-call Voice Gateway runtime so START/STOP/FLUSH
    and audio writes cannot race each other.
    """

    await _send_text(
        websocket,
        {
            "command":
                "START_MEDIA_BUFFERING",
        },
        operation="START_MEDIA_BUFFERING",
        timeout_seconds=timeout_seconds,
        send_lock=send_lock,
    )


async def send_media_chunk(
    websocket: WebSocket,
    audio: bytes,
    *,
    send_lock: asyncio.Lock | None = None,
    timeout_seconds: float = (
        DEFAULT_MEDIA_SEND_TIMEOUT_SECONDS
    ),
) -> None:
    """
    Send raw media already encoded in the Asterisk
    WebSocket media format.

    Current MedMind voice format:
        PCM16 signed little-endian
        mono
        24 kHz
    """

    if not audio:
        return

    for offset in range(
        0,
        len(audio),
        MAX_MEDIA_CHUNK_BYTES,
    ):
        chunk = audio[
            offset:
            offset + MAX_MEDIA_CHUNK_BYTES
        ]

        await _send_bytes(
            websocket,
            chunk,
            operation="MEDIA_AUDIO",
            timeout_seconds=timeout_seconds,
            send_lock=send_lock,
        )


async def stop_media_buffering(
    websocket: WebSocket,
    *,
    correlation_id: str | None = None,
    send_lock: asyncio.Lock | None = None,
    timeout_seconds: float = (
        DEFAULT_MEDIA_SEND_TIMEOUT_SECONDS
    ),
) -> str:
    """
    Finish the current buffered media transfer.

    Asterisk later emits MEDIA_BUFFERING_COMPLETED
    for normal completion.

    FLUSH_MEDIA is different and does not produce
    MEDIA_BUFFERING_COMPLETED.
    """

    if correlation_id is None:
        correlation_id = str(
            uuid.uuid4()
        )

    await _send_text(
        websocket,
        {
            "command":
                "STOP_MEDIA_BUFFERING",

            "correlation_id":
                correlation_id,
        },
        operation="STOP_MEDIA_BUFFERING",
        timeout_seconds=timeout_seconds,
        send_lock=send_lock,
    )

    return correlation_id


async def flush_media(
    websocket: WebSocket,
    *,
    send_lock: asyncio.Lock | None = None,
    timeout_seconds: float = (
        DEFAULT_MEDIA_SEND_TIMEOUT_SECONDS
    ),
) -> None:
    """
    Immediately discard queued outbound media.

    Used by barge-in.

    Important:
    Asterisk does not emit MEDIA_BUFFERING_COMPLETED
    after FLUSH_MEDIA.
    """

    await _send_text(
        websocket,
        {
            "command":
                "FLUSH_MEDIA",
        },
        operation="FLUSH_MEDIA",
        timeout_seconds=timeout_seconds,
        send_lock=send_lock,
    )


async def send_media_audio(
    websocket: WebSocket,
    audio: bytes,
    *,
    send_lock: asyncio.Lock | None = None,
    timeout_seconds: float = (
        DEFAULT_MEDIA_SEND_TIMEOUT_SECONDS
    ),
) -> str:
    """
    Send one complete audio buffer.

    Flow:
        START_MEDIA_BUFFERING
        -> audio chunks
        -> STOP_MEDIA_BUFFERING
    """

    if not audio:
        raise ValueError(
            "Audio buffer cannot be empty"
        )

    await start_media_buffering(
        websocket,
        send_lock=send_lock,
        timeout_seconds=timeout_seconds,
    )

    await send_media_chunk(
        websocket,
        audio,
        send_lock=send_lock,
        timeout_seconds=timeout_seconds,
    )

    correlation_id = (
        await stop_media_buffering(
            websocket,
            send_lock=send_lock,
            timeout_seconds=timeout_seconds,
        )
    )

    return correlation_id


# Backward compatibility.
send_ulaw_audio = send_media_audio