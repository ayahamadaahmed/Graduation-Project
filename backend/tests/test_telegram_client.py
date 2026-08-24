import httpx
import pytest

from app.integrations.telegram.client import (
    TelegramAPIError,
    TelegramClient,
)


@pytest.mark.asyncio
async def test_send_message_payload(
    monkeypatch,
):
    captured = {}

    async def fake_post(
        self,
        url,
        *,
        json,
    ):
        captured["url"] = url
        captured["json"] = json

        request = httpx.Request(
            "POST",
            url,
        )

        return httpx.Response(
            200,
            request=request,
            json={
                "ok": True,
                "result": {
                    "message_id": 1,
                },
            },
        )

    monkeypatch.setattr(
        httpx.AsyncClient,
        "post",
        fake_post,
    )

    client = TelegramClient(
        bot_token="test-token"
    )

    result = await client.send_message(
        chat_id=123,
        text="Hello",
        reply_markup={
            "inline_keyboard": [],
        },
    )

    assert captured["url"] == (
        "https://api.telegram.org/"
        "bottest-token/sendMessage"
    )

    assert captured["json"] == {
        "chat_id": 123,
        "text": "Hello",
        "reply_markup": {
            "inline_keyboard": [],
        },
    }

    assert result["message_id"] == 1


@pytest.mark.asyncio
async def test_telegram_api_error(
    monkeypatch,
):
    async def fake_post(
        self,
        url,
        *,
        json,
    ):
        request = httpx.Request(
            "POST",
            url,
        )

        return httpx.Response(
            400,
            request=request,
            json={
                "ok": False,
                "description":
                    "Bad Request",
            },
        )

    monkeypatch.setattr(
        httpx.AsyncClient,
        "post",
        fake_post,
    )

    client = TelegramClient(
        bot_token="test-token"
    )

    with pytest.raises(
        TelegramAPIError,
        match="Bad Request",
    ):
        await client.send_message(
            chat_id=123,
            text="Hello",
        )


def test_empty_token_is_rejected():
    with pytest.raises(
        ValueError
    ):
        TelegramClient(
            bot_token="  "
        )