from __future__ import annotations

import asyncio
import math
import os
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


TEST_CASES = [

    # ========================================================
    # A. Genuine ambiguity
    # Planner should NOT guess.
    # ========================================================

    {
        "name": "ambiguous_change_without_context",
        "message": "عايز أغيره",
        "expected_status": "ambiguous",
        "expected_capability": None,
        "expected_arguments": {},
        "context": {},
    },

    {
        "name": "ambiguous_reference_without_context",
        "message": "التاني",
        "expected_status": "ambiguous",
        "expected_capability": None,
        "expected_arguments": {},
        "context": {},
    },

    {
        "name": "ambiguous_generic_help",
        "message": "ممكن تساعدني في الحجز؟",
        "expected_status": "ambiguous",
        "expected_capability": None,
        "expected_arguments": {},
        "context": {},
    },

    {
        "name": "ambiguous_correction_without_context",
        "message": "لا مش كده",
        "expected_status": "ambiguous",
        "expected_capability": None,
        "expected_arguments": {},
        "context": {},
    },

    {
        "name": "ambiguous_english_reference",
        "message": "the other one",
        "expected_status": "ambiguous",
        "expected_capability": None,
        "expected_arguments": {},
        "context": {},
    },

    # ========================================================
    # B. Context resolves otherwise ambiguous message
    # ========================================================

    {
        "name": "context_resolves_second_doctor",
        "message": "التاني",
        "expected_status": "selected",
        "expected_capability": "appointment.create",
        "expected_arguments": {
            "doctor_name": "منى صلاح",
        },
        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_doctor",
            "offered_doctors": [
                "ماهر محمود",
                "منى صلاح",
            ],
        },
    },

    {
        "name": "context_resolves_date_change",
        "message": "خليه الأحد",
        "expected_status": "selected",
        "expected_capability": "appointment.create",
        "expected_arguments": {
            "date_text": "الأحد",
        },
        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_date",
            "collected_arguments": {
                "doctor_name": "ماهر محمود",
            },
        },
    },

    {
        "name": "context_resolves_time",
        "message": "الساعة ستة",
        "expected_status": "selected",
        "expected_capability": "appointment.create",
        "expected_arguments": {
            "time_text": "الساعة ستة",
        },
        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_time",
            "collected_arguments": {
                "doctor_name": "ماهر محمود",
                "date_text": "بكرة",
            },
        },
    },

    # ========================================================
    # C. Clear operation switch despite active context
    # ========================================================

    {
        "name": "cancel_to_search",
        "message": "سيب الإلغاء، وريني حجوزاتي",
        "expected_status": "selected",
        "expected_capability": "appointment.search",
        "expected_arguments": {},
        "context": {
            "active_capability": "appointment.cancel",
            "stage": "awaiting_confirmation",
        },
    },

    {
        "name": "cancel_to_reschedule",
        "message": "متلغهوش، خليه الأحد بدل كده",
        "expected_status": "selected",
        "expected_capability": "appointment.reschedule",
        "expected_arguments": {
            "date_text": "الأحد",
        },
        "context": {
            "active_capability": "appointment.cancel",
            "stage": "awaiting_confirmation",
        },
    },

    {
        "name": "policy_to_booking",
        "message": "خلاص فهمت، احجزلي بقى",
        "expected_status": "selected",
        "expected_capability": "appointment.create",
        "expected_arguments": {},
        "context": {
            "active_capability": "provider.get_policy",
            "stage": "answering_policy",
        },
    },

    {
        "name": "slots_to_booking",
        "message": "تمام احجز الساعة خمسة",
        "expected_status": "selected",
        "expected_capability": "appointment.create",
        "expected_arguments": {
            "time_text": "الساعة خمسة",
        },
        "context": {
            "active_capability": "provider.get_slots",
            "stage": "showing_slots",
            "offered_times": [
                "الساعة خمسة",
                "الساعة ستة",
            ],
        },
    },
]


def normalize_text(
    value: str,
) -> str:

    return " ".join(
        value.strip().split()
    )


def arguments_match(
    actual: dict[str, str],
    expected: dict[str, str],
) -> bool:

    if set(actual.keys()) != set(
        expected.keys()
    ):
        return False

    for key, expected_value in (
        expected.items()
    ):

        actual_value = actual.get(key)

        if actual_value is None:
            return False

        if (
            normalize_text(
                actual_value
            )
            != normalize_text(
                expected_value
            )
        ):
            return False

    return True


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


async def main() -> None:

    load_dotenv(
        override=False
    )

    model_name = (
        os.getenv(
            "TOOL_PLANNER_MODEL"
        )
        or os.getenv(
            "OPENAI_MODEL"
        )
        or "gpt-4.1"
    )

    print(
        "Planner model:",
        model_name,
    )

    print(
        "Retriever Top-K:",
        TOP_K,
    )

    router = (
        SemanticCapabilityRouter()
    )

    model = ChatOpenAI(
        model=model_name,
        temperature=0,
        timeout=30,
    )

    planner = ToolPlanner(
        model=model
    )

    status_correct = 0
    capability_correct = 0
    arguments_correct = 0
    full_correct = 0

    total_latencies: list[
        float
    ] = []

    for case in TEST_CASES:

        message = case[
            "message"
        ]

        context = case[
            "context"
        ]

        expected_status = case[
            "expected_status"
        ]

        expected_capability = case[
            "expected_capability"
        ]

        expected_arguments = case[
            "expected_arguments"
        ]

        started = (
            time.perf_counter()
        )

        candidates = (
            select_capability_candidates(
                router=router,
                message=message,
                context=context,
                top_k=TOP_K,
            )
        )

        result = await planner.plan(
            message=message,
            candidates=candidates,
            context=context,
        )

        total_ms = (
            time.perf_counter()
            - started
        ) * 1000

        total_latencies.append(
            total_ms
        )

        status_ok = (
            result.status
            == expected_status
        )

        capability_ok = (
            result.capability
            == expected_capability
        )

        args_ok = (
            arguments_match(
                result.arguments,
                expected_arguments,
            )
        )

        full_ok = (
            status_ok
            and capability_ok
            and args_ok
        )

        if status_ok:
            status_correct += 1

        if capability_ok:
            capability_correct += 1

        if args_ok:
            arguments_correct += 1

        if full_ok:
            full_correct += 1

        print()
        print("=" * 80)

        print(
            "CASE:",
            case["name"],
        )

        print(
            "USER:",
            message,
        )

        print(
            "ACTIVE CAPABILITY:",
            context.get(
                "active_capability"
            ),
        )

        print(
            "CANDIDATES:",
            [
                candidate.name
                for candidate
                in candidates
            ],
        )

        print(
            "EXPECTED STATUS:",
            expected_status,
        )

        print(
            "PLANNER STATUS:",
            result.status,
        )

        print(
            "EXPECTED CAPABILITY:",
            expected_capability,
        )

        print(
            "PLANNER CAPABILITY:",
            result.capability,
        )

        print(
            "EXPECTED ARGS:",
            expected_arguments,
        )

        print(
            "PLANNER ARGS:",
            result.arguments,
        )

        print(
            "REASON:",
            result.reason,
        )

        print(
            "STATUS:",
            (
                "PASS"
                if status_ok
                else "FAIL"
            ),
        )

        print(
            "CAPABILITY:",
            (
                "PASS"
                if capability_ok
                else "FAIL"
            ),
        )

        print(
            "ARGUMENTS:",
            (
                "PASS"
                if args_ok
                else "FAIL"
            ),
        )

        print(
            "FULL RESULT:",
            (
                "PASS"
                if full_ok
                else "FAIL"
            ),
        )

        print(
            f"TOTAL LATENCY: "
            f"{total_ms:.2f} ms"
        )

    total_cases = len(
        TEST_CASES
    )

    print()
    print("=" * 80)
    print(
        "FINAL AMBIGUITY RESULTS"
    )
    print("=" * 80)

    print(
        f"Cases: {total_cases}"
    )

    print(
        "Status accuracy: "
        f"{status_correct / total_cases:.2%}"
    )

    print(
        "Capability accuracy: "
        f"{capability_correct / total_cases:.2%}"
    )

    print(
        "Argument accuracy: "
        f"{arguments_correct / total_cases:.2%}"
    )

    print(
        "Full accuracy: "
        f"{full_correct / total_cases:.2%}"
    )

    print()

    print(
        "TOTAL LATENCY P50: "
        f"{percentile(total_latencies, 50):.2f} ms"
    )

    print(
        "TOTAL LATENCY P95: "
        f"{percentile(total_latencies, 95):.2f} ms"
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )