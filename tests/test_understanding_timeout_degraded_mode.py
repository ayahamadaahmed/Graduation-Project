from types import SimpleNamespace

import pytest

from agent.medmind.service import (
    MedMindService,
)

from medmind.understanding.orchestrator import (
    UnderstandingResult,
)


class TimeoutUnderstanding:

    async def understand(
        self,
        *,
        message,
        context,
    ):

        return UnderstandingResult(
            status="fallback_required",
            capability=None,
            arguments={},
            ambiguity_kind=None,
            reason="understanding_timeout",
            attempts=1,
            used_broad_candidates=False,
        )


class ForbiddenLegacyNLU:

    def __init__(self):
        self.calls = 0

    async def understand(
        self,
        **kwargs,
    ):

        self.calls += 1

        raise AssertionError(
            "Legacy NLU must not be called "
            "after understanding_timeout."
        )


class ForbiddenAgent:

    def __init__(self):
        self.calls = 0

    async def run(
        self,
        **kwargs,
    ):

        self.calls += 1

        raise AssertionError(
            "Read agent must not be called "
            "after understanding_timeout."
        )


class FakeMemory:

    def __init__(self):
        self.user_messages = []
        self.assistant_messages = []

    async def get_recent(
        self,
        session_id,
    ):
        return []

    async def add_user_message(
        self,
        *,
        session_id,
        content,
    ):
        self.user_messages.append(
            content
        )

    async def add_assistant_message(
        self,
        *,
        session_id,
        content,
    ):
        self.assistant_messages.append(
            content
        )


class FakeStateStore:

    def __init__(self):
        self.saved = 0

        self.state = SimpleNamespace(
            language="ar",
            stage="new",
            operation_type=None,
        )

        self.state.safe_llm_context = (
            lambda: {}
        )

    async def get_or_create(
        self,
        *,
        session_id,
        tenant_id,
        channel,
    ):
        return self.state

    async def save(
        self,
        state,
    ):
        self.saved += 1


@pytest.mark.asyncio
async def test_understanding_timeout_skips_legacy_llm():

    legacy_nlu = (
        ForbiddenLegacyNLU()
    )

    agent = (
        ForbiddenAgent()
    )

    memory = (
        FakeMemory()
    )

    state_store = (
        FakeStateStore()
    )

    service = MedMindService(
        tenant_id="test-tenant",
        agent=agent,
        nlu=legacy_nlu,
        understanding=TimeoutUnderstanding(),
        booking_workflow=object(),
        cancel_workflow=object(),
        reschedule_workflow=object(),
        state_store=state_store,
        memory=memory,
        tools=object(),
    )

    # Keep this test focused only on timeout behavior.
    service._build_understanding_context = (
        lambda state: {}
    )

    result = await service.chat(
        session_id="timeout-test-001",
        message="عايز احجز",
        channel="web",
    )

    assert legacy_nlu.calls == 0
    assert agent.calls == 0

    assert (
        result["intent"]
        == "unknown"
    )

    assert (
        result["route"]
        == "understanding_clarification"
    )

    assert (
        result["response_type"]
        == "clarification"
    )

    assert result["reply"]

    assert (
        memory.user_messages
        == ["عايز احجز"]
    )

    assert len(
        memory.assistant_messages
    ) == 1

    assert state_store.saved == 1


class FailingUnderstanding:

    async def understand(
        self,
        *,
        message,
        context,
    ):

        raise RuntimeError(
            "simulated planner provider failure"
        )


@pytest.mark.asyncio
async def test_understanding_exception_skips_legacy_llm():

    legacy_nlu = (
        ForbiddenLegacyNLU()
    )

    agent = (
        ForbiddenAgent()
    )

    memory = (
        FakeMemory()
    )

    state_store = (
        FakeStateStore()
    )

    service = MedMindService(
        tenant_id="test-tenant",
        agent=agent,
        nlu=legacy_nlu,
        understanding=FailingUnderstanding(),
        booking_workflow=object(),
        cancel_workflow=object(),
        reschedule_workflow=object(),
        state_store=state_store,
        memory=memory,
        tools=object(),
    )

    service._build_understanding_context = (
        lambda state: {}
    )

    result = await service.chat(
        session_id="failure-test-001",
        message="عايز احجز",
        channel="web",
    )

    assert legacy_nlu.calls == 0
    assert agent.calls == 0

    assert (
        result["intent"]
        == "unknown"
    )

    assert (
        result["route"]
        == "understanding_clarification"
    )

    assert (
        result["response_type"]
        == "clarification"
    )

    assert result["reply"]

    assert state_store.saved == 1  

@pytest.mark.parametrize(
    "message",
    [
        "17:00",
        "\u0627\u0644\u0633\u0627\u0639\u0629 \u062e\u0645\u0633\u0629",
    ],
)      

@pytest.mark.asyncio
async def test_awaiting_time_exact_offered_slot_skips_understanding(
    monkeypatch,
    message,
):

    # ========================================================
    # Understanding must NOT be called for an exact trusted
    # offered slot while the active booking workflow is
    # waiting specifically for time.
    # ========================================================

    class ForbiddenUnderstanding:

        def __init__(self):
            self.calls = 0

        async def understand(
            self,
            *,
            message,
            context,
        ):
            self.calls += 1

            raise AssertionError(
                "Understanding/Qwen must not be called "
                "for an exact offered time."
            )

    class FakeBookingWorkflow:

        def __init__(self):
            self.calls = []

        async def handle(
            self,
            *,
            state,
            nlu,
            user_message,
        ):
            self.calls.append(
                {
                    "intent": nlu.intent,
                    "user_message": user_message,
                }
            )

            return SimpleNamespace(
                handled=True,
                reply="time accepted",
                response_type="booking_confirmation",
            )

    understanding = (
        ForbiddenUnderstanding()
    )

    booking_workflow = (
        FakeBookingWorkflow()
    )

    memory = (
        FakeMemory()
    )

    state_store = (
        FakeStateStore()
    )

    # Active deterministic booking state.
    state_store.state.stage = (
        "awaiting_time"
    )

    state_store.state.operation_type = (
        "book_appointment"
    )

    state_store.state.awaiting_confirmation = (
        False
    )

    # Trusted slots that were already returned by backend.
    state_store.state.recent_slots = [
        SimpleNamespace(
            start_time="17:00:00",
        )
    ]

    service = MedMindService(
        tenant_id="test-tenant",
        agent=ForbiddenAgent(),
        nlu=ForbiddenLegacyNLU(),
        understanding=understanding,
        booking_workflow=booking_workflow,
        cancel_workflow=object(),
        reschedule_workflow=object(),
        state_store=state_store,
        memory=memory,
        tools=object(),
    )

    service._build_understanding_context = (
        lambda state: {}
    )

    service._is_side_question = (
        lambda **kwargs: False
    )

    # Keep this test focused on routing/latency behavior.
    monkeypatch.setattr(
        "agent.medmind.service.remember_conversation_focus",
        lambda **kwargs: None,
    )

    result = await service.chat(
        session_id="fast-time-test-001",
        message=message,
        channel="web",
    )

    assert (
        understanding.calls
        == 0
    )

    assert (
        len(booking_workflow.calls)
        == 1
    )

    assert (
        booking_workflow.calls[0]["intent"]
        == "provide_time"
    )

    assert (
        result["route"]
        == "book_appointment"
    ) 

@pytest.mark.asyncio
async def test_awaiting_time_side_question_does_not_use_time_fast_path(
    monkeypatch,
):

    class TrackingUnderstanding:

        def __init__(self):
            self.calls = 0

        async def understand(
            self,
            *,
            message,
            context,
        ):
            self.calls += 1

            return UnderstandingResult(
                status="fallback_required",
                capability=None,
                arguments={},
                ambiguity_kind=None,
                reason="understanding_timeout",
                attempts=1,
                used_broad_candidates=False,
            )

    class ForbiddenBookingWorkflow:

        def __init__(self):
            self.calls = 0

        async def handle(
            self,
            **kwargs,
        ):
            self.calls += 1

            raise AssertionError(
                "A side question containing a time "
                "must not be treated as time selection."
            )

    understanding = TrackingUnderstanding()
    booking_workflow = ForbiddenBookingWorkflow()

    memory = FakeMemory()
    state_store = FakeStateStore()

    state_store.state.stage = (
        "awaiting_time"
    )

    state_store.state.operation_type = (
        "book_appointment"
    )

    state_store.state.awaiting_confirmation = (
        False
    )

    state_store.state.recent_slots = [
        SimpleNamespace(
            start_time="17:00:00",
        )
    ]

    service = MedMindService(
        tenant_id="test-tenant",
        agent=ForbiddenAgent(),
        nlu=ForbiddenLegacyNLU(),
        understanding=understanding,
        booking_workflow=booking_workflow,
        cancel_workflow=object(),
        reschedule_workflow=object(),
        state_store=state_store,
        memory=memory,
        tools=object(),
    )

    service._build_understanding_context = (
        lambda state: {}
    )

    monkeypatch.setattr(
        "agent.medmind.service.remember_conversation_focus",
        lambda **kwargs: None,
    )

    result = await service.chat(
        session_id="fast-time-side-question-001",
        message=(
            "\u0647\u0644 \u0627\u0644\u062f\u0643\u062a\u0648\u0631 "
            "\u0645\u0648\u062c\u0648\u062f "
            "\u0627\u0644\u0633\u0627\u0639\u0629 "
            "\u062e\u0645\u0633\u0629\u061f"
        ),
        channel="web",
    )

    assert understanding.calls == 1
    assert booking_workflow.calls == 0

    assert (
        result["route"]
        == "understanding_clarification"
    )       