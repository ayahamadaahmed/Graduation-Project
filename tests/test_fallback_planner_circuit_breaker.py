from types import SimpleNamespace
import httpx

from groq import RateLimitError
import pytest

import agent.medmind.understanding.fallback_tool_planner as fallback_module

from agent.medmind.understanding.fallback_tool_planner import (
    FallbackToolPlanner,
)
from openai import RateLimitError as OpenAIRateLimitError
from agent.medmind.understanding.tool_planner import (
    ToolPlan,
)

class RateLimitedGPT:

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

        request = httpx.Request(
            "POST",
            "https://api.openai.com/v1/chat/completions",
        )

        response = httpx.Response(
            status_code=429,
            request=request,
        )

        raise OpenAIRateLimitError(
            "GPT rate limit reached.",
            response=response,
            body={
                "error": {
                    "type": "rate_limit_error",
                    "code": "rate_limit_exceeded",
                }
            },
        )
    
class FailingQwen:

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
            "Fake Qwen timeout."
        )


class FakeGPT:

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
            capability="appointment.cancel",
            arguments={},
            confirmation="unknown",
            ambiguity_kind=None,
            correction_target=None,
            reason="",
        )


@pytest.mark.asyncio
async def test_circuit_opens_after_two_primary_failures(
    monkeypatch,
):

    # Force the planner policy to use Qwen.
    monkeypatch.setattr(
        fallback_module,
        "choose_planner_provider",
        lambda **kwargs: SimpleNamespace(
            provider="qwen",
            reason="test_fast_path",
            complexity_score=0,
            complexity_level="simple",
            semantic_margin=None,
            signals=(),
        ),
    )

    qwen = FailingQwen()
    gpt = FakeGPT()

    planner = FallbackToolPlanner(
        primary=qwen,
        fallback=gpt,
        circuit_failure_threshold=2,
        circuit_cooldown_seconds=60.0,
    )

    # Request 1:
    # Qwen fails -> GPT fallback.
    result_1 = await planner.plan(
        message="عايز أكنسل الحجز",
        candidates=[],
        context={},
    )

    assert result_1.capability == "appointment.cancel"

    assert qwen.calls == 1
    assert gpt.calls == 1

    # Request 2:
    # Qwen fails again -> GPT fallback.
    # Circuit should now open.
    result_2 = await planner.plan(
        message="عايز أكنسل الحجز",
        candidates=[],
        context={},
    )

    assert result_2.capability == "appointment.cancel"

    assert qwen.calls == 2
    assert gpt.calls == 2

    assert planner._is_primary_circuit_open()

    # Request 3:
    # Circuit is open.
    # Qwen MUST NOT be called again.
    result_3 = await planner.plan(
        message="عايز أكنسل الحجز",
        candidates=[],
        context={},
    )

    assert result_3.capability == "appointment.cancel"

    # Critical assertion:
    # still 2, not 3.
    assert qwen.calls == 2

    # GPT handled all three requests.
    assert gpt.calls == 3


class RecoveringQwen:

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

        # First two calls fail.
        if self.calls <= 2:
            raise TimeoutError(
                "Fake Qwen timeout."
            )

        # After cooldown, Qwen recovers.
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
async def test_circuit_recovers_after_cooldown(
    monkeypatch,
):

    # --------------------------------------------------------
    # Force simple request -> Qwen path
    # --------------------------------------------------------

    monkeypatch.setattr(
        fallback_module,
        "choose_planner_provider",
        lambda **kwargs: SimpleNamespace(
            provider="qwen",
            reason="test_fast_path",
            complexity_score=0,
            complexity_level="simple",
            semantic_margin=None,
            signals=(),
        ),
    )

    # --------------------------------------------------------
    # Fake monotonic clock
    # --------------------------------------------------------

    clock = {
        "now": 100.0,
    }

    monkeypatch.setattr(
        fallback_module.time,
        "monotonic",
        lambda: clock["now"],
    )

    qwen = RecoveringQwen()
    gpt = FakeGPT()

    planner = FallbackToolPlanner(
        primary=qwen,
        fallback=gpt,
        circuit_failure_threshold=2,
        circuit_cooldown_seconds=30.0,
    )

    # --------------------------------------------------------
    # Request 1
    # Qwen fails -> GPT
    # --------------------------------------------------------

    await planner.plan(
        message="عايز أكنسل الحجز",
        candidates=[],
        context={},
    )

    assert qwen.calls == 1
    assert gpt.calls == 1

    # --------------------------------------------------------
    # Request 2
    # Qwen fails again -> circuit opens
    # --------------------------------------------------------

    await planner.plan(
        message="عايز أكنسل الحجز",
        candidates=[],
        context={},
    )

    assert qwen.calls == 2
    assert gpt.calls == 2

    assert planner._is_primary_circuit_open()

    # --------------------------------------------------------
    # Request 3 during cooldown
    # Qwen MUST be skipped
    # --------------------------------------------------------

    clock["now"] = 110.0

    await planner.plan(
        message="عايز أكنسل الحجز",
        candidates=[],
        context={},
    )

    assert qwen.calls == 2
    assert gpt.calls == 3

    assert planner._is_primary_circuit_open()

    # --------------------------------------------------------
    # Move time beyond cooldown
    # --------------------------------------------------------

    clock["now"] = 131.0

    assert not planner._is_primary_circuit_open()

    # --------------------------------------------------------
    # Request 4
    # Qwen should be tried again and succeed
    # --------------------------------------------------------

    result = await planner.plan(
        message="عايز أكنسل الحجز",
        candidates=[],
        context={},
    )

    assert result.capability == "appointment.cancel"

    # Qwen was called again.
    assert qwen.calls == 3

    # GPT was NOT needed for request 4.
    assert gpt.calls == 3

    # Successful Qwen call resets the circuit.
    assert planner._primary_failure_count == 0

    assert not planner._is_primary_circuit_open()    


class RateLimitedQwen:

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

        request = httpx.Request(
            "POST",
            "https://api.groq.com/openai/v1/chat/completions",
        )

        response = httpx.Response(
            status_code=429,
            request=request,
        )

        raise RateLimitError(
            "Rate limit reached.",
            response=response,
            body={
                "error": {
                    "type": "tokens",
                    "code": "rate_limit_exceeded",
                }
            },
        )


@pytest.mark.asyncio
async def test_rate_limit_opens_primary_circuit(
    monkeypatch,
):

    monkeypatch.setattr(
        fallback_module,
        "choose_planner_provider",
        lambda **kwargs: SimpleNamespace(
            provider="qwen",
            reason="test_fast_path",
            complexity_score=0,
            complexity_level="simple",
            semantic_margin=None,
            signals=(),
        ),
    )

    qwen = RateLimitedQwen()
    gpt = FakeGPT()

    planner = FallbackToolPlanner(
        primary=qwen,
        fallback=gpt,
        circuit_failure_threshold=2,
        circuit_cooldown_seconds=60.0,
    )

    # First 429 -> GPT fallback.
    result_1 = await planner.plan(
        message="عايزة احجز",
        candidates=[],
        context={},
    )

    assert result_1.capability == "appointment.cancel"

    assert qwen.calls == 1
    assert gpt.calls == 1

    # Second 429 -> GPT fallback + circuit opens.
    result_2 = await planner.plan(
        message="عايزة احجز",
        candidates=[],
        context={},
    )

    assert result_2.capability == "appointment.cancel"

    assert qwen.calls == 2
    assert gpt.calls == 2

    assert planner._is_primary_circuit_open()

    # Third request:
    # Qwen must be skipped completely.
    result_3 = await planner.plan(
        message="عايزة احجز",
        candidates=[],
        context={},
    )

    assert result_3.capability == "appointment.cancel"

    assert qwen.calls == 2
    assert gpt.calls == 3            

@pytest.mark.asyncio
async def test_circuit_open_gpt_invalid_result_fails_closed(
    monkeypatch,
):

    monkeypatch.setattr(
        fallback_module,
        "choose_planner_provider",
        lambda **kwargs: SimpleNamespace(
            provider="qwen",
            reason="test_fast_path",
            complexity_score=0,
            complexity_level="simple",
            semantic_margin=None,
            signals=(),
        ),
    )

    qwen = FailingQwen()
    gpt = FakeGPT()

    planner = FallbackToolPlanner(
        primary=qwen,
        fallback=gpt,
        circuit_failure_threshold=2,
        circuit_cooldown_seconds=60.0,
    )

    # Force the primary circuit open so this test
    # exercises ONLY the circuit-open GPT path.
    planner._primary_failure_count = 2
    planner._circuit_open_until = (
        fallback_module.time.monotonic()
        + 60.0
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

    # Qwen must be skipped completely.
    assert qwen.calls == 0

    # GPT is called exactly once.
    assert gpt.calls == 1

    # GPT tried to switch from appointment.create
    # to appointment.cancel, so validation must
    # reject the result and fail closed.
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
async def test_qwen_failure_and_gpt_rate_limit_do_not_retry(
    monkeypatch,
):

    monkeypatch.setattr(
        fallback_module,
        "choose_planner_provider",
        lambda **kwargs: SimpleNamespace(
            provider="qwen",
            reason="test_fast_path",
            complexity_score=0,
            complexity_level="simple",
            semantic_margin=None,
            signals=(),
        ),
    )

    qwen = FailingQwen()
    gpt = RateLimitedGPT()

    planner = FallbackToolPlanner(
        primary=qwen,
        fallback=gpt,
        circuit_failure_threshold=2,
        circuit_cooldown_seconds=60.0,
    )

    with pytest.raises(OpenAIRateLimitError):
        await planner.plan(
            message="عايزة أحجز",
            candidates=[],
            context={},
        )

    assert qwen.calls == 1

    # GPT must be attempted exactly once.
    assert gpt.calls == 1

    # Only the actual Qwen failure is counted
    # against the primary circuit.
    assert planner._primary_failure_count == 1      