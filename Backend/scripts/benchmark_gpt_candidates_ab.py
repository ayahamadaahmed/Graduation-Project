from __future__ import annotations

import asyncio
import os
import statistics
import time

from dotenv import load_dotenv
from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import ChatOpenAI

from medmind.understanding.capabilities import (
    get_capability,
)

from medmind.understanding.capability_router import (
    CapabilityMatch,
    SemanticCapabilityRouter,
)

from medmind.understanding.candidate_selector import (
    select_capability_candidates,
)

from medmind.understanding.tool_planner import (
    ToolPlanner,
)

from scripts.benchmark_gpt_ttft import (
    MESSAGE,
    CONTEXT,
    TOP_K,
)


RUNS = 5


# ============================================================
# COMPACT CANDIDATE PLANNER
#
# Same ToolPlanner behavior.
# Only candidate representation changes.
# ============================================================

class CompactCandidateToolPlanner(
    ToolPlanner
):

    @staticmethod
    def _build_candidate_text(
        candidates: list[CapabilityMatch],
    ) -> str:

        lines: list[str] = []

        for candidate in candidates:

            capability = get_capability(
                candidate.name
            )

            if capability is None:
                continue

            argument_names = list(
                capability.arguments.keys()
            )

            arguments_text = (
                ", ".join(argument_names)
                if argument_names
                else "none"
            )

            lines.append(
                (
                    f"{capability.name} | "
                    f"{capability.description_ar} | "
                    f"args={arguments_text}"
                )
            )

        return "\n".join(lines)


# ============================================================
# TTFT CALLBACK
# ============================================================

class TTFTCallback(
    BaseCallbackHandler
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

    def ttft_ms(
        self,
    ) -> float | None:

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

    router = SemanticCapabilityRouter()

    candidates = (
        select_capability_candidates(
            router=router,
            message=MESSAGE,
            context=CONTEXT,
            top_k=TOP_K,
        )
    )

    # --------------------------------------------------------
    # Compare representation sizes before making API calls.
    # --------------------------------------------------------

    full_candidate_text = (
        ToolPlanner._build_candidate_text(
            candidates
        )
    )

    compact_candidate_text = (
        CompactCandidateToolPlanner
        ._build_candidate_text(
            candidates
        )
    )

    print(
        "Full candidate chars:",
        len(full_candidate_text),
    )

    print(
        "Compact candidate chars:",
        len(compact_candidate_text),
    )

    reduction = (
        (
            len(full_candidate_text)
            - len(compact_candidate_text)
        )
        / len(full_candidate_text)
        * 100
    )

    print(
        "Candidate reduction:",
        f"{reduction:.2f}%",
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

    full_planner = ToolPlanner(
        model=model
    )

    compact_planner = (
        CompactCandidateToolPlanner(
            model=model
        )
    )

    full_totals: list[float] = []
    full_ttfts: list[float] = []

    compact_totals: list[float] = []
    compact_ttfts: list[float] = []

    # --------------------------------------------------------
    # Alternate order:
    #
    # round 1: FULL -> COMPACT
    # round 2: COMPACT -> FULL
    #
    # This reduces warm-up/provider timing bias.
    # --------------------------------------------------------

    for round_number in range(RUNS):

        variants = (
            [
                (
                    "FULL",
                    full_planner,
                ),
                (
                    "COMPACT",
                    compact_planner,
                ),
            ]
            if round_number % 2 == 0
            else
            [
                (
                    "COMPACT",
                    compact_planner,
                ),
                (
                    "FULL",
                    full_planner,
                ),
            ]
        )

        for name, planner in variants:

            callback.reset()
            callback.mark_start()

            started = (
                time.perf_counter()
            )

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

            if ttft_ms is None:
                raise RuntimeError(
                    "TTFT was not captured."
                )

            print(
                f"{name:7} | "
                f"TTFT={ttft_ms:.2f} ms | "
                f"total={total_ms:.2f} ms | "
                f"{result.capability} | "
                f"{result.arguments}"
            )

            if name == "FULL":

                full_totals.append(
                    total_ms
                )

                full_ttfts.append(
                    ttft_ms
                )

            else:

                compact_totals.append(
                    total_ms
                )

                compact_ttfts.append(
                    ttft_ms
                )

    print()
    print("=" * 65)
    print("CANDIDATE A/B SUMMARY")
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

    full_ttft_p50 = (
        statistics.median(
            full_ttfts
        )
    )

    compact_ttft_p50 = (
        statistics.median(
            compact_ttfts
        )
    )

    ttft_improvement = (
        (
            full_ttft_p50
            - compact_ttft_p50
        )
        / full_ttft_p50
        * 100
    )

    full_total_p50 = (
        statistics.median(
            full_totals
        )
    )

    compact_total_p50 = (
        statistics.median(
            compact_totals
        )
    )

    total_improvement = (
        (
            full_total_p50
            - compact_total_p50
        )
        / full_total_p50
        * 100
    )

    print()

    print(
        "TTFT improvement:",
        f"{ttft_improvement:.2f}%",
    )

    print(
        "Total improvement:",
        f"{total_improvement:.2f}%",
    )


if __name__ == "__main__":
    asyncio.run(
        main()
    )