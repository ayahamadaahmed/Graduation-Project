from types import SimpleNamespace

import pytest

import agent.medmind.understanding.fallback_tool_planner as fallback_module

from agent.medmind.understanding.fallback_tool_planner import (
    FallbackToolPlanner,
)

from agent.medmind.understanding.tool_planner import (
    ToolPlan,
)

import pytest

from agent.medmind.understanding.fallback_tool_planner import (
    FallbackToolPlanner,
)

from agent.medmind.understanding.tool_planner import (
    ToolPlan,
)

class TimeoutGPT:

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

        raise TimeoutError(
            "Fake GPT timeout."
        )

class WrongSemanticQwen:

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

        # Technically valid ToolPlan,
        # but semantically wrong for the current context.
        return ToolPlan(
            status="selected",
            capability="appointment.cancel",
            arguments={},
            confirmation="unknown",
            ambiguity_kind=None,
            correction_target=None,
            reason="",
        )


class CorrectGPT:

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


class InvalidGPT:

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

        # Still conflicts with the active workflow.
        return ToolPlan(
            status="selected",
            capability="appointment.cancel",
            arguments={},
            confirmation="unknown",
            ambiguity_kind=None,
            correction_target=None,
            reason="",
        )

@pytest.mark.asyncio
async def test_semantic_rejection_uses_gpt_without_opening_circuit(
    monkeypatch,
):

    # Force this request through the Qwen fast path.
    monkeypatch.setattr(
        fallback_module,
        "choose_planner_provider",
        lambda **kwargs: SimpleNamespace(
            provider="qwen",
            reason="test_fast_path",
            complexity_score=-3,
            complexity_level="simple",
            semantic_margin=None,
            signals=("short_contextual_turn",),
        ),
    )

    qwen = WrongSemanticQwen()
    gpt = CorrectGPT()

    planner = FallbackToolPlanner(
        primary=qwen,
        fallback=gpt,
        circuit_failure_threshold=2,
        circuit_cooldown_seconds=60.0,
    )

    result = await planner.plan(
        message="جلدية",
        candidates=[],
        context={
            "active_capability": "appointment.create",
            "stage": "awaiting_specialty",
        },
    )

    # Qwen was tried once.
    assert qwen.calls == 1

    # Validator rejected Qwen,
    # so GPT was called.
    assert gpt.calls == 1

    # Final result must come from GPT.
    assert result.capability == "appointment.create"

    assert result.arguments == {
        "specialty_name": "جلدية",
    }

    # CRITICAL:
    # semantic mistake is NOT a provider failure.
    assert planner._primary_failure_count == 0

    # Circuit must remain healthy.
    assert not planner._is_primary_circuit_open()


@pytest.mark.asyncio
async def test_semantic_rejection_invalid_gpt_fails_closed(
    monkeypatch,
):

    monkeypatch.setattr(
        fallback_module,
        "choose_planner_provider",
        lambda **kwargs: SimpleNamespace(
            provider="qwen",
            reason="test_fast_path",
            complexity_score=-3,
            complexity_level="simple",
            semantic_margin=None,
            signals=("short_contextual_turn",),
        ),
    )

    qwen = WrongSemanticQwen()
    gpt = InvalidGPT()

    planner = FallbackToolPlanner(
        primary=qwen,
        fallback=gpt,
        circuit_failure_threshold=2,
        circuit_cooldown_seconds=60.0,
    )

    result = await planner.plan(
        message="السبت",
        candidates=[],
        context={
            "active_capability":
                "appointment.create",
            "stage":
                "awaiting_date",
        },
    )

    # Qwen was tried once.
    assert qwen.calls == 1

    # Qwen failed semantic validation,
    # so GPT was tried exactly once.
    assert gpt.calls == 1

    # GPT also failed validation.
    # Final result must fail closed.
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

    # Semantic rejection is NOT a provider failure.
    assert planner._primary_failure_count == 0

    assert not planner._is_primary_circuit_open()

class NormalizablePrimaryPlanner:

    async def plan(
        self,
        *,
        message,
        candidates,
        context=None,
    ):

        return ToolPlan(
            status="selected",
            capability="appointment.create",
            arguments={
                "patient_name": "آية محمد",
            },
            confirmation="unknown",
            ambiguity_kind=None,
            correction_target="patient_name",
            reason="",
        )


class MustNotBeCalledFallback:

    async def plan(
        self,
        *,
        message,
        candidates,
        context=None,
    ):

        raise AssertionError(
            "GPT fallback must not be called "
            "for a safely normalizable result"
        )


@pytest.mark.asyncio
async def test_normalized_primary_result_skips_fallback():

    planner = FallbackToolPlanner(
        primary=NormalizablePrimaryPlanner(),
        fallback=MustNotBeCalledFallback(),
    )

    result = await planner.plan(
        message="لا الاسم الصح آية محمد",
        candidates=[],
        context={
            "active_capability":
                "appointment.create",

            "stage":
                "awaiting_confirmation",

            "pending_confirmation":
                True,

            "collected_arguments": {
                "patient_name":
                    "آية أحمد",
            },
        },
    )

    assert (
        result.capability
        == "appointment.create"
    )

    assert result.arguments == {
        "patient_name": "آية محمد",
    }

    assert result.confirmation == "unknown"

    assert result.correction_target is None    

@pytest.mark.asyncio
async def test_semantic_fallback_gpt_timeout_is_not_retried(
    monkeypatch,
):

    monkeypatch.setattr(
        fallback_module,
        "choose_planner_provider",
        lambda **kwargs: SimpleNamespace(
            provider="qwen",
            reason="test_fast_path",
            complexity_score=-3,
            complexity_level="simple",
            semantic_margin=None,
            signals=("short_contextual_turn",),
        ),
    )

    qwen = WrongSemanticQwen()
    gpt = TimeoutGPT()

    planner = FallbackToolPlanner(
        primary=qwen,
        fallback=gpt,
        circuit_failure_threshold=2,
        circuit_cooldown_seconds=60.0,
    )

    with pytest.raises(TimeoutError):
        await planner.plan(
            message="السبت",
            candidates=[],
            context={
                "active_capability":
                    "appointment.create",
                "stage":
                    "awaiting_date",
            },
        )

    assert qwen.calls == 1

    # Critical production requirement:
    # GPT failure must NOT trigger another GPT call.
    assert gpt.calls == 1

    # Qwen produced a response successfully.
    # Semantic rejection is not a provider outage.
    assert planner._primary_failure_count == 0    