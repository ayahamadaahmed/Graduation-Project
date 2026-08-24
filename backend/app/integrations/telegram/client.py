from __future__ import annotations

from typing import Any

import httpx


class TelegramAPIError(
    RuntimeError
):
    pass


class TelegramClient:
    def __init__(
        self,
        *,
        bot_token: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        token = bot_token.strip()

        if not token:
            raise ValueError(
                "Telegram bot token is required."
            )

        self.base_url = (
            "https://api.telegram.org/"
            f"bot{token}"
        )

        self.timeout_seconds = (
            timeout_seconds
        )

    async def _post(
        self,
        method: str,
        payload: dict[str, Any],
    ) -> Any:
        url = (
            f"{self.base_url}/{method}"
        )

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds
            ) as client:
                response = await client.post(
                    url,
                    json=payload,
                )

        except httpx.HTTPError as exc:
            raise TelegramAPIError(
                "Telegram API request failed."
            ) from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise TelegramAPIError(
                "Telegram returned invalid JSON."
            ) from exc

        if (
            response.status_code >= 400
            or not body.get("ok")
        ):
            description = str(
                body.get("description")
                or "Unknown Telegram API error."
            )

            raise TelegramAPIError(
                description
            )

        return body.get("result")

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup: dict | None = None,
    ) -> Any:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
        }

        if reply_markup is not None:
            payload["reply_markup"] = (
                reply_markup
            )

        return await self._post(
            "sendMessage",
            payload,
        )

    async def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
    ) -> Any:
        payload: dict[str, Any] = {
            "callback_query_id":
                callback_query_id,
        }

        if text:
            payload["text"] = text

        return await self._post(
            "answerCallbackQuery",
            payload,
        )

    async def set_webhook(
        self,
        *,
        webhook_url: str,
        secret_token: str,
    ) -> Any:
        return await self._post(
            "setWebhook",
            {
                "url":
                    webhook_url,

                "secret_token":
                    secret_token,

                "allowed_updates": [
                    "message",
                    "callback_query",
                ],

                "drop_pending_updates":
                    True,
            },
        )

    async def delete_webhook(
        self,
    ) -> Any:
        return await self._post(
            "deleteWebhook",
            {
                "drop_pending_updates":
                    False,
            },
        )

    async def get_webhook_info(
        self,
    ) -> Any:
        return await self._post(
            "getWebhookInfo",
            {},
        )