from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

from agent.medmind.understanding.capability_router import (
    CapabilityMatch,
)

from agent.medmind.understanding.qwen_tool_planner import (
    QwenToolPlanner,
)


load_dotenv()


async def main() -> None:

    api_key = os.getenv(
        "GROQ_API_KEY"
    )

    model = os.getenv(
        "QWEN_PLANNER_MODEL",
        "qwen/qwen3.6-27b",
    )

    timeout = float(
        os.getenv(
            "QWEN_PLANNER_TIMEOUT",
            "3",
        )
    )

    max_tokens = int(
        os.getenv(
            "QWEN_PLANNER_MAX_TOKENS",
            "160",
        )
    )

    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is missing."
        )

    planner = QwenToolPlanner(
        api_key=api_key,
        model=model,
        timeout=timeout,
        max_tokens=max_tokens,
    )

    candidates = [
        CapabilityMatch(
            name="appointment.create",
            domain="appointment",
            score=0.90,
            matched_text="test",
        ),
        CapabilityMatch(
            name="appointment.reschedule",
            domain="appointment",
            score=0.70,
            matched_text="test",
        ),
        CapabilityMatch(
            name="provider.get_slots",
            domain="provider",
            score=0.60,
            matched_text="test",
        ),
    ]

    result = await planner.plan(
        message="ممكن أعمل حجز لبكرة؟",
        candidates=candidates,
        context={},
    )

    print()
    print("=" * 60)
    print("QWEN PLANNER SMOKE TEST")
    print("=" * 60)

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
        "CONFIRMATION:",
        result.confirmation,
    )

    print(
        "AMBIGUITY:",
        result.ambiguity_kind,
    )

    print(
        "CORRECTION TARGET:",
        result.correction_target,
    )


if __name__ == "__main__":
    asyncio.run(
        main()
    )