from contextlib import (
    asynccontextmanager,
)
from uuid import (
    uuid4,
)
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import (
    TestClient,
)

from app.api.dependencies import (
    get_catalog_service,
    get_telegram_client,
)
from app.api.routers import (
    telegram as telegram_module,
)

from app.api.routers import (
    telegram,
)

from app.core.config import (
    get_settings,
)

from app.main import app


class FakeTelegramClient:
    def __init__(self):
        self.messages = []
        self.callbacks = []

    async def send_message(
        self,
        *,
        chat_id,
        text,
        reply_markup=None,
    ):
        self.messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
            }
        )

        return {
            "message_id": 1,
        }

    async def answer_callback_query(
        self,
        *,
        callback_query_id,
        text=None,
    ):
        self.callbacks.append(
            {
                "callback_query_id":
                    callback_query_id,
                "text": text,
            }
        )

        return True


class FakePublicGraph:
    async def ainvoke(
        self,
        values,
        config,
    ):
        return {
            "session_id":
                values["session_id"],

            "stage":
                "awaiting_org_type",

            "reply":
                "Ø£Ù‡Ù„Ù‹Ø§ Ø¨ÙŠÙƒ ÙÙŠ MedMind ðŸ‘‹",

            "reply_markup": {
                "inline_keyboard": [
                    [
                        {
                            "text": "Ø¹ÙŠØ§Ø¯Ø©",
                            "callback_data":
                                "org:clinic",
                        }
                    ]
                ]
            },

            "onboarding_completed":
                False,
        }

    async def aget_state(
        self,
        config,
    ):
        return SimpleNamespace(
            values={}
        )


class FakeBookingGraph:
    async def ainvoke(
        self,
        values,
        config,
    ):
        return {
            "reply": "Booking reply",
            "stage": "new",
        }


fake_telegram = FakeTelegramClient()


@asynccontextmanager
async def fake_lifespan(
    application,
):
    application.state.public_onboarding_graph = (
        FakePublicGraph()
    )

    application.state.booking_graph = (
        FakeBookingGraph()
    )

    yield

    application.state.public_onboarding_graph = None
    application.state.booking_graph = None


def fake_catalog_service():
    return object()


def fake_telegram_client():
    return fake_telegram


def test_start_message_opens_public_onboarding(
    monkeypatch,
):
    fake_telegram.messages.clear()
    fake_telegram.callbacks.clear()

    monkeypatch.setattr(
        telegram,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_webhook_secret=(
                "test-webhook-secret"
            )
        ),
    )

    original_lifespan = app.router.lifespan_context

    app.router.lifespan_context = (
        fake_lifespan
    )

    app.dependency_overrides[
        get_catalog_service
    ] = fake_catalog_service

    app.dependency_overrides[
        get_telegram_client
    ] = fake_telegram_client

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/telegram/webhook",
                headers={
                    (
                        "X-Telegram-Bot-"
                        "Api-Secret-Token"
                    ):
                        "test-webhook-secret",
                },
                json={
                    "update_id": 1001,
                    "message": {
                        "message_id": 1,
                        "from": {
                            "id": 501,
                            "is_bot": False,
                            "first_name": "Aya",
                            "language_code": "ar",
                        },
                        "chat": {
                            "id": 501,
                            "type": "private",
                            "first_name": "Aya",
                        },
                        "text": "/start",
                    },
                },
            )

        assert response.status_code == 200
        assert response.json() == {
            "ok": True
        }

        assert len(
            fake_telegram.messages
        ) == 1

        sent = fake_telegram.messages[0]

        assert sent["chat_id"] == 501

        assert (
            "MedMind"
            in sent["text"]
        )

        assert sent["reply_markup"][
            "inline_keyboard"
        ][0][0]["callback_data"] == (
            "org:clinic"
        )

    finally:
        app.dependency_overrides.clear()

        app.router.lifespan_context = (
            original_lifespan
        )


def test_first_greeting_sends_reply_then_onboarding(
    monkeypatch,
):
    fake_telegram.messages.clear()
    fake_telegram.callbacks.clear()

    monkeypatch.setattr(
        telegram,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_webhook_secret="test-webhook-secret"
        ),
    )

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = fake_lifespan
    app.dependency_overrides[
        get_catalog_service
    ] = fake_catalog_service
    app.dependency_overrides[
        get_telegram_client
    ] = fake_telegram_client

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/telegram/webhook",
                headers={
                    "X-Telegram-Bot-Api-Secret-Token":
                        "test-webhook-secret",
                },
                json={
                    "update_id": 1003,
                    "message": {
                        "message_id": 1,
                        "from": {
                            "id": 501,
                            "is_bot": False,
                            "first_name": "Aya",
                        },
                        "chat": {
                            "id": 501,
                            "type": "private",
                        },
                        "text": "السلام عليكم",
                    },
                },
            )

        assert response.status_code == 200
        assert len(fake_telegram.messages) == 2
        assert "وعليكم السلام" in fake_telegram.messages[0]["text"]
        assert "MedMind" in fake_telegram.messages[1]["text"]
        assert (
            fake_telegram.messages[1]["reply_markup"]
            ["inline_keyboard"][0][0]["callback_data"]
            == "org:clinic"
        )

    finally:
        app.dependency_overrides.clear()
        app.router.lifespan_context = original_lifespan


def test_invalid_webhook_secret_is_rejected(
    monkeypatch,
):
    monkeypatch.setattr(
        telegram,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_webhook_secret=(
                "correct-secret"
            )
        ),
    )

    original_lifespan = app.router.lifespan_context

    app.router.lifespan_context = (
        fake_lifespan
    )
    app.dependency_overrides[
        get_catalog_service
    ] = fake_catalog_service

    app.dependency_overrides[
        get_telegram_client
    ] = fake_telegram_client

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/telegram/webhook",
                headers={
                    (
                        "X-Telegram-Bot-"
                        "Api-Secret-Token"
                    ):
                        "wrong-secret",
                },
                json={
                    "update_id": 1002,
                },
            )

        assert response.status_code == 403

        assert response.json()[
            "detail"
        ]["code"] == (
            "INVALID_TELEGRAM_SECRET"
        )

    finally:
        app.dependency_overrides.clear()

        app.router.lifespan_context = (
            original_lifespan
        )


class FakeProvider:
    def __init__(
        self,
        *,
        provider_id,
        tenant_key,
    ):
        self.id = provider_id
        self.name = "Andro Health"
        self.slug = "andro-health"
        self.org_type = "clinic"
        self.default_language = "ar"
        self.tenant_key = tenant_key


class FakeBranch:
    def __init__(
        self,
        *,
        branch_id,
        provider_id,
    ):
        self.id = branch_id
        self.provider_id = provider_id
        self.code = "DOK"
        self.name_ar = "الدقي"
        self.name_en = "Dokki"
        self.address_ar = None
        self.address_en = None
        self.governorate = "Giza"


class StatefulFakePublicGraph:
    def __init__(
        self,
        *,
        provider,
        branch,
    ):
        self.provider = provider
        self.branch = branch

        self.state = {}

    async def ainvoke(
        self,
        values,
        config,
    ):
        callback_data = values.get(
            "callback_data"
        )

        if callback_data == (
            "restart:onboarding"
        ):
            self.state = {
                "stage":
                    "awaiting_org_type",

                "onboarding_completed":
                    False,

                "reply":
                    "اختاري عيادة ولا مستشفى",

                "reply_markup": {
                    "inline_keyboard": [
                        [
                            {
                                "text": "عيادة",
                                "callback_data":
                                    "org:clinic",
                            }
                        ]
                    ]
                },
            }

        elif callback_data == "org:clinic":
            self.state = {
                **self.state,

                "stage":
                    "awaiting_provider",

                "org_type":
                    "clinic",

                "reply":
                    "اختاري مقدم الخدمة",

                "reply_markup": {
                    "inline_keyboard": [
                        [
                            {
                                "text":
                                    self.provider.name,

                                "callback_data": (
                                    "provider:"
                                    f"{self.provider.id}"
                                ),
                            }
                        ]
                    ]
                },
            }

        elif callback_data == (
            f"provider:{self.provider.id}"
        ):
            self.state = {
                **self.state,

                "stage":
                    "awaiting_branch",

                "provider_id":
                    str(
                        self.provider.id
                    ),

                "provider_name":
                    self.provider.name,

                "tenant_key":
                    self.provider.tenant_key,

                "reply":
                    "اختاري الفرع",

                "reply_markup": {
                    "inline_keyboard": [
                        [
                            {
                                "text":
                                    self.branch.name_ar,

                                "callback_data": (
                                    "branch:"
                                    f"{self.branch.id}"
                                ),
                            }
                        ]
                    ]
                },
            }

        elif callback_data == (
            f"branch:{self.branch.id}"
        ):
            self.state = {
                **self.state,

                "stage":
                    "ready_for_booking",

                "branch_id":
                    str(
                        self.branch.id
                    ),

                "branch_code":
                    self.branch.code,

                "branch_name":
                    self.branch.name_ar,

                "onboarding_completed":
                    True,

                "reply":
                    "تم اختيار فرع الدقي ✅",

                "reply_markup":
                    None,
            }

        return dict(
            self.state
        )

    async def aget_state(
        self,
        config,
    ):
        return SimpleNamespace(
            values=dict(
                self.state
            )
        )


class CapturingBookingGraph:
    def __init__(self):
        self.calls = []

    async def ainvoke(
        self,
        values,
        config,
    ):
        self.calls.append(
            {
                "values": values,
                "config": config,
            }
        )

        return {
            "reply":
                "ممكن تقولي التخصص المطلوب؟",

            "stage":
                "awaiting_specialty",

            "language":
                "ar",
        }


class CompletedBookingGraph:
    async def aget_state(
        self,
        config,
    ):
        return SimpleNamespace(values={})

    async def ainvoke(
        self,
        values,
        config,
    ):
        return {
            "reply": "تم تأكيد الحجز. رقم الحجز APT-TEST-001.",
            "stage": "booking_completed",
            "intent": "confirm_action",
            "operation_id": "operation-001",
            "operation_type": "book_appointment",
            "operation_status": "completed",
        }


def test_complete_onboarding_then_booking_handoff(
    monkeypatch,
):
    fake_telegram.messages.clear()
    fake_telegram.callbacks.clear()

    provider_id = uuid4()
    branch_id = uuid4()

    provider = FakeProvider(
        provider_id=provider_id,
        tenant_key="clinic-001",
    )

    branch = FakeBranch(
        branch_id=branch_id,
        provider_id=provider_id,
    )

    public_graph = (
        StatefulFakePublicGraph(
            provider=provider,
            branch=branch,
        )
    )

    booking_graph = (
        CapturingBookingGraph()
    )

    @asynccontextmanager
    async def onboarding_lifespan(
        application,
    ):
        application.state.public_onboarding_graph = (
            public_graph
        )

        application.state.booking_graph = (
            booking_graph
        )

        yield

        application.state.public_onboarding_graph = None
        application.state.booking_graph = None

    monkeypatch.setattr(
        telegram,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_webhook_secret=(
                "test-webhook-secret"
            )
        ),
    )

    original_lifespan = (
        app.router.lifespan_context
    )

    app.router.lifespan_context = (
        onboarding_lifespan
    )

    app.dependency_overrides[
        get_catalog_service
    ] = fake_catalog_service

    app.dependency_overrides[
        get_telegram_client
    ] = fake_telegram_client

    headers = {
        (
            "X-Telegram-Bot-"
            "Api-Secret-Token"
        ):
            "test-webhook-secret",
    }

    def callback_payload(
        *,
        update_id,
        callback_id,
        data,
    ):
        return {
            "update_id": update_id,

            "callback_query": {
                "id": callback_id,

                "from": {
                    "id": 501,
                    "is_bot": False,
                    "first_name": "Aya",
                },

                "message": {
                    "message_id": 1,

                    "from": {
                        "id": 999,
                        "is_bot": True,
                        "first_name": "MedMind",
                    },

                    "chat": {
                        "id": 501,
                        "type": "private",
                    },

                    "text": "selection",
                },

                "data": data,
            },
        }

    try:
        with TestClient(app) as client:
            start_response = client.post(
                "/api/v1/telegram/webhook",
                headers=headers,
                json={
                    "update_id": 2001,

                    "message": {
                        "message_id": 1,

                        "from": {
                            "id": 501,
                            "is_bot": False,
                            "first_name": "Aya",
                        },

                        "chat": {
                            "id": 501,
                            "type": "private",
                        },

                        "text": "/start",
                    },
                },
            )

            org_response = client.post(
                "/api/v1/telegram/webhook",
                headers=headers,
                json=callback_payload(
                    update_id=2002,
                    callback_id="callback-1",
                    data="org:clinic",
                ),
            )

            provider_response = client.post(
                "/api/v1/telegram/webhook",
                headers=headers,
                json=callback_payload(
                    update_id=2003,
                    callback_id="callback-2",
                    data=(
                        f"provider:{provider_id}"
                    ),
                ),
            )

            branch_response = client.post(
                "/api/v1/telegram/webhook",
                headers=headers,
                json=callback_payload(
                    update_id=2004,
                    callback_id="callback-3",
                    data=(
                        f"branch:{branch_id}"
                    ),
                ),
            )

            booking_response = client.post(
                "/api/v1/telegram/webhook",
                headers=headers,
                json={
                    "update_id": 2005,

                    "message": {
                        "message_id": 2,

                        "from": {
                            "id": 501,
                            "is_bot": False,
                            "first_name": "Aya",
                        },

                        "chat": {
                            "id": 501,
                            "type": "private",
                        },

                        "text":
                            "عايزة أحجز جلدية",
                    },
                },
            )

        assert start_response.status_code == 200
        assert org_response.status_code == 200
        assert provider_response.status_code == 200
        assert branch_response.status_code == 200
        assert booking_response.status_code == 200

        assert len(
            fake_telegram.callbacks
        ) == 3

        assert len(
            booking_graph.calls
        ) == 1

        call = booking_graph.calls[0]

        assert call["values"][
            "tenant_id"
        ] == "clinic-001"

        assert call["values"][
            "provider_id"
        ] == str(provider_id)

        assert call["values"][
            "branch_id"
        ] == str(branch_id)

        assert call["values"][
            "branch_code"
        ] == "DOK"

        assert call["values"][
            "branch_name"
        ] == "الدقي"

        assert call["values"][
            "user_message"
        ] == "عايزة أحجز جلدية"

        assert call["config"][
            "configurable"
        ]["thread_id"] == (
            "clinic-001:"
            "telegram:501:501"
        )

        assert fake_telegram.messages[
            -1
        ]["text"] == (
            "ممكن تقولي التخصص المطلوب؟"
        )

    finally:
        app.dependency_overrides.clear()

        app.router.lifespan_context = (
            original_lifespan
        )


def test_completed_booking_sends_confirmation_then_fresh_buttons(
    monkeypatch,
):
    fake_telegram.messages.clear()
    fake_telegram.callbacks.clear()

    provider_id = uuid4()
    branch_id = uuid4()
    provider = FakeProvider(
        provider_id=provider_id,
        tenant_key="clinic-001",
    )
    branch = FakeBranch(
        branch_id=branch_id,
        provider_id=provider_id,
    )
    public_graph = StatefulFakePublicGraph(
        provider=provider,
        branch=branch,
    )
    public_graph.state = {
        "stage": "ready_for_booking",
        "onboarding_completed": True,
        "tenant_key": "clinic-001",
        "provider_id": str(provider_id),
        "branch_id": str(branch_id),
        "branch_code": "DOK",
        "branch_name": "الدقي",
    }

    @asynccontextmanager
    async def completed_lifespan(application):
        application.state.public_onboarding_graph = public_graph
        application.state.booking_graph = CompletedBookingGraph()
        yield
        application.state.public_onboarding_graph = None
        application.state.booking_graph = None

    monkeypatch.setattr(
        telegram,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_webhook_secret="test-webhook-secret"
        ),
    )

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = completed_lifespan
    app.dependency_overrides[
        get_catalog_service
    ] = fake_catalog_service
    app.dependency_overrides[
        get_telegram_client
    ] = fake_telegram_client

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/telegram/webhook",
                headers={
                    "X-Telegram-Bot-Api-Secret-Token":
                        "test-webhook-secret",
                },
                json={
                    "update_id": 3001,
                    "message": {
                        "message_id": 20,
                        "from": {
                            "id": 501,
                            "is_bot": False,
                            "first_name": "Aya",
                        },
                        "chat": {
                            "id": 501,
                            "type": "private",
                        },
                        "text": "أيوه أكد الحجز",
                    },
                },
            )

        assert response.status_code == 200
        assert len(fake_telegram.messages) == 2
        assert "APT-TEST-001" in fake_telegram.messages[0]["text"]
        assert "عيادة ولا مستشفى" in fake_telegram.messages[1]["text"]
        keyboard = fake_telegram.messages[1]["reply_markup"]
        assert keyboard["inline_keyboard"][0][0]["callback_data"] == (
            "org:clinic"
        )
        assert public_graph.state["onboarding_completed"] is False

    finally:
        app.dependency_overrides.clear()
        app.router.lifespan_context = original_lifespan

def test_telegram_update_idempotency():

    update_id = 987654321

    # Ensure this synthetic update ID is clean
    # before the test starts.
    telegram_module._processed_update_ids.discard(
        update_id
    )

    try:

        first = (
            telegram_module
            ._claim_telegram_update(
                update_id
            )
        )

        second = (
            telegram_module
            ._claim_telegram_update(
                update_id
            )
        )

        assert first is True
        assert second is False

    finally:

        telegram_module._processed_update_ids.discard(
            update_id
        )

        try:
            telegram_module._processed_update_order.remove(
                update_id
            )
        except ValueError:
            pass