from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

from agent.medmind.service import (
    MedMindService,
)

from agent.medmind.state.models import (
    SessionState,
)

from agent.medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)

from agent.medmind.understanding.qwen_tool_planner import (
    QwenToolPlanner,
)


load_dotenv()


async def main() -> None:

    message = "ممكن أعمل حجز لبكرة؟"

    # ========================================================
    # SAME ROUTER USED BY PRODUCTION
    # ========================================================

    router = SemanticCapabilityRouter()

    candidates = router.route(
        message,
        top_k=8,
    )

    print()
    print("CANDIDATES:")
    print(
        [
            candidate.name
            for candidate in candidates
        ]
    )

    # ========================================================
    # SAME QWEN PLANNER
    # ========================================================

    planner = QwenToolPlanner(
        api_key=os.environ[
            "GROQ_API_KEY"
        ],

        model=os.getenv(
            "QWEN_PLANNER_MODEL",
            "qwen/qwen3.6-27b",
        ),

        timeout=float(
            os.getenv(
                "QWEN_PLANNER_TIMEOUT",
                "3",
            )
        ),

        max_tokens=int(
            os.getenv(
                "QWEN_PLANNER_MAX_TOKENS",
                "160",
            )
        ),
    )

    # ========================================================
    # NEW SESSION — SAME SHAPE AS PRODUCTION
    # ========================================================

    state = SessionState(
        channel="web",
        session_id="context-test-001",
        tenant_id="clinic-001",
        language="ar",
    )

    production_context = (
        MedMindService
        ._build_understanding_context(
            state
        )
    )

    # ========================================================
    # TEST A — EMPTY CONTEXT
    # ========================================================

    print()
    print("=" * 70)
    print("TEST A — EMPTY CONTEXT")
    print("=" * 70)

    result_empty = await planner.plan(
        message=message,
        candidates=candidates,
        context={},
    )

    print(
        "STATUS:",
        result_empty.status,
    )

    print(
        "CAPABILITY:",
        result_empty.capability,
    )

    print(
        "ARGS:",
        result_empty.arguments,
    )

    print(
        "AMBIGUITY:",
        result_empty.ambiguity_kind,
    )

    # ========================================================
    # TEST B — REAL PRODUCTION CONTEXT
    # ========================================================

    print()
    print("=" * 70)
    print("TEST B — PRODUCTION CONTEXT")
    print("=" * 70)

    print(
        "CONTEXT:",
        production_context,
    )

    result_production = await planner.plan(
        message=message,
        candidates=candidates,
        context=production_context,
    )

    print()
    print(
        "STATUS:",
        result_production.status,
    )

    print(
        "CAPABILITY:",
        result_production.capability,
    )

    print(
        "ARGS:",
        result_production.arguments,
    )

    print(
        "AMBIGUITY:",
        result_production.ambiguity_kind,
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )