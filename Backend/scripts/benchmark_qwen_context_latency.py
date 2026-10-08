from __future__ import annotations

import asyncio
import os
import time

from dotenv import load_dotenv

from agent.medmind.state.models import (
    SessionState,
)

from agent.medmind.service import (
    MedMindService,
)

from agent.medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)

from agent.medmind.understanding.candidate_selector import (
    select_capability_candidates,
)

from agent.medmind.understanding.qwen_tool_planner import (
    QwenToolPlanner,
)
import logging

load_dotenv()


logging.basicConfig(
    level=logging.INFO,
)

logging.getLogger(
    "uvicorn.error"
).setLevel(
    logging.INFO
)

async def main() -> None:

    message = "جلدية"

    router = SemanticCapabilityRouter()

    state = SessionState(
        channel="web",
        session_id="latency-test",
        tenant_id="clinic-001",
        language="ar",
        operation_type="book_appointment",
        stage="awaiting_specialty",
    )

    context = (
        MedMindService
        ._build_understanding_context(
            state
        )
    )

    candidates = select_capability_candidates(
        router=router,
        message=message,
        context=context,
        top_k=8,
    )

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

    latencies = []
    timeouts = 0

    for index in range(1, 11):

        started = time.perf_counter()

        try:

            result = await planner.plan(
                message=message,
                candidates=candidates,
                context=context,
            )

            elapsed_ms = (
                time.perf_counter()
                - started
            ) * 1000

            latencies.append(
                elapsed_ms
            )

            print(
                f"{index:02d} | "
                f"{elapsed_ms:.2f} ms | "
                f"{result.status} | "
                f"{result.capability} | "
                f"{result.arguments}"
            )

        except TimeoutError:

            elapsed_ms = (
                time.perf_counter()
                - started
            ) * 1000

            timeouts += 1

            print(
                f"{index:02d} | "
                f"{elapsed_ms:.2f} ms | "
                f"TIMEOUT"
            )

    print()
    print("=" * 60)
    print("RESULT")
    print("=" * 60)

    print(
        "Successful:",
        len(latencies),
    )

    print(
        "Timeouts:",
        timeouts,
    )

    if latencies:

        ordered = sorted(
            latencies
        )

        print(
            "Average:",
            f"{sum(ordered) / len(ordered):.2f} ms",
        )

        print(
            "P50:",
            f"{ordered[len(ordered) // 2]:.2f} ms",
        )

        print(
            "Max:",
            f"{max(ordered):.2f} ms",
        )


if __name__ == "__main__":

    asyncio.run(
        main()
    )