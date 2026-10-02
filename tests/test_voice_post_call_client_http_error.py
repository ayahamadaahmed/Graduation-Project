from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest

from voice_gateway.post_call_client import (
    PostCallClient,
    PostCallHTTPError,
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
            (
                "http://test/api/v1/"
                "post-call/"
                "booking-confirmation"
            ),
        )

    def raise_for_status(
        self,
    ) -> None:

        response = httpx.Response(
            self.status_code,
            request=self.request,
            content=(
                b"sensitive backend body"
            ),
        )

        response.raise_for_status()


class ErrorHttpClient:

    def __init__(
        self,
        status_code: int,
    ) -> None:

        self.status_code = (
            status_code
        )

        self.calls = 0

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
async def test_post_call_503_is_classified_as_retryable_but_not_retried(
    caplog: pytest.LogCaptureFixture,
) -> None:

    client = PostCallClient(
        base_url="http://test",
    )

    fake_http = ErrorHttpClient(
        status_code=503
    )

    client._client = fake_http  # type: ignore[assignment]

    with caplog.at_level(
        logging.ERROR,
        logger=(
            "medmind.voice_gateway."
            "post_call"
        ),
    ):

        with pytest.raises(
            PostCallHTTPError
        ) as exc_info:

            await (
                client.send_booking_confirmation(
                    tenant_id="clinic-001",
                    appointment_reference=(
                        "APT-TEST-001"
                    ),
                )
            )

    assert (
        exc_info.value.status_code
        == 503
    )

    assert (
        exc_info.value.retryable
        is True
    )

    # No blind automatic retry yet.
    assert fake_http.calls == 1

    assert (
        "status_code=503"
        in caplog.text
    )

    assert (
        "retryable=True"
        in caplog.text
    )

    assert (
        "action=no_automatic_retry"
        in caplog.text
    )

    assert (
        "sensitive backend body"
        not in caplog.text
    )

    await client.close()