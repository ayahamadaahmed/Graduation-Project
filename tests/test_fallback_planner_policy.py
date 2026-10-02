from __future__ import annotations

import pytest

from agent.medmind.understanding.capability_router import (
    CapabilityMatch,
)

from agent.medmind.understanding.fallback_tool_planner import (
    FallbackToolPlanner,
)

from agent.medmind.understanding.tool_planner import (
    ToolPlan,
)


# ============================================================
# FAKE QWEN
#
# لو اتنادى في complex request، التست يفشل.
# ============================================================

class QwenMustNotBeCalled:

    async def plan(
        self,
        *,
        message,
        candidates,
        context=None,
    ):
        raise AssertionError(
            "Qwen was called for a complex request."
        )


# ============================================================
# FAKE GPT
# ============================================================

class FakeGPTPlanner:

    def __init__(self) -> None:
        self.calls = 0

    async def plan(
        self,
        *,
        message,
        candidates,
        context=None,
    ) -> ToolPlan:

        self.calls += 1

        return ToolPlan(
            status="selected",
            capability="appointment.reschedule",
            arguments={
                "date_text": "السبت",
            },
            confirmation="unknown",
            ambiguity_kind=None,
            correction_target=None,
            reason="",
        )


# ============================================================
# TEST
# ============================================================

@pytest.mark.asyncio
async def test_complex_operation_switch_skips_qwen():

    gpt = FakeGPTPlanner()

    planner = FallbackToolPlanner(
        primary=QwenMustNotBeCalled(),
        fallback=gpt,
    )

    candidates = [
        CapabilityMatch(
            name="appointment.cancel",
            domain="appointment",
            score=0.90,
            matched_text="test",
        ),

        CapabilityMatch(
            name="appointment.reschedule",
            domain="appointment",
            score=0.85,
            matched_text="test",
        ),

        CapabilityMatch(
            name="appointment.create",
            domain="appointment",
            score=0.60,
            matched_text="test",
        ),
    ]

    result = await planner.plan(
        message="لا متلغهوش، غيره للسبت",
        candidates=candidates,
        context={
            "active_capability":
                "appointment.cancel",

            "stage":
                "awaiting_confirmation",
        },
    )

    assert gpt.calls == 1

    assert (
        result.status
        == "selected"
    )

    assert (
        result.capability
        == "appointment.reschedule"
    )

    assert (
        result.arguments["date_text"]
        == "السبت"
    )


# ============================================================
# FAKE QWEN FOR FAST PATH
# ============================================================

class FakeQwenPlanner:

    def __init__(self) -> None:
        self.calls = 0

    async def plan(
        self,
        *,
        message,
        candidates,
        context=None,
    ) -> ToolPlan:

        self.calls += 1

        return ToolPlan(
            status="selected",
            capability="appointment.create",
            arguments={
                "specialty_name": "جلدية",
            },
            confirmation="unknown",
            ambiguity_kind=None,
            correction_target=None,
            reason="",
        )


# ============================================================
# GPT MUST NOT RUN
# ============================================================

class GPTMustNotBeCalled:

    async def plan(
        self,
        *,
        message,
        candidates,
        context=None,
    ):
        raise AssertionError(
            "GPT was called for a simple Qwen fast-path request."
        )


# ============================================================
# SIMPLE FAST-PATH TEST
# ============================================================

@pytest.mark.asyncio
async def test_simple_contextual_request_uses_qwen_only():

    qwen = FakeQwenPlanner()

    planner = FallbackToolPlanner(
        primary=qwen,
        fallback=GPTMustNotBeCalled(),
    )

    candidates = [
        CapabilityMatch(
            name="appointment.create",
            domain="appointment",
            score=0.92,
            matched_text="test",
        ),

        CapabilityMatch(
            name="provider.search_doctors",
            domain="provider",
            score=0.70,
            matched_text="test",
        ),
    ]

    result = await planner.plan(
        message="جلدية",
        candidates=candidates,
        context={
            "active_capability":
                "appointment.create",

            "stage":
                "awaiting_specialty",
        },
    )

    # Qwen must run exactly once.
    assert qwen.calls == 1

    # GPTMustNotBeCalled would fail the test
    # automatically if fallback happened.

    assert (
        result.status
        == "selected"
    )

    assert (
        result.capability
        == "appointment.create"
    )

    assert (
        result.arguments[
            "specialty_name"
        ]
        == "جلدية"
    )    