import asyncio
import time

import pytest

import agent.medmind.understanding.fallback_tool_planner as fallback_module

from agent.medmind.understanding.fallback_tool_planner import (
    FallbackToolPlanner,
)

from agent.medmind.understanding.tool_planner import (
    ToolPlan,
)


class SlowPrimary:

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

        await asyncio.sleep(
            0.20
        )

        return ToolPlan(
            status="selected",
            capability="appointment.create",
            arguments={},
            confirmation="unknown",
            ambiguity_kind=None,
            correction_target=None,
            reason="late_primary",
        )


class FastFallback:

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
            capability="appointment.create",
            arguments={},
            confirmation="unknown",
            ambiguity_kind=None,
            correction_target=None,
            reason="fallback",
        )


@pytest.mark.asyncio
async def test_primary_budget_timeout_uses_fallback(
    monkeypatch,
):

    monkeypatch.setattr(
        fallback_module,
        "choose_planner_provider",
        lambda **kwargs:
            type(
                "Decision",
                (),
                {
                    "provider": "qwen",
                    "reason": "test",
                    "complexity_score": 0,
                    "complexity_level": "simple",
                    "semantic_margin": None,
                    "signals": (),
                },
            )(),
    )

    primary = SlowPrimary()
    fallback = FastFallback()

    planner = FallbackToolPlanner(
        primary=primary,
        fallback=fallback,
        primary_timeout_seconds=0.03,
    )

    started = time.perf_counter()

    result = await planner.plan(
        message="عايزة احجز",
        candidates=[],
        context={},
    )

    elapsed = (
        time.perf_counter()
        - started
    )

    assert primary.calls == 1
    assert fallback.calls == 1

    assert (
        result.capability
        == "appointment.create"
    )

    assert (
        planner._primary_failure_count
        == 1
    )

    assert elapsed < 0.15


class FastPrimary:

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

        await asyncio.sleep(
            0.01
        )

        return ToolPlan(
            status="selected",
            capability="appointment.create",
            arguments={},
            confirmation="unknown",
            ambiguity_kind=None,
            correction_target=None,
            reason="primary",
        )


class MustNotRunFallback:

    async def plan(
        self,
        *,
        message,
        candidates,
        context=None,
    ):

        raise AssertionError(
            "Fallback must not run when "
            "primary finishes inside budget."
        )


@pytest.mark.asyncio
async def test_primary_inside_budget_is_preserved(
    monkeypatch,
):

    monkeypatch.setattr(
        fallback_module,
        "choose_planner_provider",
        lambda **kwargs:
            type(
                "Decision",
                (),
                {
                    "provider": "qwen",
                    "reason": "test",
                    "complexity_score": 0,
                    "complexity_level": "simple",
                    "semantic_margin": None,
                    "signals": (),
                },
            )(),
    )

    primary = FastPrimary()

    planner = FallbackToolPlanner(
        primary=primary,
        fallback=MustNotRunFallback(),
        primary_timeout_seconds=0.10,
    )

    result = await planner.plan(
        message="عايزة احجز",
        candidates=[],
        context={},
    )

    assert primary.calls == 1

    assert (
        result.capability
        == "appointment.create"
    )

    assert (
        planner._primary_failure_count
        == 0
    )