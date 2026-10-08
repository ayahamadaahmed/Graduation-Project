from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

from agent.medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)

from agent.medmind.understanding.candidate_selector import (
    select_capability_candidates,
)

from agent.medmind.understanding.qwen_tool_planner import (
    QwenToolPlanner,
)


load_dotenv()


CASES = [
    (
        "محتاج أكشف بكرة لو ينفع",
        "appointment.create",
    ),
    (
        "عايز أحجز كشف بكرة",
        "appointment.create",
    ),
    (
        "في مواعيد بكرة؟",
        "provider.get_slots",
    ),
    (
        "إيه المواعيد المتاحة لدكتور منى السبت؟",
        "provider.get_slots",
    ),
]


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

    passed = 0
    completed = 0

    for index, (
        message,
        expected,
    ) in enumerate(
        CASES,
        start=1,
    ):

        context = {}

        candidates = (
            select_capability_candidates(
                router=router,
                message=message,
                context=context,
                top_k=8,
            )
        )

        try:

            result = await planner.plan(
                message=message,
                candidates=candidates,
                context=context,
            )

        except Exception as exc:

            print(
                f"{index:02d} | ERROR | "
                f"{message}"
            )

            print(
                f"     {type(exc).__name__}: "
                f"{exc}"
            )

            continue

        completed += 1

        correct = (
            result.capability
            == expected
        )

        if correct:
            passed += 1

        print(
            f"{index:02d} | "
            f"{'PASS' if correct else 'FAIL'} | "
            f"{message}"
        )

        print(
            f"     expected: {expected}"
        )

        print(
            f"     qwen:     "
            f"{result.capability}"
        )

    print()
    print("=" * 60)

    print(
        f"Completed: {completed}/{len(CASES)}"
    )

    print(
        f"Correct completed: "
        f"{passed}/{completed}"
        if completed
        else "Correct completed: 0/0"
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )