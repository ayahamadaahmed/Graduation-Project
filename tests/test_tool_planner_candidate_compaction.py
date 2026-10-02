from medmind.understanding.capability_router import (
    CapabilityMatch,
)

from medmind.understanding.tool_planner import (
    ToolPlanner,
)


def test_tool_planner_uses_compact_candidate_format():

    candidate = CapabilityMatch(
        name="appointment.create",
        domain="appointment",
        score=0.9123,
        matched_text="عايز أحجز",
    )

    text = ToolPlanner._build_candidate_text(
        [candidate]
    )

    # Required information.
    assert "appointment.create" in text
    assert "args=" in text

    # Compact one-line representation.
    assert " | " in text
    assert "\n" not in text

    # Redundant router/internal metadata must not
    # be sent to GPT.
    assert "domain:" not in text
    assert "description_en:" not in text
    assert "retrieval_score:" not in text