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
    # A. New genuine ambiguity cases
    # ========================================================

    {
        "name": "holdout_ambiguous_change_reference",
        "message": "طب غيرها",
        "expected_status": "ambiguous",
        "expected_capability": None,
        "expected_arguments": {},
        "context": {},
    },

    {
        "name": "holdout_ambiguous_next_reference",
        "message": "اللي بعدها",
        "expected_status": "ambiguous",
        "expected_capability": None,
        "expected_arguments": {},
        "context": {},
    },

    {
        "name": "holdout_ambiguous_appointment_help_en",
        "message": "I need help with my appointment",
        "expected_status": "ambiguous",
        "expected_capability": None,
        "expected_arguments": {},
        "context": {},
    },

    {
        "name": "holdout_ambiguous_rejection",
        "message": "مش ده",
        "expected_status": "ambiguous",
        "expected_capability": None,
        "expected_arguments": {},
        "context": {},
    },

    {
        "name": "holdout_ambiguous_change_en",
        "message": "can you change it?",
        "expected_status": "ambiguous",
        "expected_capability": None,
        "expected_arguments": {},
        "context": {},
    },

    # ========================================================
    # B. Context resolves vague language
    # ========================================================

    {
        "name": "holdout_context_first_doctor",
        "message": "الأولى",
        "expected_status": "selected",
        "expected_capability": "appointment.create",
        "expected_arguments": {
            "doctor_name": "ماهر محمود",
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
        "name": "holdout_context_time_period",
        "message": "خليها بالليل",
        "expected_status": "selected",
        "expected_capability": "appointment.create",
        "expected_arguments": {
            "time_text": "بالليل",
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

    {
        "name": "holdout_context_date_correction",
        "message": "مش الخميس، الأحد",
        "expected_status": "selected",
        "expected_capability": "appointment.create",
        "expected_arguments": {
            "date_text": "الأحد",
        },
        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_confirmation",
            "collected_arguments": {
                "doctor_name": "ماهر محمود",
                "date_text": "الخميس",
                "time_text": "خمسة",
            },
            "pending_confirmation": True,
        },
    },

    # ========================================================
    # C. Explicit operation changes
    # ========================================================

    {
        "name": "holdout_create_to_search",
        "message": "استنى، وريني حجوزاتي الأول",
        "expected_status": "selected",
        "expected_capability": "appointment.search",
        "expected_arguments": {},
        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_date",
        },
    },

    {
        "name": "holdout_policy_to_cancel",
        "message": "تمام فهمت، الغي الحجز بقى",
        "expected_status": "selected",
        "expected_capability": "appointment.cancel",
        "expected_arguments": {},
        "context": {
            "active_capability": "provider.get_policy",
            "stage": "answering_policy",
        },
    },

    {
        "name": "holdout_cancel_to_slots",
        "message": "سيب الإلغاء، دكتور ماهر فاضي امتى؟",
        "expected_status": "selected",
        "expected_capability": "provider.get_slots",
        "expected_arguments": {
            "doctor_name": "ماهر",
        },
        "context": {
            "active_capability": "appointment.cancel",
            "stage": "awaiting_confirmation",
        },
    },

    {
        "name": "holdout_cancel_to_reschedule_en",
        "message": "keep it, just move it to Monday",
        "expected_status": "selected",
        "expected_capability": "appointment.reschedule",
        "expected_arguments": {
            "date_text": "Monday",
        },
        "context": {
            "active_capability": "appointment.cancel",
            "stage": "awaiting_confirmation",
        },
    },
]


def normalize_text(
    value: str,
) -> str:

    return " ".join(
        value.strip().split()
    )


def normalize_doctor_name(
    value: str,
) -> str:

    value = normalize_text(
        value
    )

    doctor_titles = (
        "دكتور ",
        "دكتورة ",
        "د. ",
        "Dr. ",
        "Dr ",
        "Doctor ",
    )

    for title in doctor_titles:

        if value.startswith(title):

            value = value[
                len(title):
            ].strip()

            break

    return value


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

        actual_value = actual.get(
            key
        )

        if actual_value is None:
            return False

        if key == "doctor_name":

            actual_normalized = (
                normalize_doctor_name(
                    actual_value
                )
            )

            expected_normalized = (
                normalize_doctor_name(
                    expected_value
                )
            )

        else:

            actual_normalized = (
                normalize_text(
                    actual_value
                )
            )

            expected_normalized = (
                normalize_text(
                    expected_value
                )
            )

        if (
            actual_normalized
            != expected_normalized
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