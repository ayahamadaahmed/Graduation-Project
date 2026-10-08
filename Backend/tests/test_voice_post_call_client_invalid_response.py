from __future__ import annotations

import logging
from typing import Any

import pytest

from voice_gateway.post_call_client import (
    PostCallClient,
    PostCallResponseError,
)


class FakeResponse:

    status_code = 200

    def __init__(
        self,
        *,
        payload: Any = None,
        json_error: Exception | None = None,
    ) -> None:

        self.payload = payload
        self.json_error = json_error

    def raise_for_status(
        self,
    ) -> None:
        return None

    def json(
        self,
    ) -> Any:

        if self.json_error is not None:
            raise self.json_error

        return self.payload


class FakeHttpClient:

    def __init__(
        self,
        response: FakeResponse,
    ) -> None:

        self.response = response
        self.calls = 0

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> FakeResponse:

        self.calls += 1

        return self.response

    async def aclose(
        self,
    ) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response,expected_reason",
    [
        (
            FakeResponse(
                json_error=ValueError(
                    "invalid json"
                ),
            ),
            "invalid_json",
        ),
        (
            FakeResponse(
                payload=[
                    "unexpected",
                    "list",
                ],
            ),
            "not_object",
        ),
        (
            FakeResponse(
                payload={
                    "status": "failed",
                },
            ),
            "not_accepted",
        ),
    ],
)
async def test_invalid_post_call_response_is_classified(
    caplog: pytest.LogCaptureFixture,
    response: FakeResponse,
    expected_reason: str,
) -> None:

    client = PostCallClient(
        base_url="http://test",
    )

    fake_http = FakeHttpClient(
        response
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
            PostCallResponseError
        ):

            await client.send_booking_confirmation(
                tenant_id="clinic-001",
                appointment_reference=(
                    "APT-TEST-001"
                ),
            )

    assert fake_http.calls == 1

    assert (
        f"reason={expected_reason}"
        in caplog.text
    )

    await client.close()