from __future__ import annotations

from agent.medmind.state.models import (
    SessionState,
)

from agent.medmind.understanding.capabilities import (
    get_capability,
)

from agent.medmind.understanding.capability_router import (
    CapabilityMatch,
)

from agent.medmind.understanding.legacy_adapter import (
    adapt_understanding_to_nlu,
)

from agent.medmind.understanding.orchestrator import (
    UnderstandingResult,
)

from agent.medmind.understanding.qwen_tool_planner import (
    QwenToolPlanner,
)

from agent.medmind.understanding.tool_planner import (
    ToolPlan,
)


def test_appointment_search_accepts_reference_argument():

    capability = get_capability(
        "appointment.search"
    )

    assert capability is not None

    assert (
        "appointment_reference"
        in capability.arguments
    )


def test_qwen_guard_preserves_appointment_reference():

    result = ToolPlan(
        status="selected",
        capability="appointment.search",
        arguments={
            "appointment_reference":
                "APT-260815-ABCD1234",
        },
        confirmation="unknown",
        ambiguity_kind=None,
        correction_target=None,
        reason="",
    )

    validated = (
        QwenToolPlanner._validate_result(
            result=result,
            candidates=[
                CapabilityMatch(
                    name="appointment.search",
                    domain="appointment",
                    score=0.95,
                    matched_text="appointment search",
                )
            ],
        )
    )

    assert validated.arguments == {
        "appointment_reference":
            "APT-260815-ABCD1234",
    }


def test_explicit_reference_becomes_exact_lookup():

    state = SessionState(
        channel="web",
        session_id="test-session",
        tenant_id="clinic-001",
    )

    understanding = UnderstandingResult(
        status="selected",
        capability="appointment.search",
        arguments={
            "appointment_reference":
                "APT-260815-ABCD1234",
        },
    )

    nlu = adapt_understanding_to_nlu(
        result=understanding,
        state=state,
    )

    assert (
        nlu.intent
        == "lookup_appointment"
    )

    assert (
        nlu.operation_type
        == "lookup_appointment"
    )

    assert (
        nlu.entities.appointment_reference
        == "APT-260815-ABCD1234"
    )