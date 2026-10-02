from __future__ import annotations

import os
from typing import Any
from uuid import UUID

import httpx

from app.schemas.post_call import (
    WhatsAppBookingNotificationPayload,
)


class N8NWhatsAppClient:

    def __init__(
        self,
        *,
        webhook_url: str | None = None,
        webhook_secret: str | None = None,
        http_client:
            httpx.AsyncClient
            | None = None,
    ) -> None:

        self.webhook_url = (
            webhook_url
            or os.getenv(
                "N8N_WHATSAPP_WEBHOOK_URL"
            )
        )

        self.webhook_secret = (
            webhook_secret
            if webhook_secret is not None
            else os.getenv(
                "N8N_WHATSAPP_WEBHOOK_SECRET"
            )
        )

        self._owns_client = (
            http_client is None
        )

        self._client = (
            http_client
            or httpx.AsyncClient(
                timeout=httpx.Timeout(
                    15.0,
                    connect=5.0,
                )
            )
        )

    async def send_booking_confirmation(
        self,
        *,
        provider_id: UUID,
        payload:
            WhatsAppBookingNotificationPayload,
    ) -> dict[str, Any]:

        if not self.webhook_url:

            raise RuntimeError(
                "N8N_WHATSAPP_WEBHOOK_URL "
                "is not configured"
            )

        # ====================================================
        # Stable event identity
        #
        # n8n can use this for deduplication.
        # ====================================================

        event_id = (
            "booking_confirmation:"
            f"{provider_id}:"
            f"{payload.appointment_reference}"
        )

        headers = {
            "Content-Type":
                "application/json",

            "X-MedMind-Event-ID":
                event_id,
        }

        if self.webhook_secret:

            headers[
                "X-MedMind-Webhook-Secret"
            ] = (
                self.webhook_secret
            )

        body = {
            "event_id":
                event_id,

            "event_type":
                payload.event_type,

            "tenant_id":
                str(
                    provider_id
                ),

            "channel":
                "whatsapp",

            "to":
                payload.recipient_phone,

            "language":
                payload.language,

            "appointment":
                payload.model_dump(
                    mode="json",
                    exclude={
                        "recipient_phone",
                    },
                ),
        }

        response = await (
            self._client.post(
                self.webhook_url,
                headers=headers,
                json=body,
            )
        )

        response.raise_for_status()

        return {
            "status":
                "accepted",

            "event_id":
                event_id,

            "http_status":
                response.status_code,
        }

    async def close(
        self,
    ) -> None:

        if self._owns_client:

            await (
                self._client.aclose()
            )