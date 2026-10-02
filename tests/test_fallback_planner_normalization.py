from types import SimpleNamespace

import pytest

import agent.medmind.understanding.fallback_tool_planner as fallback_module

from agent.medmind.understanding.fallback_tool_planner import (
    FallbackToolPlanner,
)
from agent.medmind.understanding.tool_planner import (
    ToolPlan,
)


class InvalidContextSwitchGPT:

    def __init__(self):
        self.calls = 0

    async def plan(
        self,
        *,
        message,
        candidates,
        context=None,
    ):
        self.calls += 1

        return ToolPlan(
            status="selected",
            capability="appointment.cancel",
            arguments={},
            confirmation="unknown",
        )

class CopiedContextGPT:

    def __init__(self):
        self.calls = 0

    async def plan(
        self,
        *,
        message,
        candidates,
        context=None,
    ):
        self.calls += 1

        return ToolPlan(
            status="selected",
            capability="provider.get_services",
            arguments={
                "doctor_name": "دكتور ماهر",
                "specialty_name": "جلدية",
            },
            confirmation="unknown",
        )


class FailingQwen:

    async def plan(
        self,
        *,
        message,
        candidates,
        context=None,
    ):
        raise TimeoutError()


@pytest.mark.asyncio
async def test_gpt_direct_result_is_normalized(
    monkeypatch,
):

    monkeypatch.setattr(
        fallback_module,
        "choose_planner_provider",
        lambda **kwargs: SimpleNamespace(
            provider="gpt",
            reason="test_direct_gpt",
            complexity_score=3,
            complexity_level="complex",
            semantic_margin=None,
            signals=(),
        ),
    )

    gpt = CopiedContextGPT()

    planner = FallbackToolPlanner(
        primary=FailingQwen(),
        fallback=gpt,
    )

    result = await planner.plan(
        message="طب الكشف بكام؟",
        candidates=[],
        context={
            "active_capability":
                "appointment.create",
            "stage":
                "awaiting_date",
            "pending_confirmation":
                False,
            "collected_arguments": {
                "specialty_name":
                    "جلدية",
                "doctor_name":
                    "دكتور ماهر",
            },
        },
    )

    assert gpt.calls == 1
    assert result.capability == (
        "provider.get_services"
    )
    assert result.arguments == {}


@pytest.mark.asyncio
async def test_technical_fallback_result_is_normalized(
    monkeypatch,
):

    monkeypatch.setattr(
        fallback_module,
        "choose_planner_provider",
        lambda **kwargs: SimpleNamespace(
            provider="qwen",
            reason="test_qwen",
            complexity_score=0,
            complexity_level="simple",
            semantic_margin=None,
            signals=(),
        ),
    )

    gpt = CopiedContextGPT()

    planner = FallbackToolPlanner(
        primary=FailingQwen(),
        fallback=gpt,
    )

    result = await planner.plan(
        message="طب الكشف بكام؟",
        candidates=[],
        context={
            "active_capability":
                "appointment.create",
            "stage":
                "awaiting_date",
            "pending_confirmation":
                False,
            "collected_arguments": {
                "specialty_name":
                    "جلدية",
                "doctor_name":
                    "دكتور ماهر",
            },
        },
    )

    assert gpt.calls == 1
    assert result.arguments == {}

@pytest.mark.asyncio
async def test_gpt_direct_invalid_result_fails_closed(
    monkeypatch,
):

    monkeypatch.setattr(
        fallback_module,
        "choose_planner_provider",
        lambda **kwargs: SimpleNamespace(
            provider="gpt",
            reason="test_direct_gpt",
            complexity_score=3,
            complexity_level="complex",
            semantic_margin=None,
            signals=(),
        ),
    )

    gpt = InvalidContextSwitchGPT()

    planner = FallbackToolPlanner(
        primary=FailingQwen(),
        fallback=gpt,
    )

    result = await planner.plan(
        message="السبت",
        candidates=[],
        context={
            "active_capability":
                "appointment.create",
            "stage":
                "awaiting_date",
            "pending_confirmation":
                False,
        },
    )

    assert gpt.calls == 1

    assert result.status == "ambiguous"

    assert result.capability is None

    assert (
        result.ambiguity_kind
        == "needs_clarification"
    )

    assert (
        result.reason
        == "semantic_validation_failed"
    )    

@pytest.mark.asyncio
async def test_technical_fallback_invalid_gpt_fails_closed(
    monkeypatch,
):

    monkeypatch.setattr(
        fallback_module,
        "choose_planner_provider",
        lambda **kwargs: SimpleNamespace(
            provider="qwen",
            reason="test_qwen",
            complexity_score=0,
            complexity_level="simple",
            semantic_margin=None,
            signals=(),
        ),
    )

    gpt = InvalidContextSwitchGPT()

    planner = FallbackToolPlanner(
        primary=FailingQwen(),
        fallback=gpt,
    )

    result = await planner.plan(
        message="السبت",
        candidates=[],
        context={
            "active_capability":
                "appointment.create",
            "stage":
                "awaiting_date",
            "pending_confirmation":
                False,
        },
    )

    assert gpt.calls == 1

    assert result.status == "ambiguous"
    assert result.capability is None

    assert (
        result.ambiguity_kind
        == "needs_clarification"
    )

    assert (
        result.reason
        == "semantic_validation_failed"
    )    