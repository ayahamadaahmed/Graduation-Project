from __future__ import annotations

import logging
import os
from typing import Any

import httpx


logger = logging.getLogger(
    "medmind.voice_gateway.post_call"
)


class PostCallResponseError(
    RuntimeError
):
    """
    Post-call endpoint returned HTTP success,
    but the response payload did not satisfy
    the Voice Gateway contract.
    """

class PostCallHTTPError(
    RuntimeError
):
    """
    Post-call backend returned a non-success
    HTTP status.

    retryable indicates whether the status
    may be transient. This class does NOT
    perform an automatic retry.
    """

    def __init__(
        self,
        *,
        status_code: int,
    ) -> None:

        self.status_code = (
            status_code
        )

        self.retryable = (
            status_code
            in {
                408,
                425,
                429,
                500,
                502,
                503,
                504,
            }
        )

        super().__init__(
            "Post-call backend returned "
            f"HTTP {status_code}"
        )

class PostCallClient:

    def __init__(
        self,
        *,
        base_url: str | None = None,
    ) -> None:

        self._base_url = (
            base_url
            or os.getenv(
                "MEDMIND_BACKEND_URL",
                "http://127.0.0.1:8001",
            )
        ).rstrip("/")

        self._client = (
            httpx.AsyncClient(
                base_url=
                    self._base_url,

                timeout=
                    httpx.Timeout(
                        10.0,
                        connect=5.0,
                    ),
            )
        )

    async def send_booking_confirmation(
        self,
        *,
        tenant_id: str,
        appointment_reference: str,
    ) -> dict[str, Any]:

        response = await (
            self._client.post(
                (
                    "/api/v1/post-call/"
                    "booking-confirmation"
                ),

                headers={
                    "X-Tenant-ID":
                        tenant_id,
                },

                json={
                    "event_type":
                        "booking_confirmation",

                    "appointment_reference":
                        appointment_reference,

                    "source":
                        "voice",
                },
            )
        )

        try:

            response.raise_for_status()

        except httpx.HTTPStatusError as exc:

            logger.error(
                "post_call_http_error "
                "status_code=%d "
                "retryable=%s "
                "action=no_automatic_retry",
                exc.response.status_code,
                (
                    exc.response.status_code
                    in {
                        408,
                        425,
                        429,
                        500,
                        502,
                        503,
                        504,
                    }
                ),
            )

            raise PostCallHTTPError(
                status_code=(
                    exc.response.status_code
                ),
            ) from exc

        try:

            data = response.json()

        except ValueError as exc:

            logger.error(
                "post_call_invalid_response "
                "reason=invalid_json"
            )

            raise PostCallResponseError(
                "Post-call endpoint returned invalid JSON"
            ) from exc


        if not isinstance(
            data,
            dict,
        ):

            logger.error(
                "post_call_invalid_response "
                "reason=not_object"
            )

            raise PostCallResponseError(
                "Post-call endpoint returned "
                "an invalid response"
            )


        if (
            data.get("status")
            != "accepted"
        ):

            logger.error(
                "post_call_invalid_response "
                "reason=not_accepted"
            )

            raise PostCallResponseError(
                "Post-call endpoint did not "
                "accept the notification"
        )

        return data

    async def close(
        self,
    ) -> None:

        await (
            self._client.aclose()
        )