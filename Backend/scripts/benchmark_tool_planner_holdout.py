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

    {
        "name": "holdout_doctor_reference",
        "message": "طب خلينا في منى",
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
        "name": "holdout_first_reference",
        "message": "ماشي اللي قولته الأول",
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
        "name": "holdout_date_change",
        "message": "بدل بكرة خليه الأحد",
        "expected_capability": "appointment.create",
        "expected_arguments": {
            "date_text": "الأحد",
        },
        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_confirmation",
            "collected_arguments": {
                "doctor_name": "ماهر محمود",
                "date_text": "بكرة",
                "time_text": "خمسة",
            },
            "pending_confirmation": True,
        },
    },

    {
        "name": "holdout_time_change",
        "message": (
            "الدكتور واليوم تمام "
            "بس عايزه سبعة ونص"
        ),
        "expected_capability": "appointment.create",
        "expected_arguments": {
            "time_text": "سبعة ونص",
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

    {
        "name": "holdout_create_to_policy",
        "message": (
            "قبل ما أحجز، "
            "لو اتأخرت بيحصل إيه؟"
        ),
        "expected_capability": "provider.get_policy",
        "expected_arguments": {
            "query": "لو اتأخرت بيحصل إيه؟",
        },
        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_date",
        },
    },

    {
        "name": "holdout_policy_to_create",
        "message": (
            "تمام فهمت، "
            "احجزلي بقى مع ماهر"
        ),
        "expected_capability": "appointment.create",
        "expected_arguments": {
            "doctor_name": "ماهر",
        },
        "context": {
            "active_capability": "provider.get_policy",
            "stage": "answering_policy",
        },
    },

    {
        "name": "holdout_cancel_to_search",
        "message": (
            "استنى قبل ما ألغيه، "
            "وريني حجوزاتي الأول"
        ),
        "expected_capability": "appointment.search",
        "expected_arguments": {},
        "context": {
            "active_capability": "appointment.cancel",
            "stage": "awaiting_confirmation",
        },
    },

    {
        "name": "holdout_slots_to_create",
        "message": (
            "الساعة ستة مناسبة، "
            "احجزها"
        ),
        "expected_capability": "appointment.create",
        "expected_arguments": {
            "time_text": "الساعة ستة",
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

    {
        "name": "holdout_existing_reschedule",
        "message": (
            "الحجز اللي عندي يوم الخميس "
            "انقله للأحد"
        ),
        "expected_capability": "appointment.reschedule",
        "expected_arguments": {
            "date_text": "الأحد",
        },
        "context": {},
    },

    {
        "name": "holdout_existing_cancel",
        "message": (
            "مش هقدر أروح الحجز ده، "
            "الغيه"
        ),
        "expected_capability": "appointment.cancel",
        "expected_arguments": {},
        "context": {},
    },

    {
        "name": "holdout_information_not_action",
        "message": (
            "هو ينفع أغير الدكتور "
            "بعد الحجز؟"
        ),
        "expected_capability": "provider.get_policy",
        "expected_arguments": {
            "query":
                "ينفع أغير الدكتور بعد الحجز؟",
        },
        "context": {},
    },

    {
        "name": "holdout_availability",
        "message": (
            "في وقت فاضي لدكتور ماهر "
            "بالليل؟"
        ),
        "expected_capability": "provider.get_slots",
        "expected_arguments": {
            "doctor_name": "ماهر",
            "time_text": "بالليل",
        },
        "context": {},
    },

    {
        "name": "holdout_mixed_date",
        "message": (
            "خلي الـ appointment "
            "next Sunday"
        ),
        "expected_capability": "appointment.create",
        "expected_arguments": {
            "date_text": "next Sunday",
        },
        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_date",
        },
    },

    {
        "name": "holdout_english_doctor_change",
        "message": "actually go with Mona",
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
        "name": "holdout_english_operation_switch",
        "message": (
            "don't cancel it, "
            "move it to Sunday"
        ),
        "expected_capability": "appointment.reschedule",
        "expected_arguments": {
            "date_text": "Sunday",
        },
        "context": {
            "active_capability": "appointment.cancel",
            "stage": "awaiting_confirmation",
        },
    },
]


def percentile(
    values: list[float],
    percentile_value: float,
) -> float:

    if not values:
        return 0.0

    sorted_values = sorted(values)

    if len(sorted_values) == 1:
        return sorted_values[0]

    position = (
        percentile_value / 100.0
    ) * (len(sorted_values) - 1)

    lower_index = math.floor(position)
    upper_index = math.ceil(position)

    if lower_index == upper_index:
        return sorted_values[lower_index]

    lower_value = sorted_values[lower_index]
    upper_value = sorted_values[upper_index]

    fraction = position - lower_index

    return (
        lower_value
        + (upper_value - lower_value)
        * fraction
    )


def arguments_match(
    actual: dict[str, str],
    expected: dict[str, str],
) -> bool:

    def normalize_text(value: str) -> str:

        value = (
            value
            .replace("؟", "")
            .replace("?", "")
            .replace(",", "")
            .replace("،", "")
        )

        return " ".join(
            value.strip().split()
        )

    def query_match(
        actual_value: str,
        expected_value: str,
    ) -> bool:

        actual_normalized = normalize_text(
            actual_value
        )

        expected_normalized = normalize_text(
            expected_value
        )

        if (
            actual_normalized in expected_normalized
            or expected_normalized in actual_normalized
        ):
            return True

        stop_words = {
            "هو",
            "هي",
            "إيه",
            "ايه",
            "هل",
            "ينفع",
            "ممكن",
            "عايز",
            "عاوز",
            "انا",
            "أنا",
        }

        actual_tokens = {
            token
            for token in actual_normalized.split()
            if token not in stop_words
        }

        expected_tokens = {
            token
            for token in expected_normalized.split()
            if token not in stop_words
        }

        if not actual_tokens or not expected_tokens:
            return False

        common_tokens = (
            actual_tokens
            & expected_tokens
        )

        coverage = (
            len(common_tokens)
            / min(
                len(actual_tokens),
                len(expected_tokens),
            )
        )

        return coverage >= 0.60

    if set(actual.keys()) != set(
        expected.keys()
    ):
        return False

    for key, expected_value in expected.items():

        actual_value = actual.get(key)

        if actual_value is None:
            return False

        if key == "query":

            if not query_match(
                actual_value,
                expected_value,
            ):
                return False

            continue

        if (
            normalize_text(actual_value)
            != normalize_text(expected_value)
        ):
            return False

    return True


async def main() -> None:

    load_dotenv(
        override=False
    )

    model_name = (
        os.getenv("TOOL_PLANNER_MODEL")
        or os.getenv("OPENAI_MODEL")
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

    router = SemanticCapabilityRouter()

    model = ChatOpenAI(
        model=model_name,
        temperature=0,
        timeout=30,
    )

    planner = ToolPlanner(
        model=model
    )

    capability_correct = 0
    arguments_correct = 0
    full_correct = 0
    context_injections = 0

    router_latencies: list[float] = []
    planner_latencies: list[float] = []
    total_latencies: list[float] = []

    for case in TEST_CASES:

        name = case["name"]
        message = case["message"]
        expected_capability = case[
            "expected_capability"
        ]
        expected_arguments = case[
            "expected_arguments"
        ]
        context = case["context"]

        router_started = time.perf_counter()

        candidates = (
            select_capability_candidates(
                router=router,
                message=message,
                context=context,
                top_k=TOP_K,
            )
        )

        router_ms = (
            time.perf_counter()
            - router_started
        ) * 1000

        router_latencies.append(
            router_ms
        )

        candidate_names = [
            candidate.name
            for candidate in candidates
        ]

        context_injected = any(
            candidate.matched_text
            == "active_capability_from_context"
            for candidate in candidates
        )

        if context_injected:
            context_injections += 1

        planner_started = time.perf_counter()

        result = await planner.plan(
            message=message,
            candidates=candidates,
            context=context,
        )

        planner_ms = (
            time.perf_counter()
            - planner_started
        ) * 1000

        planner_latencies.append(
            planner_ms
        )

        total_ms = (
            router_ms
            + planner_ms
        )

        total_latencies.append(
            total_ms
        )

        capability_ok = (
            result.status == "selected"
            and result.capability
            == expected_capability
        )

        args_ok = arguments_match(
            result.arguments,
            expected_arguments,
        )

        full_ok = (
            capability_ok
            and args_ok
        )

        if capability_ok:
            capability_correct += 1

        if args_ok:
            arguments_correct += 1

        if full_ok:
            full_correct += 1

        print()
        print("=" * 80)

        print("CASE:", name)
        print("USER:", message)

        print(
            "ACTIVE CAPABILITY:",
            context.get(
                "active_capability"
            ),
        )

        print(
            "STAGE:",
            context.get("stage"),
        )

        print(
            "CANDIDATES:",
            candidate_names,
        )

        print(
            "CONTEXT CAPABILITY INJECTED:",
            context_injected,
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
            "STATUS:",
            result.status,
        )

        print(
            "REASON:",
            result.reason,
        )

        print(
            "CAPABILITY:",
            "PASS" if capability_ok else "FAIL",
        )

        print(
            "ARGUMENTS:",
            "PASS" if args_ok else "FAIL",
        )

        print(
            "FULL RESULT:",
            "PASS" if full_ok else "FAIL",
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
            f"TOTAL LATENCY: "
            f"{total_ms:.2f} ms"
        )

    total_cases = len(
        TEST_CASES
    )

    capability_accuracy = (
        capability_correct
        / total_cases
    )

    argument_accuracy = (
        arguments_correct
        / total_cases
    )

    full_accuracy = (
        full_correct
        / total_cases
    )

    print()
    print("=" * 80)
    print("FINAL HOLDOUT RESULTS")
    print("=" * 80)

    print(
        f"Cases: {total_cases}"
    )

    print(
        "Capability accuracy: "
        f"{capability_accuracy:.2%}"
    )

    print(
        "Argument accuracy: "
        f"{argument_accuracy:.2%}"
    )

    print(
        "Full contextual accuracy: "
        f"{full_accuracy:.2%}"
    )

    print(
        "Context capability injections: "
        f"{context_injections}"
    )

    print()

    print("ROUTER LATENCY")

    print(
        "P50: "
        f"{percentile(router_latencies, 50):.2f} ms"
    )

    print(
        "P95: "
        f"{percentile(router_latencies, 95):.2f} ms"
    )

    print()

    print("PLANNER LATENCY")

    print(
        "P50: "
        f"{percentile(planner_latencies, 50):.2f} ms"
    )

    print(
        "P95: "
        f"{percentile(planner_latencies, 95):.2f} ms"
    )

    print()

    print(
        "TOTAL UNDERSTANDING LATENCY"
    )

    print(
        "P50: "
        f"{percentile(total_latencies, 50):.2f} ms"
    )

    print(
        "P95: "
        f"{percentile(total_latencies, 95):.2f} ms"
    )


if __name__ == "__main__":
    asyncio.run(
        main()
    )