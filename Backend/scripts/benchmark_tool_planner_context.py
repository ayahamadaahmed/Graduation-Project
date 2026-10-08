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
        "name": "doctor_selection_by_name",
        "message": "أيوه مع ماهر",
        "expected_capability": "appointment.create",
        "expected_arguments": {
            "doctor_name": "ماهر محمود",
        },
        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_doctor",
            "collected_arguments": {
                "specialty_name": "جلدية",
            },
            "missing_arguments": [
                "doctor_name",
                "date_text",
                "time_text",
            ],
            "offered_doctors": [
                "ماهر محمود",
                "منى صلاح",
            ],
        },
    },

    {
        "name": "doctor_selection_by_reference",
        "message": "لا التانية",
        "expected_capability": "appointment.create",
        "expected_arguments": {
            "doctor_name": "منى صلاح",
        },
        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_doctor",
            "collected_arguments": {
                "specialty_name": "جلدية",
            },
            "offered_doctors": [
                "ماهر محمود",
                "منى صلاح",
            ],
        },
    },

    {
        "name": "short_date_reply",
        "message": "خليه بكرة",
        "expected_capability": "appointment.create",
        "expected_arguments": {
            "date_text": "بكرة",
        },
        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_date",
            "collected_arguments": {
                "specialty_name": "جلدية",
                "doctor_name": "ماهر محمود",
            },
            "missing_arguments": [
                "date_text",
                "time_text",
            ],
        },
    },

    {
        "name": "time_correction",
        "message": "لا الساعة سبعة",
        "expected_capability": "appointment.create",
        "expected_arguments": {
            "time_text": "الساعة سبعة",
        },
        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_time",
            "collected_arguments": {
                "specialty_name": "جلدية",
                "doctor_name": "ماهر محمود",
                "date_text": "بكرة",
            },
            "missing_arguments": [
                "time_text",
            ],
        },
    },

    {
        "name": "doctor_correction",
        "message": "قصدي دكتورة منى",
        "expected_capability": "appointment.create",
        "expected_arguments": {
            "doctor_name": "منى صلاح",
        },
        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_confirmation",
            "collected_arguments": {
                "specialty_name": "جلدية",
                "doctor_name": "ماهر محمود",
                "date_text": "الخميس",
                "time_text": "خمسة",
            },
            "offered_doctors": [
                "ماهر محمود",
                "منى صلاح",
            ],
            "pending_confirmation": True,
        },
    },

    {
        "name": "cancel_to_reschedule",
        "message": (
            "لا مش عايز ألغي، "
            "عايز أغيره للسبت"
        ),
        "expected_capability": "appointment.reschedule",
        "expected_arguments": {
            "date_text": "السبت",
        },
        "context": {
            "active_capability": "appointment.cancel",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,
        },
    },

    {
        "name": "doctor_reference_first_one",
        "message": "خلاص الأول",
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
        "name": "doctor_reference_other_one",
        "message": "لا خليه مع التاني",
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
        "name": "date_correction",
        "message": "لا مش الخميس، السبت",
        "expected_capability": "appointment.create",
        "expected_arguments": {
            "date_text": "السبت",
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
        "name": "time_correction_confirmation",
        "message": "كل حاجة صح بس الساعة خليها ستة",
        "expected_capability": "appointment.create",
        "expected_arguments": {
            "time_text": "ستة",
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
        "name": "create_to_slots",
        "message": "لا أنا بس عايز أعرف المواعيد المتاحة",
        "expected_capability": "provider.get_slots",
        "expected_arguments": {},
        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_date",
        },
    },

    {
        "name": "reschedule_to_policy",
        "message": "استنى، أنا بس بسأل إيه قواعد التغيير",
        "expected_capability": "provider.get_policy",
        "expected_arguments": {
            "query": "إيه قواعد التغيير",
        },
        "context": {
            "active_capability": "appointment.reschedule",
            "stage": "awaiting_confirmation",
        },
    },

    {
        "name": "cancel_correction",
        "message": "قصدي الحجز التاني مش ده",
        "expected_capability": "appointment.cancel",
        "expected_arguments": {},
        "context": {
            "active_capability": "appointment.cancel",
            "stage": "awaiting_confirmation",
        },
    },

    {
        "name": "mixed_language_time",
        "message": "لا خليها at seven",
        "expected_capability": "appointment.create",
        "expected_arguments": {
            "time_text": "at seven",
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
        "name": "english_context_date",
        "message": "make it tomorrow instead",
        "expected_capability": "appointment.create",
        "expected_arguments": {
            "date_text": "tomorrow",
        },
        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_confirmation",
            "collected_arguments": {
                "doctor_name": "ماهر محمود",
                "date_text": "Thursday",
                "time_text": "5 PM",
            },
            "pending_confirmation": True,
        },
    },

    {
        "name": "policy_to_action",
        "message": "تمام خلاص غيره للسبت",
        "expected_capability": "appointment.reschedule",
        "expected_arguments": {
            "date_text": "السبت",
        },
        "context": {
            "active_capability": "provider.get_policy",
            "stage": "answering_policy",
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
    print("FINAL CONTEXT RESULTS")
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