from __future__ import annotations

import json

from medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)

from medmind.understanding.candidate_selector import (
    select_capability_candidates,
)

from medmind.understanding.tool_planner import (
    PLANNER_INSTRUCTIONS,
    ToolPlanner,
)

from scripts.benchmark_gpt_ttft import (
    MESSAGE,
    CONTEXT,
    TOP_K,
)


def main() -> None:

    router = SemanticCapabilityRouter()

    candidates = (
        select_capability_candidates(
            router=router,
            message=MESSAGE,
            context=CONTEXT,
            top_k=TOP_K,
        )
    )

    candidate_text = (
        ToolPlanner._build_candidate_text(
            candidates
        )
    )

    context_text = json.dumps(
        CONTEXT,
        ensure_ascii=False,
        default=str,
    )

    prompt = f"""
{PLANNER_INSTRUCTIONS}


CURRENT CONTEXT

{context_text}


CANDIDATE CAPABILITIES

{candidate_text}


CURRENT USER MESSAGE

{MESSAGE}
""".strip()

    print()
    print("=" * 60)
    print("GPT PROMPT SIZE")
    print("=" * 60)

    print(
        "Instructions chars:",
        len(PLANNER_INSTRUCTIONS),
    )

    print(
        "Candidates chars:",
        len(candidate_text),
    )

    print(
        "Context chars:",
        len(context_text),
    )

    print(
        "User message chars:",
        len(MESSAGE),
    )

    print(
        "Total prompt chars:",
        len(prompt),
    )

    print()
    print(
        "Candidate count:",
        len(candidates),
    )

    print(
        "Candidates:",
        [
            candidate.name
            for candidate in candidates
        ],
    )


if __name__ == "__main__":
    main()