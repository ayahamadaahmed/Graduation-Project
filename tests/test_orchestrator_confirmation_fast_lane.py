import pytest

from agent.medmind.understanding.orchestrator import (
    UnderstandingOrchestrator,
)
from agent.medmind.understanding.tool_planner import (
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
            "for confirmation fast lane."
        )


class PlannerMustNotBeCalled:

    async def plan(
        self,
        *args,
        **kwargs,
    ):
        raise AssertionError(
            "Planner must not be called "
            "for confirmation fast lane."
        )


@pytest.mark.asyncio
async def test_clear_yes_bypasses_router_and_planner():

    orchestrator = UnderstandingOrchestrator(
        router=RouterMustNotBeCalled(),
        planner=PlannerMustNotBeCalled(),
        top_k=8,
    )

    result = await orchestrator.understand(
        message="أيوه",
        context={
            "stage": "awaiting_confirmation",
            "active_capability": "appointment.create",
        },
    )

    assert result.status == "selected"
    assert result.capability == "appointment.create"
    assert result.confirmation == "yes"

    # Fast lane means no planner attempt.
    assert result.attempts == 0
    assert result.used_broad_candidates is False


@pytest.mark.asyncio
async def test_clear_no_bypasses_router_and_planner():

    orchestrator = UnderstandingOrchestrator(
        router=RouterMustNotBeCalled(),
        planner=PlannerMustNotBeCalled(),
        top_k=8,
    )

    result = await orchestrator.understand(
        message="لأ",
        context={
            "stage": "awaiting_confirmation",
            "active_capability": "appointment.cancel",
        },
    )

    assert result.status == "selected"
    assert result.capability == "appointment.cancel"
    assert result.confirmation == "no"

    assert result.attempts == 0
    assert result.used_broad_candidates is False


class TrackingRouter:

    def __init__(self) -> None:
        self.calls = 0

    def route(
        self,
        *args,
        **kwargs,
    ):
        self.calls += 1
        return []


class CorrectionPlanner:

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
            arguments={},
            confirmation="unknown",
            ambiguity_kind=None,
            correction_target="patient_name",
            reason="",
        )


@pytest.mark.asyncio
async def test_complex_confirmation_does_not_use_fast_lane():

    router = TrackingRouter()
    planner = CorrectionPlanner()

    orchestrator = UnderstandingOrchestrator(
        router=router,
        planner=planner,
        top_k=8,
    )

    result = await orchestrator.understand(
        message="لا الاسم غلط",
        context={
            "stage": "awaiting_confirmation",
            "active_capability": "appointment.create",
        },
    )

    # Must continue through normal understanding.
    assert router.calls == 1
    assert planner.calls == 1

    assert result.status == "selected"
    assert result.capability == "appointment.create"

    # This is a correction, not a simple "no".
    assert result.confirmation == "unknown"
    assert result.correction_target == "patient_name"

    # Planner was actually used.
    assert result.attempts == 1


@pytest.mark.asyncio
async def test_phone_confirmation_yes_bypasses_router_and_planner():

    orchestrator = UnderstandingOrchestrator(
        router=RouterMustNotBeCalled(),
        planner=PlannerMustNotBeCalled(),
        top_k=8,
    )

    result = await orchestrator.understand(
        message="أيوه",
        context={
            "stage": "awaiting_phone_confirmation",
            "active_capability": "appointment.create",
        },
    )

    assert result.status == "selected"
    assert result.capability == "appointment.create"
    assert result.confirmation == "yes"

    assert result.attempts == 0
    assert result.used_broad_candidates is False

@pytest.mark.asyncio
async def test_phone_confirmation_complex_message_does_not_use_fast_lane():

    router = TrackingRouter()
    planner = CorrectionPlanner()

    orchestrator = UnderstandingOrchestrator(
        router=router,
        planner=planner,
        top_k=8,
    )

    result = await orchestrator.understand(
        message="لا الرقم غلط",
        context={
            "stage": "awaiting_phone_confirmation",
            "active_capability": "appointment.create",
        },
    )

    assert router.calls == 1
    assert planner.calls == 1

    assert result.status == "selected"
    assert result.capability == "appointment.create"        

@pytest.mark.asyncio
async def test_phone_confirmation_no_bypasses_router_and_planner():

    orchestrator = UnderstandingOrchestrator(
        router=RouterMustNotBeCalled(),
        planner=PlannerMustNotBeCalled(),
        top_k=8,
    )

    result = await orchestrator.understand(
        message="لأ",
        context={
            "stage": "awaiting_phone_confirmation",
            "active_capability": "appointment.create",
        },
    )

    assert result.status == "selected"
    assert result.capability == "appointment.create"
    assert result.confirmation == "no"

    assert result.attempts == 0
    assert result.used_broad_candidates is False    