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

from agent.medmind.understanding.tool_planner import (
    ToolPlanner,
)


load_dotenv()


# ============================================================
# FAKE FAILED PRIMARY
#
# يمثل Qwen لما يحصل له timeout / API failure.
# ============================================================

class FailedPrimaryPlanner:

    async def plan(
        self,
        *,
        message,
        candidates,
        context=None,
    ):
        raise RuntimeError(
            "Simulated primary planner failure."
        )


# ============================================================
# MAIN
# ============================================================

async def main() -> None:

    api_key = os.getenv(
        "OPENAI_API_KEY"
    )

    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is missing."
        )

    fallback_model_name = os.getenv(
        "PLANNER_FALLBACK_MODEL",
        "gpt-4.1",
    )

    # --------------------------------------------------------
    # GPT-4.1 fallback
    # --------------------------------------------------------

    gpt_model = ChatOpenAI(
        model=fallback_model_name,
        temperature=0,
        timeout=60,
    )

    gpt_planner = ToolPlanner(
        model=gpt_model,
    )

    # --------------------------------------------------------
    # Primary → fails
    # Fallback → GPT-4.1
    # --------------------------------------------------------

    planner = FallbackToolPlanner(
        primary=FailedPrimaryPlanner(),
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
    print("PRIMARY FAILURE / GPT-4.1 FALLBACK")
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
        "PASS: Primary failed and GPT-4.1 "
        "returned the planner result."
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )