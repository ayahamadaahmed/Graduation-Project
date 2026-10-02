from __future__ import annotations

import logging
from typing import Any

import pytest

from voice_gateway.medmind_client import MedMindClient


class FakeResponse:
    def __init__(
        self,
        payload: dict[str, Any],
    ) -> None:
        self._payload = payload

    def raise_for_status(
        self,
    ) -> None:
        return None

    def json(
        self,
    ) -> dict[str, Any]:
        return self._payload


class FakeHttpClient:
    def __init__(
        self,
        payload: dict[str, Any],
    ) -> None:
        self.payload = payload
        self.last_request_json: dict[str, Any] | None = None
        self.last_request_headers: dict[str, str] | None = None

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> FakeResponse:
        self.last_request_headers = headers
        self.last_request_json = json

        return FakeResponse(
            self.payload
        )

    async def aclose(
        self,
    ) -> None:
        return None


def make_response(
    *,
    stage: str,
    intent: str,
) -> dict[str, Any]:
    return {
        "session_id": "voice-test-session",
        "reply": "تمام",
        "stage": stage,
        "intent": intent,
        "nlu": {},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sensitive_message,stage,intent",
    [
        (
            "12345678912345",
            "awaiting_phone_confirmation",
            "provide_national_id",
        ),
        (
            "01023456789",
            "awaiting_phone_confirmation",
            "provide_phone",
        ),
    ],
)
async def test_sensitive_voice_message_is_redacted_from_logs(
    caplog: pytest.LogCaptureFixture,
    sensitive_message: str,
    stage: str,
    intent: str,
) -> None:
    """
    National ID / phone must still be sent to MedMind,
    but must never appear raw in Voice Gateway logs.
    """

    client = MedMindClient(
        base_url="http://test"
    )

    fake_http = FakeHttpClient(
        make_response(
            stage=stage,
            intent=intent,
        )
    )

    client._client = fake_http  # type: ignore[assignment]

    with caplog.at_level(
        logging.INFO,
        logger=(
            "medmind.voice_gateway."
            "medmind_client"
        ),
    ):
        result = await client.chat(
            session_id="voice-test-session",
            tenant_id="clinic-001",
            message=sensitive_message,
            sensitive=True,
        )

    # --------------------------------------------------
    # Backend must still receive the real value.
    # --------------------------------------------------

    assert (
        fake_http.last_request_json
        is not None
    )

    assert (
        fake_http.last_request_json["message"]
        == sensitive_message
    )

    assert (
        fake_http.last_request_json["channel"]
        == "voice"
    )

    # --------------------------------------------------
    # But logs must never contain the real value.
    # --------------------------------------------------

    assert (
        sensitive_message
        not in caplog.text
    )

    assert (
        f"message_chars={len(sensitive_message)}"
        in caplog.text
    )

    assert (
        "sensitive=True"
        in caplog.text
    )

    assert result["stage"] == stage
    assert result["intent"] == intent

    await client.close()


@pytest.mark.asyncio
async def test_normal_voice_message_is_not_logged_raw(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Ordinary conversational text must be sent to MedMind,
    but must never appear raw in Voice Gateway logs.
    """

    message = "عايز احجز كشف جلدية"

    client = MedMindClient(
        base_url="http://test"
    )

    fake_http = FakeHttpClient(
        make_response(
            stage="awaiting_doctor",
            intent="book_appointment",
        )
    )

    client._client = fake_http  # type: ignore[assignment]

    with caplog.at_level(
        logging.INFO,
        logger=(
            "medmind.voice_gateway."
            "medmind_client"
        ),
    ):
        await client.chat(
            session_id="voice-test-session",
            tenant_id="clinic-001",
            message=message,
            sensitive=False,
        )

    assert message not in caplog.text

    assert (
        f"message_chars={len(message)}"
        in caplog.text
    )

    assert (
        "sensitive=False"
        in caplog.text
    )

    await client.close()