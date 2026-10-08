from __future__ import annotations

import asyncio
import os
import statistics
import time

from dotenv import load_dotenv
from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import ChatOpenAI

import medmind.understanding.tool_planner as tool_planner_module

from medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)

from medmind.understanding.candidate_selector import (
    select_capability_candidates,
)

from medmind.understanding.tool_planner import (
    PLANNER_INSTRUCTIONS,
    ToolPlanner,
)

from scripts.benchmark_gpt_ttft import (
    MESSAGE,
    CONTEXT,
    TOP_K,
)


RUNS = 5


# ============================================================
# COMPACT GPT INSTRUCTIONS
#
# Same core semantics.
# Only removes repetition and verbose examples.
# ============================================================

COMPACT_INSTRUCTIONS = """
You are MedMind's capability planner.

Choose only from the supplied candidate capabilities.

Rules:
- Determine the user's CURRENT operation, not only the topic.
- Use conversation context for short contextual replies.
- active_capability provides context but is not a restriction.
- Explicit operation switches are allowed.
- Return only values newly stated, corrected, changed, or
  selected in the CURRENT message.
- Never copy unchanged context values.
- Never invent values or database IDs.
- Preserve spoken date/time phrases.

Appointments:
- New booking -> appointment.create
- Existing booking lookup -> appointment.search
- Cancel existing booking -> appointment.cancel
- Change an existing booking -> appointment.reschedule
- Correcting fields while creating a booking keeps
  appointment.create

Missing workflow fields do not make an operation ambiguous.
The workflow will collect missing information later.

Confirmation:
- yes/no only when confirmation is pending.
- Replacement data during confirmation is a correction.
- For corrections with replacement data:
  confirmation = unknown.
- Do not copy old values from context.

If a field is wrong but no replacement is provided, use:
- patient name -> patient_name
- mobile/phone -> phone
- doctor -> doctor
- schedule/date -> schedule
- time only -> time
- national ID -> national_id

If replacement data is provided, put it in arguments and
normally leave correction_target null.

Ambiguity:
- needs_clarification when the requested operation cannot
  safely be determined.
- candidate_miss when the requested operation is clear but
  absent from the supplied candidates.

For selected results:
- capability must be one supplied candidate.
- arguments contain CURRENT-turn delta only.
- ambiguity_kind = null.
- keep correction_target null when there is no correction.
""".strip()


# ============================================================
# TTFT CALLBACK
# ============================================================

class TTFTCallback(BaseCallbackHandler):

    def __init__(self) -> None:
        self.started_at: float | None = None
        self.first_token_at: float | None = None

    def reset(self) -> None:
        self.started_at = None
        self.first_token_at = None

    def mark_start(self) -> None:
        self.started_at = time.perf_counter()

    def on_llm_new_token(
        self,
        token: str,
        **kwargs,
    ) -> None:

        if self.first_token_at is None:
            self.first_token_at = time.perf_counter()

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


# ============================================================
# RUN ONE VARIANT
# ============================================================

async def run_variant(
    *,
    name: str,
    instructions: str,
    planner: ToolPlanner,
    callback: TTFTCallback,
    candidates,
) -> tuple[list[float], list[float]]:

    # ToolPlanner reads this module-level value
    # while building its prompt.
    tool_planner_module.PLANNER_INSTRUCTIONS = instructions

    totals: list[float] = []
    ttfts: list[float] = []

    print()
    print("=" * 65)
    print(name)
    print("=" * 65)

    print(
        "Instructions chars:",
        len(instructions),
    )

    for index in range(1, RUNS + 1):

        callback.reset()
        callback.mark_start()

        started = time.perf_counter()

        result = await planner.plan(
            message=MESSAGE,
            candidates=candidates,
            context=CONTEXT,
        )

        total_ms = (
            time.perf_counter()
            - started
        ) * 1000

        ttft_ms = callback.ttft_ms()

        totals.append(total_ms)

        if ttft_ms is not None:
            ttfts.append(ttft_ms)

        print(
            f"{index:02d} | "
            f"TTFT="
            f"{ttft_ms:.2f} ms | "
            f"total="
            f"{total_ms:.2f} ms | "
            f"{result.capability}"
        )

    return totals, ttfts


# ============================================================
# SUMMARY
# ============================================================

def print_summary(
    name: str,
    totals: list[float],
    ttfts: list[float],
) -> None:

    print()
    print(name)

    print(
        "Total P50:",
        f"{statistics.median(totals):.2f} ms",
    )

    if ttfts:
        print(
            "TTFT P50:",
            f"{statistics.median(ttfts):.2f} ms",
        )

        print(
            "TTFT min:",
            f"{min(ttfts):.2f} ms",
        )

        print(
            "TTFT max:",
            f"{max(ttfts):.2f} ms",
        )


# ============================================================
# MAIN
# ============================================================

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
        "Runs per variant:",
        RUNS,
    )

    print(
        "Full instructions chars:",
        len(PLANNER_INSTRUCTIONS),
    )

    print(
        "Compact instructions chars:",
        len(COMPACT_INSTRUCTIONS),
    )

    router = SemanticCapabilityRouter()

    candidates = select_capability_candidates(
        router=router,
        message=MESSAGE,
        context=CONTEXT,
        top_k=TOP_K,
    )

    callback = TTFTCallback()

    model = ChatOpenAI(
        model=model_name,
        temperature=0,
        timeout=30,
        streaming=True,
        callbacks=[callback],
    )

    planner = ToolPlanner(
        model=model
    )

    # Alternate order helps reduce provider/time bias.
    full_totals: list[float] = []
    full_ttfts: list[float] = []

    compact_totals: list[float] = []
    compact_ttfts: list[float] = []

    for round_number in range(RUNS):

        variants = (
            [
                ("FULL", PLANNER_INSTRUCTIONS),
                ("COMPACT", COMPACT_INSTRUCTIONS),
            ]
            if round_number % 2 == 0
            else
            [
                ("COMPACT", COMPACT_INSTRUCTIONS),
                ("FULL", PLANNER_INSTRUCTIONS),
            ]
        )

        for name, instructions in variants:

            tool_planner_module.PLANNER_INSTRUCTIONS = (
                instructions
            )

            callback.reset()
            callback.mark_start()

            started = time.perf_counter()

            result = await planner.plan(
                message=MESSAGE,
                candidates=candidates,
                context=CONTEXT,
            )

            total_ms = (
                time.perf_counter()
                - started
            ) * 1000

            ttft_ms = callback.ttft_ms()

            print(
                f"{name:7} | "
                f"TTFT="
                f"{ttft_ms:.2f} ms | "
                f"total="
                f"{total_ms:.2f} ms | "
                f"{result.capability}"
            )

            if name == "FULL":
                full_totals.append(total_ms)
                full_ttfts.append(ttft_ms)

            else:
                compact_totals.append(total_ms)
                compact_ttfts.append(ttft_ms)

    # Restore original global value.
    tool_planner_module.PLANNER_INSTRUCTIONS = (
        PLANNER_INSTRUCTIONS
    )

    print()
    print("=" * 65)
    print("A/B SUMMARY")
    print("=" * 65)

    print_summary(
        "FULL",
        full_totals,
        full_ttfts,
    )

    print_summary(
        "COMPACT",
        compact_totals,
        compact_ttfts,
    )

    full_p50 = statistics.median(
        full_ttfts
    )

    compact_p50 = statistics.median(
        compact_ttfts
    )

    improvement = (
        (full_p50 - compact_p50)
        / full_p50
        * 100
    )

    print()
    print(
        "TTFT improvement:",
        f"{improvement:.2f}%",
    )


if __name__ == "__main__":
    asyncio.run(
        main()
    )