from __future__ import annotations

import asyncio
from types import SimpleNamespace

import medmind.service as service_module

from medmind.service import (
    MedMindService,
)

from medmind.state.store import (
    InMemoryStateStore,
)

from medmind.understanding.types import (
    NLUResult,
)


class FakeNLU:

    async def understand(
        self,
        **kwargs,
    ) -> NLUResult:

        return NLUResult(
            intent="ask_provider",
            operation_type=None,
            confidence=1.0,
        )


class FailIfCalledAgent:

    async def run(
        self,
        **kwargs,
    ):

        raise AssertionError(
            "Read Agent must not run "
            "for ask_provider RAG requests."
        )


class FakeMemory:

    def __init__(
        self,
    ) -> None:

        self.messages = []

    async def get_recent(
        self,
        session_id: str,
    ):

        return []

    async def add_user_message(
        self,
        *,
        session_id: str,
        content: str,
    ) -> None:

        self.messages.append(
            (
                "user",
                content,
            )
        )

    async def add_assistant_message(
        self,
        *,
        session_id: str,
        content: str,
    ) -> None:

        self.messages.append(
            (
                "assistant",
                content,
            )
        )


def test_ask_provider_routes_to_rag(
    monkeypatch,
) -> None:

    calls = {}

    async def fake_rag_answer(
        *,
        tenant_id: str,
        query: str,
        language: str,
    ):

        calls["tenant_id"] = (
            tenant_id
        )

        calls["query"] = (
            query
        )

        calls["language"] = (
            language
        )

        return SimpleNamespace(
            answer=(
                "Dr. Maher treats acne."
            ),
            supported=True,
        )

    monkeypatch.setattr(
        service_module,
        "answer_provider_knowledge",
        fake_rag_answer,
    )

    service = MedMindService(
        tenant_id="clinic-001",

        agent=FailIfCalledAgent(),

        nlu=FakeNLU(),

        booking_workflow=object(),

        cancel_workflow=object(),

        reschedule_workflow=object(),

        state_store=InMemoryStateStore(),

        memory=FakeMemory(),
    )

    result = asyncio.run(
        service.chat(
            session_id=
                "rag-routing-test-001",

            message=
                "Does Dr. Maher treat acne?",
        )
    )

    assert (
        result["intent"]
        == "ask_provider"
    )

    assert (
        result["route"]
        == "provider_rag"
    )

    assert (
        result["response_type"]
        == "rag_answer"
    )

    assert (
        result["reply"]
        == "Dr. Maher treats acne."
    )

    assert (
        result["tool_calls"]
        == []
    )

    assert (
        result["state"]["stage"]
        == "new"
    )

    assert (
        calls["tenant_id"]
        == "clinic-001"
    )

    assert (
        calls["query"]
        == "Does Dr. Maher treat acne?"
    )

    assert (
        calls["language"]
        == "en"
    )


def test_unsupported_provider_knowledge_is_marked_unsupported(
    monkeypatch,
) -> None:

    async def fake_rag_answer(
        *,
        tenant_id: str,
        query: str,
        language: str,
    ):

        return SimpleNamespace(
            answer=(
                "I don't have enough verified "
                "information to answer that."
            ),
            supported=False,
        )

    monkeypatch.setattr(
        service_module,
        "answer_provider_knowledge",
        fake_rag_answer,
    )

    service = MedMindService(
        tenant_id="clinic-001",

        agent=FailIfCalledAgent(),

        nlu=FakeNLU(),

        booking_workflow=object(),

        cancel_workflow=object(),

        reschedule_workflow=object(),

        state_store=InMemoryStateStore(),

        memory=FakeMemory(),
    )

    result = asyncio.run(
        service.chat(
            session_id=
                "rag-unsupported-test-001",

            message=
                "Does the clinic offer a service "
                "that is not in the knowledge base?",
        )
    )

    assert (
        result["intent"]
        == "ask_provider"
    )

    assert (
        result["route"]
        == "provider_rag"
    )

    assert (
        result["response_type"]
        == "rag_unsupported"
    )

    assert (
        result["tool_calls"]
        == []
    )
