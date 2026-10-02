from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest

from voice_gateway.medmind_client import (
    MedMindClient,
    MedMindTimeoutError,
)


class TimeoutHttpClient:

    def __init__(
        self,
    ) -> None:

        self.calls = 0

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ):

        self.calls += 1

        request = httpx.Request(
            "POST",
            "http://test/api/v1/ai/chat",
        )

        raise httpx.ReadTimeout(
            "backend stalled",
            request=request,
        )

    async def aclose(
        self,
    ) -> None:

        return None


@pytest.mark.asyncio
async def test_medmind_timeout_is_bounded_and_not_retried(
    caplog: pytest.LogCaptureFixture,
) -> None:

    client = MedMindClient(
        base_url="http://test",
        request_timeout_seconds=8.0,
    )

    fake_http = TimeoutHttpClient()

    client._client = fake_http  # type: ignore[assignment]

    message = (
        "عايزة احجز مع دكتور جلدية"
    )

    with caplog.at_level(
        logging.ERROR,
        logger=(
            "medmind.voice_gateway."
            "medmind_client"
        ),
    ):

        with pytest.raises(
            MedMindTimeoutError
        ):

            await client.chat(
                session_id=(
                    "voice-timeout-test"
                ),
                tenant_id="clinic-001",
                message=message,
                sensitive=False,
            )

    # Never retry a potentially mutating
    # booking/chat operation automatically.
    assert fake_http.calls == 1

    # Privacy still holds on failure paths.
    assert message not in caplog.text

    assert (
        "timeout_seconds=8.00"
        in caplog.text
    )

    assert (
        "action=no_retry"
        in caplog.text
    )

    await client.close()