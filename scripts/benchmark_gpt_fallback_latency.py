from __future__ import annotations

import asyncio
import os
import statistics
import time

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from agent.medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)
from agent.medmind.understanding.candidate_selector import (
    select_capability_candidates,
)
from agent.medmind.understanding.tool_planner import (
    ToolPlanner,
)


TOP_K = 8
RUNS = 5

MESSAGE = "لا خليه الاتنين"

CONTEXT = {
    "active_capability":
        "appointment.reschedule",

    "stage":
        "awaiting_confirmation",

    "pending_confirmation":
        True,

    "collected_arguments": {
        "date_text": "الأحد",
        "time_text": "الساعة ستة",
    },
}


async def main() -> None:

    load_dotenv()

    model_name = os.getenv(
        "PLANNER_FALLBACK_MODEL",
        "gpt-4.1",
    )

    print(
        f"GPT model: {model_name}"
    )

    print(
        f"Runs: {RUNS}"
    )

    print(
        f"Message: {MESSAGE}"
    )

    print()

    # ========================================================
    # ROUTER
    #
    # Build candidates once.
    # Router time is intentionally excluded from GPT latency.
    # ========================================================

    router = SemanticCapabilityRouter()

    candidates = select_capability_candidates(
        router=router,
        message=MESSAGE,
        context=CONTEXT,
        top_k=TOP_K,
    )

    print(
        "Candidates:",
        [
            candidate.name
            for candidate
            in candidates
        ],
    )

    print()

    # ========================================================
    # GPT PLANNER
    #
    # Keep this configuration identical to the current
    # fallback configuration so this is a real baseline.
    # ========================================================

    model = ChatOpenAI(
        model=model_name,
        temperature=0,
        timeout=30,
    )

    planner = ToolPlanner(
        model=model,
    )

    latencies: list[float] = []
    successful = 0
    errors = 0

    # ========================================================
    # RUN
    # ========================================================

    for run_number in range(
        1,
        RUNS + 1,
    ):

        started = time.perf_counter()

        try:

            result = await planner.plan(
                message=MESSAGE,
                candidates=candidates,
                context=CONTEXT,
            )

            latency_ms = (
                time.perf_counter()
                - started
            ) * 1000

            latencies.append(
                latency_ms
            )

            successful += 1

            print(
                f"{run_number:02d} | "
                f"{latency_ms:.2f} ms | "
                f"{result.status} | "
                f"{result.capability}"
            )

            print(
                "     arguments:",
                result.arguments,
            )

            print(
                "     confirmation:",
                result.confirmation,
            )

        except Exception as exc:

            latency_ms = (
                time.perf_counter()
                - started
            ) * 1000

            errors += 1

            print(
                f"{run_number:02d} | ERROR | "
                f"{latency_ms:.2f} ms | "
                f"{type(exc).__name__}: "
                f"{exc}"
            )

    # ========================================================
    # SUMMARY
    # ========================================================

    print()
    print("=" * 65)
    print("GPT FALLBACK LATENCY SUMMARY")
    print("=" * 65)

    print(
        f"Successful: "
        f"{successful}/{RUNS}"
    )

    print(
        f"Errors: "
        f"{errors}/{RUNS}"
    )

    if latencies:

        print(
            f"Average: "
            f"{statistics.mean(latencies):.2f} ms"
        )

        print(
            f"P50: "
            f"{statistics.median(latencies):.2f} ms"
        )

        print(
            f"Min: "
            f"{min(latencies):.2f} ms"
        )

        print(
            f"Max: "
            f"{max(latencies):.2f} ms"
        )


if __name__ == "__main__":

    asyncio.run(
        main()
    )