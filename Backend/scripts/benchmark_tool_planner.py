from __future__ import annotations

import asyncio
import math
import os
import time

from dotenv import (
    load_dotenv,
)

from langchain_openai import (
    ChatOpenAI,
)

from agent.medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)

from agent.medmind.understanding.tool_planner import (
    ToolPlanner,
)


# ============================================================
# SETTINGS
# ============================================================


TOP_K = 8


# ============================================================
# TEST CASES
# ============================================================


TEST_CASES = [

    (
        "ممكن أعمل حجز لبكرة؟",
        "appointment.create",
    ),

    (
        "إيه نظام تغيير المواعيد عندكم؟",
        "provider.get_policy",
    ),

    (
        "غير ميعادي للسبت",
        "appointment.reschedule",
    ),

    (
        "لو اتأخرت عن الميعاد بيحصل إيه؟",
        "provider.get_policy",
    ),

    (
        "الفرع بيقفل الساعة كام؟",
        "provider.get_working_hours",
    ),

    (
        "تكلفة كشف العيون إيه؟",
        "provider.get_services",
    ),

    (
        "عندي ميعاد قريب؟",
        "appointment.search",
    ),

    (
        "مين عندكم متخصص جلدية؟",
        "provider.search_doctors",
    ),

    (
        "عايز أكلم موظف",
        "human_support.transfer",
    ),

    (
        "فيه كشف متاح بعد الضهر؟",
        "provider.get_slots",
    ),
]


# ============================================================
# PERCENTILE
# ============================================================


def percentile(
    values: list[float],
    percentile_value: float,
) -> float:

    if not values:
        return 0.0

    sorted_values = sorted(
        values
    )

    if len(sorted_values) == 1:
        return sorted_values[0]

    position = (
        percentile_value
        / 100.0
    ) * (
        len(sorted_values) - 1
    )

    lower_index = math.floor(
        position
    )

    upper_index = math.ceil(
        position
    )

    if lower_index == upper_index:
        return sorted_values[
            lower_index
        ]

    lower_value = sorted_values[
        lower_index
    ]

    upper_value = sorted_values[
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


# ============================================================
# MAIN
# ============================================================


async def main() -> None:

    # --------------------------------------------------------
    # Important:
    #
    # override=False means a PowerShell environment variable:
    #
    # $env:TOOL_PLANNER_MODEL = "gpt-4.1"
    #
    # wins over the value inside .env.
    # --------------------------------------------------------

    load_dotenv(
        override=False
    )

    model_name = (
        os.getenv(
            "TOOL_PLANNER_MODEL"
        )
        or
        os.getenv(
            "OPENAI_MODEL"
        )
        or
        "gpt-4.1"
    )

    print(
        "Planner model:",
        model_name,
    )

    print(
        "Retriever Top-K:",
        TOP_K,
    )

    # ========================================================
    # INITIALIZE ROUTER
    # ========================================================

    router = (
        SemanticCapabilityRouter()
    )

    # ========================================================
    # INITIALIZE PLANNER MODEL
    # ========================================================

    model = ChatOpenAI(
        model=model_name,
        temperature=0,
        timeout=30,
    )

    planner = ToolPlanner(
        model=model
    )

    # ========================================================
    # METRICS
    # ========================================================

    planner_correct = 0
    retrieval_hits = 0

    planner_correct_when_retrieved = 0

    router_latencies: list[
        float
    ] = []

    planner_latencies: list[
        float
    ] = []

    understanding_latencies: list[
        float
    ] = []

    # ========================================================
    # RUN CASES
    # ========================================================

    for (
        message,
        expected,
    ) in TEST_CASES:

        # ====================================================
        # RETRIEVER
        # ====================================================

        router_started_at = (
            time.perf_counter()
        )

        candidates = router.route(
            message,
            top_k=TOP_K,
        )

        router_ms = (
            time.perf_counter()
            - router_started_at
        ) * 1000

        router_latencies.append(
            router_ms
        )

        candidate_names = [
            candidate.name
            for candidate
            in candidates
        ]

        retrieval_hit = (
            expected
            in candidate_names
        )

        if retrieval_hit:
            retrieval_hits += 1

        # ====================================================
        # PLANNER
        # ====================================================

        planner_started_at = (
            time.perf_counter()
        )

        result = await planner.plan(
            message=message,
            candidates=candidates,
            context={},
        )

        planner_ms = (
            time.perf_counter()
            - planner_started_at
        ) * 1000

        planner_latencies.append(
            planner_ms
        )

        understanding_ms = (
            router_ms
            + planner_ms
        )

        understanding_latencies.append(
            understanding_ms
        )

        # ====================================================
        # RESULT
        # ====================================================

        planner_ok = (
            result.status
            == "selected"
            and result.capability
            == expected
        )

        if planner_ok:
            planner_correct += 1

        if (
            retrieval_hit
            and planner_ok
        ):
            planner_correct_when_retrieved += 1

        # ====================================================
        # OUTPUT
        # ====================================================

        print()
        print("=" * 80)

        print(
            "USER:",
            message,
        )

        print(
            "EXPECTED:",
            expected,
        )

        print(
            "CANDIDATES:",
            candidate_names,
        )

        print(
            "RETRIEVAL:",
            (
                "HIT"
                if retrieval_hit
                else "MISS"
            ),
        )

        print(
            "PLANNER:",
            result.capability,
        )

        print(
            "STATUS:",
            result.status,
        )

        print(
            "ARGS:",
            result.arguments,
        )

        print(
            "REASON:",
            result.reason,
        )

        print(
            f"ROUTER LATENCY: "
            f"{router_ms:.2f} ms"
        )

        print(
            f"PLANNER LATENCY: "
            f"{planner_ms:.2f} ms"
        )

        print(
            f"UNDERSTANDING LATENCY: "
            f"{understanding_ms:.2f} ms"
        )

        print(
            "RESULT:",
            (
                "PASS"
                if planner_ok
                else "FAIL"
            ),
        )

    # ========================================================
    # FINAL METRICS
    # ========================================================

    total = len(
        TEST_CASES
    )

    retrieval_recall = (
        retrieval_hits
        / total
        if total
        else 0.0
    )

    planner_accuracy = (
        planner_correct
        / total
        if total
        else 0.0
    )

    planner_accuracy_when_retrieved = (
        planner_correct_when_retrieved
        / retrieval_hits
        if retrieval_hits
        else 0.0
    )

    average_router = (
        sum(
            router_latencies
        )
        / len(
            router_latencies
        )
        if router_latencies
        else 0.0
    )

    average_planner = (
        sum(
            planner_latencies
        )
        / len(
            planner_latencies
        )
        if planner_latencies
        else 0.0
    )

    average_understanding = (
        sum(
            understanding_latencies
        )
        / len(
            understanding_latencies
        )
        if understanding_latencies
        else 0.0
    )

    router_p50 = percentile(
        router_latencies,
        50,
    )

    router_p95 = percentile(
        router_latencies,
        95,
    )

    planner_p50 = percentile(
        planner_latencies,
        50,
    )

    planner_p95 = percentile(
        planner_latencies,
        95,
    )

    understanding_p50 = percentile(
        understanding_latencies,
        50,
    )

    understanding_p95 = percentile(
        understanding_latencies,
        95,
    )

    # ========================================================
    # FINAL OUTPUT
    # ========================================================

    print()
    print("=" * 80)
    print("FINAL RESULTS")
    print("=" * 80)

    print(
        f"Cases: {total}"
    )

    print(
        f"Retriever Top-{TOP_K} recall: "
        f"{retrieval_recall:.2%}"
    )

    print(
        f"Planner accuracy: "
        f"{planner_accuracy:.2%}"
    )

    print(
        "Planner accuracy when "
        f"retrieval HIT: "
        f"{planner_accuracy_when_retrieved:.2%}"
    )

    print()
    print(
        "ROUTER LATENCY"
    )

    print(
        f"Average: "
        f"{average_router:.2f} ms"
    )

    print(
        f"P50: "
        f"{router_p50:.2f} ms"
    )

    print(
        f"P95: "
        f"{router_p95:.2f} ms"
    )

    print()
    print(
        "PLANNER LATENCY"
    )

    print(
        f"Average: "
        f"{average_planner:.2f} ms"
    )

    print(
        f"P50: "
        f"{planner_p50:.2f} ms"
    )

    print(
        f"P95: "
        f"{planner_p95:.2f} ms"
    )

    print()
    print(
        "TOTAL UNDERSTANDING LATENCY"
    )

    print(
        f"Average: "
        f"{average_understanding:.2f} ms"
    )

    print(
        f"P50: "
        f"{understanding_p50:.2f} ms"
    )

    print(
        f"P95: "
        f"{understanding_p95:.2f} ms"
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )