from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

from agent.medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)

from agent.medmind.understanding.qwen_tool_planner import (
    QwenToolPlanner,
)


load_dotenv()


async def main() -> None:

    router = SemanticCapabilityRouter()

    planner = QwenToolPlanner(
        api_key=os.environ["GROQ_API_KEY"],
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

    message = "ممكن أعمل حجز لبكرة؟"

    for top_k in (
        3,
        5,
        8,
    ):

        print()
        print("=" * 70)
        print(
            f"TOP-K = {top_k}"
        )
        print("=" * 70)

        candidates = router.route(
            message,
            top_k=top_k,
        )

        print(
            "CANDIDATES:",
            [
                candidate.name
                for candidate in candidates
            ],
        )

        result = await planner.plan(
            message=message,
            candidates=candidates,
            context={},
        )

        print(
            "STATUS:",
            result.status,
        )

        print(
            "CAPABILITY:",
            result.capability,
        )

        print(
            "ARGUMENTS:",
            result.arguments,
        )

        print(
            "AMBIGUITY:",
            result.ambiguity_kind,
        )


if __name__ == "__main__":

    asyncio.run(
        main()
    )