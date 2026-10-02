from __future__ import annotations

import logging
import os
from typing import Any

import httpx


logger = logging.getLogger(
    "medmind.voice_gateway.medmind_client"
)


DEFAULT_REQUEST_TIMEOUT_SECONDS = 8.0


class MedMindTimeoutError(
    RuntimeError
):
    """
    MedMind did not respond within the
    Voice Gateway response deadline.
    """
class MedMindHTTPError(
    RuntimeError
):
    """
    MedMind returned a non-success HTTP status.

    The Voice Gateway must not automatically
    retry because the backend request may have
    already caused a state-changing operation.
    """

    def __init__(
        self,
        *,
        status_code: int,
    ) -> None:

        self.status_code = (
            status_code
        )

        super().__init__(
            "MedMind backend returned "
            f"HTTP {status_code}"
        )   

class MedMindResponseError(
    RuntimeError
):
    """
    MedMind returned HTTP success,
    but the response payload was invalid
    for the Voice Gateway contract.
    """         

class MedMindClient:
    """
    Async client for the existing MedMind production chat API.

    Voice Gateway does not duplicate any MedMind logic.
    It forwards final transcripts to the same backend used by chat.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        request_timeout_seconds: float = (
            DEFAULT_REQUEST_TIMEOUT_SECONDS
        ),
    ) -> None:
        self._base_url = (
            base_url
            or os.getenv(
                "MEDMIND_BACKEND_URL",
                "http://127.0.0.1:8001",
            )
        ).rstrip("/")

        if request_timeout_seconds <= 0:
            raise ValueError(
                "request_timeout_seconds "
                "must be greater than zero"
            )

        self._request_timeout_seconds = (
            request_timeout_seconds
        )

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(
                self._request_timeout_seconds,
                connect=min(
                    5.0,
                    self._request_timeout_seconds,
                ),
            ),
        )

    @staticmethod
    def _first_not_none(
        *values: Any,
    ) -> Any:
        for value in values:
            if value is not None:
                return value

        return None


    async def warmup(
        self,
        *,
        tenant_id: str,
    ) -> bool:
        """
        Best-effort MedMind pre-warm for an incoming voice call.

        Warm-up is an optimization only.
        Failure must never block or terminate the call.
        """

        try:
            response = await self._client.post(
                "/api/v1/ai/warmup",
                headers={
                    "X-Tenant-ID": tenant_id,
                },
                timeout=min(
                    2.0,
                    self._request_timeout_seconds,
                ),
            )

            response.raise_for_status()

        except httpx.TimeoutException:

            logger.warning(
                "medmind_warmup_timeout "
                "tenant_id=%s "
                "action=continue_call",
                tenant_id,
            )

            return False

        except httpx.HTTPStatusError as exc:

            logger.warning(
                "medmind_warmup_http_error "
                "tenant_id=%s "
                "status_code=%d "
                "action=continue_call",
                tenant_id,
                exc.response.status_code,
            )

            return False

        except httpx.RequestError:

            logger.exception(
                "medmind_warmup_request_error "
                "tenant_id=%s "
                "action=continue_call",
                tenant_id,
            )

            return False

        logger.info(
            "medmind_warmup_ready "
            "tenant_id=%s",
            tenant_id,
        )

        return True

    async def chat(
        self,
        *,
        session_id: str,
        tenant_id: str,
        message: str,
        sensitive: bool = False,
    ) -> dict[str, Any]:
        """
        Send one final voice transcript to MedMind.

        `sensitive=True` means the transcript may contain sensitive
        information such as a national ID or phone number.

        Sensitive content is still sent to MedMind because the backend
        needs it for the workflow, but the raw content is never written
        to this client's logs.
        """

        # -------------------------------------------------
        # Request
        # -------------------------------------------------

        try:

            response = await self._client.post(
                "/api/v1/ai/chat",
                headers={
                    "X-Tenant-ID": tenant_id,
                },
                json={
                    "session_id": session_id,
                    "message": message,
                    "channel": "voice",
                },
            )

        except httpx.TimeoutException as exc:

            logger.error(
                "medmind_voice_timeout "
                "session_id=%s "
                "timeout_seconds=%.2f "
                "sensitive=%s "
                "action=no_retry",
                session_id,
                self._request_timeout_seconds,
                sensitive,
            )

            raise MedMindTimeoutError(
                "MedMind backend response timed out"
            ) from exc

        try:

            response.raise_for_status()

        except httpx.HTTPStatusError as exc:

            logger.error(
                "medmind_voice_http_error "
                "session_id=%s "
                "status_code=%d "
                "sensitive=%s "
                "action=no_retry",
                session_id,
                exc.response.status_code,
                sensitive,
            )

            raise MedMindHTTPError(
                status_code=(
                    exc.response.status_code
                ),
            ) from exc

        # -------------------------------------------------
        # Response validation
        # -------------------------------------------------

        try:

            data = response.json()

        except ValueError as exc:

            logger.error(
                "medmind_voice_invalid_response "
                "session_id=%s "
                "reason=invalid_json",
                session_id,
            )

            raise MedMindResponseError(
                "MedMind returned invalid JSON"
            ) from exc


        if not isinstance(
            data,
            dict,
        ):

            logger.error(
                "medmind_voice_invalid_response "
                "session_id=%s "
                "reason=not_object",
                session_id,
            )

            raise MedMindResponseError(
                "MedMind returned an invalid response"
            )
        reply = data.get(
            "reply"
        )

        if (
            not isinstance(
                reply,
                str,
            )
            or not reply.strip()
        ):
            logger.error(
                "medmind_voice_invalid_response "
                "session_id=%s "
                "reason=invalid_reply",
                session_id,
            )

            raise MedMindResponseError(
                "MedMind response has no valid reply"
            )

        # -------------------------------------------------
        # NLU observability
        # -------------------------------------------------

        nlu = data.get(
            "nlu"
        )

        if not isinstance(
            nlu,
            dict,
        ):
            nlu = {}

        intent = data.get(
            "intent"
        )

        stage = data.get(
            "stage"
        )

        nlu_source = self._first_not_none(
            nlu.get(
                "source"
            ),
            data.get(
                "nlu_source"
            ),
        )

        confidence = self._first_not_none(
            nlu.get(
                "confidence"
            ),
            data.get(
                "confidence"
            ),
        )

        fallback_used = self._first_not_none(
            nlu.get(
                "fallback_used"
            ),
            data.get(
                "fallback_used"
            ),
        )


        logger.info(
            "medmind_voice_response "
            "session_id=%s "
            "message_chars=%d "
            "sensitive=%s "
            "stage=%s "
            "intent=%s "
            "nlu_source=%s "
            "confidence=%s "
            "fallback_used=%s",
            session_id,
            len(
                message
            ),
            sensitive,
            stage,
            intent,
            nlu_source,
            confidence,
            fallback_used,
        )

        return data

    async def close(
        self,
    ) -> None:
        await self._client.aclose()