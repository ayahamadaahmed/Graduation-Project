from __future__ import annotations

import asyncio
import os
import statistics
import time

from dotenv import load_dotenv

from langchain_core.callbacks import (
    BaseCallbackHandler,
)

from langchain_openai import (
    ChatOpenAI,
)

from medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)

from medmind.understanding.candidate_selector import (
    select_capability_candidates,
)

from medmind.understanding.tool_planner import (
    ToolPlanner,
)


RUNS = 5
TOP_K = 8

MESSAGE = "لا خليه الاتنين"

CONTEXT = {
    "active_capability": (
        "appointment.reschedule"
    ),
    "stage": "awaiting_confirmation",
    "pending_confirmation": True,
    "collected_arguments": {
        "date_text": "الأحد",
        "time_text": "الساعة ستة",
    },
}


class TTFTCallback(
    BaseCallbackHandler,
):

    def __init__(self) -> None:
        self.started_at: float | None = None
        self.first_token_at: float | None = None

    def reset(self) -> None:
        self.started_at = None
        self.first_token_at = None

    def mark_start(self) -> None:
        self.started_at = (
            time.perf_counter()
        )

    def on_llm_new_token(
        self,
        token: str,
        **kwargs,
    ) -> None:
        if self.first_token_at is None:
            self.first_token_at = (
                time.perf_counter()
            )

    def ttft_ms(self) -> float | None:
        if (
            self.started_at is None
            or self.first_token_at is None
        ):
            return None

        return (
            self.first_token_at
            - self.started_at
        ) * 1000


async def main() -> None:
    load_dotenv(
        override=False
    )

    model_name = (
        os.getenv(
            "PLANNER_FALLBACK_MODEL"
        )
        or os.getenv(
            "PLANNER_MODEL"
        )
        or "gpt-4.1"
    )

    print(
        "GPT model:",
        model_name,
    )

    print(
        "Runs:",
        RUNS,
    )

    print(
        "Message:",
        MESSAGE,
    )

    router = (
        SemanticCapabilityRouter()
    )

    candidates = (
        select_capability_candidates(
            router=router,
            message=MESSAGE,
            context=CONTEXT,
            top_k=TOP_K,
        )
    )

    print(
        "Candidates:",
        [
            candidate.name
            for candidate in candidates
        ],
    )

    callback = TTFTCallback()

    model = ChatOpenAI(
        model=model_name,
        temperature=0,
        timeout=30,
        streaming=True,
        callbacks=[
            callback,
        ],
    )

    planner = ToolPlanner(
        model=model
    )

    total_latencies: list[float] = []
    ttft_values: list[float] = []

    for index in range(
        1,
        RUNS + 1,
    ):
        callback.reset()
        callback.mark_start()

        started = (
            time.perf_counter()
        )

        try:
            result = await planner.plan(
                message=MESSAGE,
                candidates=candidates,
                context=CONTEXT,
            )

            total_ms = (
                time.perf_counter()
                - started
            ) * 1000

            ttft_ms = (
                callback.ttft_ms()
            )

            total_latencies.append(
                total_ms
            )

            if ttft_ms is not None:
                ttft_values.append(
                    ttft_ms
                )

            print()

            print(
                f"{index:02d} | "
                f"TTFT="
                f"{ttft_ms:.2f} ms"
                if ttft_ms is not None
                else (
                    f"{index:02d} | "
                    "TTFT=N/A"
                )
            )

            print(
                f"     total="
                f"{total_ms:.2f} ms"
            )

            print(
                f"     status="
                f"{result.status}"
            )

            print(
                f"     capability="
                f"{result.capability}"
            )

            print(
                f"     arguments="
                f"{result.arguments}"
            )

        except Exception as exc:
            print(
                f"{index:02d} | ERROR | "
                f"{type(exc).__name__}: "
                f"{exc}"
            )

    print()
    print(
        "=" * 65
    )

    print(
        "GPT TTFT SUMMARY"
    )

    print(
        "=" * 65
    )

    if total_latencies:
        print(
            "Total P50:",
            f"{statistics.median(total_latencies):.2f} ms",
        )

        print(
            "Total min:",
            f"{min(total_latencies):.2f} ms",
        )

        print(
            "Total max:",
            f"{max(total_latencies):.2f} ms",
        )

    if ttft_values:
        print(
            "TTFT P50:",
            f"{statistics.median(ttft_values):.2f} ms",
        )

        print(
            "TTFT min:",
            f"{min(ttft_values):.2f} ms",
        )

        print(
            "TTFT max:",
            f"{max(ttft_values):.2f} ms",
        )

        generation_values = [
            total - ttft
            for total, ttft
            in zip(
                total_latencies,
                ttft_values,
            )
        ]

        if generation_values:
            print(
                "Post-TTFT P50:",
                f"{statistics.median(generation_values):.2f} ms",
            )


if __name__ == "__main__":
    asyncio.run(
        main()
    )