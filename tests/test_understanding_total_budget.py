import asyncio
import time

import pytest

import medmind.understanding.orchestrator as orchestrator_module

from medmind.understanding.orchestrator import (
    UnderstandingOrchestrator,
)


class SlowPlanner:

    async def plan(
        self,
        *,
        message,
        candidates,
        context=None,
    ):

        await asyncio.sleep(
            1.0
        )

        raise AssertionError(
            "Planner should have been cancelled "
            "by the total understanding budget."
        )


@pytest.mark.asyncio
async def test_understanding_total_budget_stops_slow_planner(
    monkeypatch,
):

    monkeypatch.setattr(
        orchestrator_module,
        "select_capability_candidates",
        lambda **kwargs: [],
    )

    orchestrator = (
        UnderstandingOrchestrator(
            router=object(),
            planner=SlowPlanner(),
            top_k=8,
            total_timeout_seconds=0.05,
        )
    )

    started = time.perf_counter()

    result = await orchestrator.understand(
        message="عايز احجز",
        context={},
    )

    elapsed = (
        time.perf_counter()
        - started
    )

    assert (
        result.status
        == "fallback_required"
    )

    assert (
        result.reason
        == "understanding_timeout"
    )

    assert elapsed < 0.25

class CandidateMissThenSlowPlanner:

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

        # First attempt consumes most of the total budget,
        # then asks the orchestrator to broaden candidates.
        if self.calls == 1:

            await asyncio.sleep(
                0.14
            )

            from medmind.understanding.tool_planner import (
                ToolPlan,
            )

            return ToolPlan(
                status="ambiguous",
                capability=None,
                arguments={},
                ambiguity_kind="candidate_miss",
                reason="candidate_miss",
            )

        # If attempt 2 incorrectly receives a NEW 0.20s
        # timeout, this would finish successfully.
        #
        # With the shared deadline, only about 0.06s
        # should remain, so this attempt must be cancelled.
        await asyncio.sleep(
            0.10
        )

        from medmind.understanding.tool_planner import (
            ToolPlan,
        )

        return ToolPlan(
            status="selected",
            capability="appointment.create",
            arguments={},
            reason="should_not_complete",
        )


@pytest.mark.asyncio
async def test_broad_retry_uses_remaining_budget_not_new_budget(
    monkeypatch,
):

    monkeypatch.setattr(
        orchestrator_module,
        "select_capability_candidates",
        lambda **kwargs: [],
    )

    planner = (
        CandidateMissThenSlowPlanner()
    )

    orchestrator = (
        UnderstandingOrchestrator(
            router=object(),
            planner=planner,
            top_k=8,
            total_timeout_seconds=0.20,
        )
    )

    started = time.perf_counter()

    result = await orchestrator.understand(
        message="عايز احجز",
        context={},
    )

    elapsed = (
        time.perf_counter()
        - started
    )

    assert planner.calls == 2

    assert (
        result.status
        == "fallback_required"
    )

    assert (
        result.reason
        == "understanding_timeout"
    )

    assert result.attempts == 2

    assert (
        result.used_broad_candidates
        is True
    )

    # Shared deadline should stop the whole turn
    # near 0.20s, not 0.14 + another 0.20s.
    assert elapsed < 0.30    