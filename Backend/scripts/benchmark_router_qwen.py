from __future__ import annotations

import asyncio
import os
import time
import logging

from dotenv import load_dotenv

from agent.medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)
from agent.medmind.understanding.qwen_tool_planner import (
    QwenToolPlanner,
)
logging.basicConfig(
    level=logging.INFO,
)

logging.getLogger(
    "uvicorn.error"
).setLevel(
    logging.INFO
)

CASES = [
    (
        "عايز أكنسل الحجز",
        "appointment.cancel",
    ),
    (
        "ممكن أأجل الميعاد",
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

    print("\nRouter + Qwen Benchmark\n")

    for index, (message, expected) in enumerate(
        CASES,
        start=1,
    ):
        # ---------------------------------------------
        # 1. Semantic Router
        # ---------------------------------------------

        router_started = time.perf_counter()

        candidates = router.route(
            message,
            top_k=8,
        )

        router_ms = (
            time.perf_counter()
            - router_started
        ) * 1000

        print(
            f"{index:02d} | {message}"
        )

        print(
            f"     expected: {expected}"
        )

        print(
            f"     router:   {router_ms:.2f} ms"
        )

        print(
            "     candidates:"
        )

        for rank, candidate in enumerate(
            candidates,
            start=1,
        ):
            print(
                f"       {rank}. "
                f"{candidate.name:<30} "
                f"{candidate.score:.4f}"
            )

        # ---------------------------------------------
        # 2. Qwen Planner
        # ---------------------------------------------

        planner_started = time.perf_counter()

        try:
            plan = await planner.plan(
                message=message,
                candidates=candidates,
                context={},
            )

            planner_ms = (
                time.perf_counter()
                - planner_started
            ) * 1000

            print(
                f"     qwen:     "
                f"{planner_ms:.2f} ms"
            )

            print(
                "     plan:"
            )

            print(
                plan.model_dump()
            )

        except Exception as exc:
            planner_ms = (
                time.perf_counter()
                - planner_started
            ) * 1000

            print(
                f"     QWEN ERROR "
                f"after {planner_ms:.2f} ms:"
            )

            print(
                f"     {type(exc).__name__}: "
                f"{exc}"
            )

        print()


if __name__ == "__main__":
    asyncio.run(main())