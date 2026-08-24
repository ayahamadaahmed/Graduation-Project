from __future__ import annotations

import logging
import os
from typing import Any

import httpx


logger = logging.getLogger(
    "medmind.voice_gateway.medmind_client"
)


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
    ) -> None:
        self._base_url = (
            base_url
            or os.getenv(
                "MEDMIND_BACKEND_URL",
                "http://127.0.0.1:8001",
            )
        ).rstrip("/")

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(
                30.0,
                connect=5.0,
            ),
        )

    @staticmethod
    def _first_not_none(*values: Any) -> Any:
        for value in values:
            if value is not None:
                return value

        return None

    async def chat(
        self,
        *,
        tenant_id: str,
        session_id: str,
        message: str,
    ) -> dict[str, Any]:
        response = await self._client.post(
            "/api/v1/ai/chat",
            headers={
                "X-Tenant-ID": tenant_id,
            },
            json={
                "session_id": session_id,
                "message": message,
            },
        )

        response.raise_for_status()

        data = response.json()

        if not isinstance(data, dict):
            raise RuntimeError(
                "MedMind returned an invalid response"
            )

        reply = data.get("reply")

        if not isinstance(reply, str) or not reply.strip():
            raise RuntimeError(
                "MedMind response has no valid reply"
            )

        # -------------------------------------------------
        # NLU observability
        # -------------------------------------------------

        nlu = data.get("nlu")

        if not isinstance(nlu, dict):
            nlu = {}

        intent = data.get("intent")
        stage = data.get("stage")

        nlu_source = self._first_not_none(
            nlu.get("source"),
            data.get("nlu_source"),
        )

        confidence = self._first_not_none(
            nlu.get("confidence"),
            data.get("confidence"),
        )

        fallback_used = self._first_not_none(
            nlu.get("fallback_used"),
            data.get("fallback_used"),
        )

        marbert_intent = self._first_not_none(
            nlu.get("marbert_intent"),
            data.get("marbert_intent"),
        )

        marbert_confidence = self._first_not_none(
            nlu.get("marbert_confidence"),
            data.get("marbert_confidence"),
        )

        logger.info(
            "medmind_voice_response "
            "session_id=%s "
            "text=%r "
            "stage=%s "
            "intent=%s "
            "nlu_source=%s "
            "confidence=%s "
            "fallback_used=%s "
            "marbert_intent=%s "
            "marbert_confidence=%s",
            session_id,
            message,
            stage,
            intent,
            nlu_source,
            confidence,
            fallback_used,
            marbert_intent,
            marbert_confidence,
        )

        return data

    async def close(self) -> None:
        await self._client.aclose()