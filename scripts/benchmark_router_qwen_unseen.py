from __future__ import annotations

import asyncio
import os
import time

from dotenv import load_dotenv

from agent.medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)
from agent.medmind.understanding.qwen_tool_planner import (
    QwenToolPlanner,
)


CASES = [
    # CREATE - unseen phrasing
    (
        "محتاج أكشف بكرة لو ينفع",
        "appointment.create",
    ),
    (
        "عاوز أظبط ميعاد مع دكتور جلدية",
        "appointment.create",
    ),

    # SEARCH - unseen phrasing
    (
        "هو ميعادي اللي حجزته امتى؟",
        "appointment.search",
    ),
    (
        "ممكن تقولي الحجز بتاعي يوم كام؟",
        "appointment.search",
    ),

    # CANCEL - unseen phrasing
    (
        "مش هقدر أجي، شيل الحجز",
        "appointment.cancel",
    ),
    (
        "خلاص مش محتاج الميعاد ده",
        "appointment.cancel",
    ),

    # RESCHEDULE - unseen phrasing
    (
        "ينفع نخلي الموعد يوم الأحد بدل السبت؟",
        "appointment.reschedule",
    ),
    (
        "بدل ما أجي بكرة خليها بعد بكرة",
        "appointment.reschedule",
    ),
]


async def main() -> None:
    load_dotenv()

    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is missing."
        )

    print("Loading semantic router...")

    router = SemanticCapabilityRouter()

    planner = QwenToolPlanner(
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

    print("\nUnseen Router + Qwen Benchmark\n")

    planner_correct = 0
    top8_correct = 0

    router_latencies = []
    qwen_latencies = []

    for index, (message, expected) in enumerate(
        CASES,
        start=1,
    ):
        router_started = time.perf_counter()

        candidates = router.route(
            message,
            top_k=8,
        )

        router_ms = (
            time.perf_counter()
            - router_started
        ) * 1000

        router_latencies.append(router_ms)

        candidate_names = [
            candidate.name
            for candidate in candidates
        ]

        retrieved = (
            expected in candidate_names
        )

        if retrieved:
            top8_correct += 1

        qwen_started = time.perf_counter()

        try:
            plan = await planner.plan(
                message=message,
                candidates=candidates,
                context={},
            )

            qwen_ms = (
                time.perf_counter()
                - qwen_started
            ) * 1000

            qwen_latencies.append(qwen_ms)

            predicted = plan.capability

            passed = (
                predicted == expected
            )

            if passed:
                planner_correct += 1

            status = (
                "PASS"
                if passed
                else "FAIL"
            )

            print(
                f"{index:02d} | "
                f"{status} | "
                f"{message}"
            )

            print(
                f"     expected: "
                f"{expected}"
            )

            print(
                f"     router top8: "
                f"{'YES' if retrieved else 'NO'}"
            )

            print(
                f"     qwen: "
                f"{predicted}"
            )

            print(
                f"     router_ms: "
                f"{router_ms:.2f}"
            )

            print(
                f"     qwen_ms: "
                f"{qwen_ms:.2f}"
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

        print()

    total = len(CASES)

    print("=" * 65)

    print(
        f"Router Top-8 Recall: "
        f"{top8_correct}/{total} "
        f"({top8_correct / total * 100:.1f}%)"
    )

    print(
        f"Qwen Planner Accuracy: "
        f"{planner_correct}/{total} "
        f"({planner_correct / total * 100:.1f}%)"
    )

    if router_latencies:
        print(
            f"Router Avg: "
            f"{sum(router_latencies) / len(router_latencies):.2f} ms"
        )

    if qwen_latencies:
        print(
            f"Qwen Avg: "
            f"{sum(qwen_latencies) / len(qwen_latencies):.2f} ms"
        )


if __name__ == "__main__":
    asyncio.run(main())