from agent.medmind.understanding.capability_router import (
    CapabilityMatch,
)

from agent.medmind.understanding.qwen_tool_planner import (
    QwenToolPlanner,
)


def test_candidate_text_preserves_semantic_evidence():

    candidates = [
        CapabilityMatch(
            name="knowledge.search",
            domain="knowledge",
            score=1.0,
            matched_text=(
                "دكتور ماهر بيعالج حب الشباب؟"
            ),
        ),
        CapabilityMatch(
            name="provider.search_doctors",
            domain="provider",
            score=0.5185,
            matched_text=(
                "عندكم دكاترة جلدية مين"
            ),
        ),
    ]

    text = (
        QwenToolPlanner
        ._build_candidate_text(
            candidates
        )
    )

    assert (
        "knowledge.search"
        in text
    )

    assert (
        "semantic_score=1.0000"
        in text
    )

    assert (
        "دكتور ماهر بيعالج حب الشباب؟"
        in text
    )

    assert (
        "semantic_score=0.5185"
        in text
    )