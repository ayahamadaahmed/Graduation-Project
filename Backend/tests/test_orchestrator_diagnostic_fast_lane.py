import pytest

from medmind.understanding.orchestrator import (
    UnderstandingOrchestrator,
)

from medmind.understanding.tool_planner import (
    ToolPlan,
)


class RouterMustNotBeCalled:

    def route(
        self,
        *args,
        **kwargs,
    ):
        raise AssertionError(
            "Semantic router must not be called "
            "for explicit diagnostic fast lane."
        )


class PlannerMustNotBeCalled:

    async def plan(
        self,
        *,
        message,
        candidates,
        context=None,
    ):
        raise AssertionError(
            "Planner must not be called "
            "for explicit diagnostic fast lane."
        )


class EmptyRouter:

    def route(
        self,
        *args,
        **kwargs,
    ):
        return []


class ClarifyingPlanner:

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
            status="ambiguous",
            capability=None,
            arguments={},
            confirmation="unknown",
            ambiguity_kind="needs_clarification",
            correction_target=None,
            reason="normal_understanding_path",
        )


@pytest.mark.asyncio
async def test_explicit_brain_mri_bypasses_router_and_planner():

    orchestrator = UnderstandingOrchestrator(
        router=RouterMustNotBeCalled(),
        planner=PlannerMustNotBeCalled(),
        top_k=8,
    )

    result = await orchestrator.understand(
        message="Analyze this brain MRI",
        context={},
    )

    assert result.status == "selected"

    assert (
        result.capability
        == "diagnostics.radiology.analyze"
    )

    assert result.arguments == {
        "modality": "brain_mri",
    }

    assert result.attempts == 0
    assert result.used_broad_candidates is False


@pytest.mark.asyncio
async def test_diagnostic_fast_lane_respects_tenant_policy():

    planner = ClarifyingPlanner()

    orchestrator = UnderstandingOrchestrator(
        router=EmptyRouter(),
        planner=planner,
        top_k=8,
        allowed_capabilities={
            "appointment.create",
        },
    )

    result = await orchestrator.understand(
        message="Analyze this brain MRI",
        context={},
    )

    assert result.status == "ambiguous"

    assert (
        result.capability
        is None
    )

    assert planner.calls == 1