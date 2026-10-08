from __future__ import annotations

import asyncio
import math
import os
import statistics
import time

from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)

from medmind.understanding.candidate_selector import (
    select_capability_candidates,
)

from medmind.understanding.tool_planner import (
    ToolPlanner,
)


TOP_K = 8
ROUNDS = 7


@dataclass
class Case:
    name: str
    message: str
    expected_capability: str

    context: dict[str, Any] = field(
        default_factory=dict
    )


CASES = [

    Case(
        name="operation_switch",
        message="لا متلغهوش، غيره للسبت",
        expected_capability="appointment.reschedule",
        context={
            "active_capability": "appointment.cancel",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,
        },
    ),

    Case(
        name="multiple_conditions",
        message=(
            "لو مفيش بكرة شوفلي بعده "
            "بس يكون بعد الساعة خمسة"
        ),
        expected_capability="appointment.create",
        context={
            "active_capability": "appointment.create",
            "stage": "awaiting_date",
        },
    ),

    Case(
        name="search_then_reschedule",
        message=(
            "شوف حجزي الأول ولو موجود "
            "غيره للاتنين"
        ),
        expected_capability="appointment.reschedule",
    ),
]


def percentile(
    values: list[float],
    percent: float,
) -> float:

    ordered = sorted(values)

    if len(ordered) == 1:
        return ordered[0]

    position = (
        len(ordered) - 1
    ) * percent

    lower_index = math.floor(
        position
    )

    upper_index = math.ceil(
        position
    )

    if lower_index == upper_index:
        return ordered[
            lower_index
        ]

    lower_value = ordered[
        lower_index
    ]

    upper_value = ordered[
        upper_index
    ]

    fraction = (
        position
        - lower_index
    )

    return (
        lower_value
        + (
            upper_value
            - lower_value
        )
        * fraction
    )


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
        "Rounds:",
        ROUNDS,
    )

    print(
        "Cases:",
        len(CASES),
    )

    print(
        "Total planned calls:",
        ROUNDS * len(CASES),
    )

    router = (
        SemanticCapabilityRouter()
    )

    # Build candidates before latency measurement.
    prepared_cases = []

    for case in CASES:

        candidates = (
            select_capability_candidates(
                router=router,
                message=case.message,
                context=case.context,
                top_k=TOP_K,
            )
        )

        prepared_cases.append(
            (
                case,
                candidates,
            )
        )

    gpt_timeout = float(
        os.getenv(
            "GPT_PLANNER_TIMEOUT",
            "4",
        )
    )

    print(
        "GPT timeout:",
        gpt_timeout,
    )    

    model = ChatOpenAI(
        model=model_name,
        temperature=0,
        timeout=gpt_timeout,
        max_retries=0,
    )

    planner = ToolPlanner(
        model=model,
    )

    all_latencies: list[float] = []

    per_case: dict[
        str,
        list[float],
    ] = {
        case.name: []
        for case in CASES
    }

    successes = 0
    errors = 0

    for round_number in range(
        1,
        ROUNDS + 1,
    ):

        print()
        print(
            "=" * 70
        )

        print(
            f"ROUND {round_number}"
        )

        print(
            "=" * 70
        )

        # Rotate execution order slightly so one case
        # is not always first or last.
        offset = (
            round_number - 1
        ) % len(
            prepared_cases
        )

        ordered_cases = (
            prepared_cases[offset:]
            + prepared_cases[:offset]
        )

        for (
            case,
            candidates,
        ) in ordered_cases:

            started = (
                time.perf_counter()
            )

            try:

                result = await planner.plan(
                    message=case.message,
                    candidates=candidates,
                    context=case.context,
                )

                latency_ms = (
                    time.perf_counter()
                    - started
                ) * 1000

                capability_ok = (
                    result.capability
                    == case.expected_capability
                )

                all_latencies.append(
                    latency_ms
                )

                per_case[
                    case.name
                ].append(
                    latency_ms
                )

                if capability_ok:
                    successes += 1

                print(
                    f"{case.name:26} | "
                    f"{latency_ms:8.2f} ms | "
                    f"{result.capability} | "
                    f"{'PASS' if capability_ok else 'FAIL'}"
                )

            except Exception as exc:

                latency_ms = (
                    time.perf_counter()
                    - started
                ) * 1000

                errors += 1

                print(
                    f"{case.name:26} | "
                    f"{latency_ms:8.2f} ms | "
                    f"ERROR | "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

    print()
    print(
        "=" * 70
    )

    print(
        "GPT COMPLEX LATENCY SUMMARY"
    )

    print(
        "=" * 70
    )

    print(
        "Successful semantic results:",
        successes,
    )

    print(
        "Errors:",
        errors,
    )

    if all_latencies:

        print(
            "Samples:",
            len(all_latencies),
        )

        print(
            "Average:",
            f"{statistics.mean(all_latencies):.2f} ms",
        )

        print(
            "P50:",
            f"{percentile(all_latencies, 0.50):.2f} ms",
        )

        print(
            "P90:",
            f"{percentile(all_latencies, 0.90):.2f} ms",
        )

        print(
            "P95:",
            f"{percentile(all_latencies, 0.95):.2f} ms",
        )

        print(
            "Max:",
            f"{max(all_latencies):.2f} ms",
        )

    print()
    print(
        "PER CASE"
    )

    print(
        "-" * 70
    )

    for (
        case_name,
        values,
    ) in per_case.items():

        if not values:
            continue

        print(
            f"{case_name}: "
            f"P50={percentile(values, 0.50):.2f} ms | "
            f"P95={percentile(values, 0.95):.2f} ms | "
            f"Max={max(values):.2f} ms"
        )


if __name__ == "__main__":

    asyncio.run(
        main()
    )