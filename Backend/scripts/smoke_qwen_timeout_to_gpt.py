from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

from langchain_openai import (
    ChatOpenAI,
)

from agent.medmind.understanding.capability_router import (
    CapabilityMatch,
)

from agent.medmind.understanding.fallback_tool_planner import (
    FallbackToolPlanner,
)

from agent.medmind.understanding.qwen_tool_planner import (
    QwenToolPlanner,
)

from agent.medmind.understanding.tool_planner import (
    ToolPlanner,
)


load_dotenv()


async def main() -> None:

    groq_api_key = os.getenv(
        "GROQ_API_KEY"
    )

    openai_api_key = os.getenv(
        "OPENAI_API_KEY"
    )

    if not groq_api_key:
        raise RuntimeError(
            "GROQ_API_KEY is missing."
        )

    if not openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is missing."
        )

    # ========================================================
    # REAL QWEN PRIMARY
    #
    # Intentionally tiny timeout so Qwen should fail.
    # ========================================================

    qwen_planner = QwenToolPlanner(
        api_key=groq_api_key,

        model=os.getenv(
            "QWEN_PLANNER_MODEL",
            "qwen/qwen3.6-27b",
        ),

        # Intentional timeout for this test only.
        timeout=0.001,

        max_tokens=int(
            os.getenv(
                "QWEN_PLANNER_MAX_TOKENS",
                "160",
            )
        ),
    )

    # ========================================================
    # GPT-4.1 FALLBACK
    # ========================================================

    fallback_model_name = os.getenv(
        "PLANNER_FALLBACK_MODEL",
        "gpt-4.1",
    )

    gpt_model = ChatOpenAI(
        model=fallback_model_name,
        temperature=0,
        timeout=60,
    )

    gpt_planner = ToolPlanner(
        model=gpt_model,
    )

    # ========================================================
    # FALLBACK ARCHITECTURE
    # ========================================================

    planner = FallbackToolPlanner(
        primary=qwen_planner,
        fallback=gpt_planner,
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
    print("REAL QWEN TIMEOUT -> GPT-4.1 FALLBACK")
    print("=" * 60)

    print(
        "FALLBACK MODEL:",
        fallback_model_name,
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

    print()
    print(
        "PASS: Real Qwen timed out and "
        "GPT-4.1 handled the request."
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )