from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

from agent.medmind.understanding.capability_router import (
    CapabilityMatch,
)

from agent.medmind.understanding.fallback_tool_planner import (
    FallbackToolPlanner,
)

from agent.medmind.understanding.qwen_tool_planner import (
    QwenToolPlanner,
)


load_dotenv()


# ============================================================
# FAKE FALLBACK
#
# لو الكلاس حاول يستخدم fallback بالغلط،
# التست هيفشل فورًا.
# ============================================================

class ShouldNeverBeCalledFallback:

    async def plan(
        self,
        *,
        message,
        candidates,
        context=None,
    ):
        raise RuntimeError(
            "ERROR: fallback was called even though "
            "Qwen should have succeeded."
        )


# ============================================================
# MAIN
# ============================================================

async def main() -> None:

    api_key = os.getenv(
        "GROQ_API_KEY"
    )

    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is missing."
        )

    qwen = QwenToolPlanner(
        api_key=api_key,

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

    planner = FallbackToolPlanner(
        primary=qwen,
        fallback=ShouldNeverBeCalledFallback(),
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
    print("PRIMARY SUCCESS / FALLBACK NOT USED")
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

    print()
    print(
        "PASS: Qwen succeeded and fallback was not called."
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )