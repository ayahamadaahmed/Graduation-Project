from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest

from voice_gateway.medmind_client import (
    MedMindClient,
    MedMindHTTPError,
)


class ErrorResponse:

    def __init__(
        self,
        status_code: int,
    ) -> None:

        self.status_code = (
            status_code
        )

        self.request = httpx.Request(
            "POST",
            "http://test/api/v1/ai/chat",
        )

    def raise_for_status(
        self,
    ) -> None:

        response = httpx.Response(
            self.status_code,
            request=self.request,
            content=(
                b"sensitive backend error body"
            ),
        )

        response.raise_for_status()


class ErrorHttpClient:

    def __init__(
        self,
        status_code: int,
    ) -> None:

        self.calls = 0
        self.status_code = (
            status_code
        )

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> ErrorResponse:

        self.calls += 1

        return ErrorResponse(
            self.status_code
        )

    async def aclose(
        self,
    ) -> None:

        return None


@pytest.mark.asyncio
async def test_medmind_http_error_is_classified_and_not_retried(
    caplog: pytest.LogCaptureFixture,
) -> None:

    client = MedMindClient(
        base_url="http://test",
    )

    fake_http = ErrorHttpClient(
        status_code=503
    )

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
            MedMindHTTPError
        ) as exc_info:

            await client.chat(
                session_id=(
                    "voice-http-error-test"
                ),
                tenant_id="clinic-001",
                message=message,
                sensitive=False,
            )

    assert (
        exc_info.value.status_code
        == 503
    )

    # Never automatically retry.
    assert fake_http.calls == 1

    # User content must remain private.
    assert message not in caplog.text

    assert (
        "status_code=503"
        in caplog.text
    )

    assert (
        "action=no_retry"
        in caplog.text
    )

    assert (
        "sensitive backend error body"
        not in caplog.text
    )

    await client.close()