from __future__ import annotations

import json
from datetime import (
    date,
    time,
)
from uuid import (
    uuid4,
)

import httpx
import pytest

from app.integrations.n8n_whatsapp_client import (
    N8NWhatsAppClient,
)

from app.schemas.post_call import (
    WhatsAppBookingNotificationPayload,
)


def make_payload():

    return (
        WhatsAppBookingNotificationPayload(
            language="ar",

            appointment_reference=
                "APT-260827-ABC123",

            recipient_phone=
                "+201023456789",

            patient_name=
                "آية أحمد",

            doctor_name=
                "دكتور ماهر",

            scheduled_date=
                date(
                    2026,
                    8,
                    28,
                ),

            start_time=
                time(
                    17,
                    0,
                ),

            end_time=
                time(
                    17,
                    30,
                ),

            appointment_status=
                "confirmed",

            original_channel=
                "voice",
        )
    )


@pytest.mark.asyncio
async def test_n8n_client_sends_expected_payload():

    captured = {}

    async def handler(
        request:
            httpx.Request,
    ):

        captured[
            "headers"
        ] = request.headers

        captured[
            "body"
        ] = json.loads(
            request.content
        )

        return (
            httpx.Response(
                status_code=200,
                json={
                    "ok": True,
                },
            )
        )

    transport = (
        httpx.MockTransport(
            handler
        )
    )

    http_client = (
        httpx.AsyncClient(
            transport=
                transport
        )
    )

    provider_id = (
        uuid4()
    )

    client = (
        N8NWhatsAppClient(
            webhook_url=(
                "https://n8n.example/"
                "webhook/medmind"
            ),

            webhook_secret=
                "test-secret",

            http_client=
                http_client,
        )
    )

    try:

        result = await (
            client
            .send_booking_confirmation(
                provider_id=
                    provider_id,

                payload=
                    make_payload(),

                message=
                    "test message",
            )
        )

    finally:

        await (
            http_client.aclose()
        )

    assert (
        result["status"]
        == "accepted"
    )

    assert (
        captured["body"]["to"]
        == "+201023456789"
    )

    assert (
        captured["body"]["channel"]
        == "whatsapp"
    )

    assert (
        captured["body"]["language"]
        == "ar"
    )

    assert (
        captured["body"]["message"]
        == "test message"
    )

    assert (
        captured[
            "headers"
        ][
            "X-MedMind-Webhook-Secret"
        ]
        == "test-secret"
    )


@pytest.mark.asyncio
async def test_n8n_event_id_is_stable():

    event_ids = []

    async def handler(
        request:
            httpx.Request,
    ):

        body = json.loads(
            request.content
        )

        event_ids.append(
            body[
                "event_id"
            ]
        )

        return (
            httpx.Response(
                200
            )
        )

    http_client = (
        httpx.AsyncClient(
            transport=
                httpx.MockTransport(
                    handler
                )
        )
    )

    provider_id = (
        uuid4()
    )

    client = (
        N8NWhatsAppClient(
            webhook_url=
                "https://n8n.test/webhook",

            http_client=
                http_client,
        )
    )

    try:

        for _ in range(
            2
        ):

            await (
                client
                .send_booking_confirmation(
                    provider_id=
                        provider_id,

                    payload=
                        make_payload(),

                    message=
                        "hello",
                )
            )

    finally:

        await (
            http_client.aclose()
        )

    assert (
        event_ids[0]
        == event_ids[1]
    )


@pytest.mark.asyncio
async def test_n8n_requires_webhook_url():

    client = (
        N8NWhatsAppClient(
            webhook_url=None,
            http_client=
                httpx.AsyncClient(),
        )
    )

    # Force test independence from local .env
    client.webhook_url = None

    try:

        with pytest.raises(
            RuntimeError
        ):

            await (
                client
                .send_booking_confirmation(
                    provider_id=
                        uuid4(),

                    payload=
                        make_payload(),

                    message=
                        "hello",
                )
            )

    finally:

        await (
            client
            ._client
            .aclose()
        )