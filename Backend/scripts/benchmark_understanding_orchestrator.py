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
from agent.medmind.understanding.orchestrator import (
    UnderstandingOrchestrator,
)
from agent.medmind.understanding.tool_planner import (
    ToolPlanner,
)


TOP_K = 8


TEST_CASES = [

    # ========================================================
    # A. Clear request
    #
    # Should finish on the first planner attempt.
    # ========================================================

    {
        "name": "clear_create",
        "message": "عايز أحجز مع دكتور ماهر بكرة",
        "context": {},

        "expected_status": "selected",
        "expected_capability": "appointment.create",

        "expected_arguments": {
            "doctor_name": "ماهر",
            "date_text": "بكرة",
        },

        "expected_ambiguity_kind": None,
        "expected_attempts": 1,
        "expected_broad": False,
    },

    # ========================================================
    # B. Context resolves short reference
    # ========================================================

    {
        "name": "context_doctor_reference",
        "message": "التانية",

        "context": {
            "active_capability":
                "appointment.create",

            "stage":
                "awaiting_doctor",

            "offered_doctors": [
                "ماهر محمود",
                "منى صلاح",
            ],
        },

        "expected_status": "selected",
        "expected_capability":
            "appointment.create",

        "expected_arguments": {
            "doctor_name": "منى صلاح",
        },

        "expected_ambiguity_kind": None,
        "expected_attempts": 1,
        "expected_broad": False,
    },

    # ========================================================
    # C. Explicit operation switching
    # ========================================================

    {
        "name": "cancel_to_reschedule",
        "message": (
            "متلغهوش، "
            "خليه الأحد بدل كده"
        ),

        "context": {
            "active_capability":
                "appointment.cancel",

            "stage":
                "awaiting_confirmation",
        },

        "expected_status": "selected",
        "expected_capability":
            "appointment.reschedule",

        "expected_arguments": {
            "date_text": "الأحد",
        },

        "expected_ambiguity_kind": None,
        "expected_attempts": 1,
        "expected_broad": False,
    },

    # ========================================================
    # D. Genuine ambiguity
    #
    # The planner should classify these as:
    #
    # ambiguity_kind = needs_clarification
    #
    # The orchestrator must STOP after attempt 1.
    #
    # No broad retry.
    # ========================================================

    {
        "name": "ambiguous_change",
        "message": "عايز أغيره",

        "context": {},

        "expected_status": "ambiguous",
        "expected_capability": None,
        "expected_arguments": {},

        "expected_ambiguity_kind":
            "needs_clarification",

        "expected_attempts": 1,
        "expected_broad": False,
    },

    {
        "name": "ambiguous_reference",
        "message": "التاني",

        "context": {},

        "expected_status": "ambiguous",
        "expected_capability": None,
        "expected_arguments": {},

        "expected_ambiguity_kind":
            "needs_clarification",

        "expected_attempts": 1,
        "expected_broad": False,
    },

    {
        "name": "ambiguous_generic_help",
        "message": "ممكن تساعدني في الحجز؟",

        "context": {},

        "expected_status": "ambiguous",
        "expected_capability": None,
        "expected_arguments": {},

        "expected_ambiguity_kind":
            "needs_clarification",

        "expected_attempts": 1,
        "expected_broad": False,
    },

    # ========================================================
    # E. Empty message
    #
    # No router.
    # No planner.
    # ========================================================

    {
        "name": "empty_message",
        "message": "   ",

        "context": {},

        "expected_status": "ambiguous",
        "expected_capability": None,
        "expected_arguments": {},

        "expected_ambiguity_kind":
            "needs_clarification",

        "expected_attempts": 0,
        "expected_broad": False,
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

    orchestrator = (
        UnderstandingOrchestrator(
            router=router,
            planner=planner,
            top_k=TOP_K,
        )
    )

    status_correct = 0
    capability_correct = 0
    arguments_correct = 0
    ambiguity_kind_correct = 0
    attempts_correct = 0
    broad_correct = 0
    full_correct = 0

    latencies: list[float] = []

    for case in TEST_CASES:

        started = (
            time.perf_counter()
        )

        result = (
            await orchestrator.understand(
                message=case["message"],
                context=case["context"],
            )
        )

        latency_ms = (
            time.perf_counter()
            - started
        ) * 1000

        latencies.append(
            latency_ms
        )

        status_ok = (
            result.status
            == case[
                "expected_status"
            ]
        )

        capability_ok = (
            result.capability
            == case[
                "expected_capability"
            ]
        )

        arguments_ok = (
            arguments_match(
                result.arguments,
                case[
                    "expected_arguments"
                ],
            )
        )

        ambiguity_kind_ok = (
            result.ambiguity_kind
            == case[
                "expected_ambiguity_kind"
            ]
        )

        attempts_ok = (
            result.attempts
            == case[
                "expected_attempts"
            ]
        )

        broad_ok = (
            result.used_broad_candidates
            == case[
                "expected_broad"
            ]
        )

        full_ok = (
            status_ok
            and capability_ok
            and arguments_ok
            and ambiguity_kind_ok
            and attempts_ok
            and broad_ok
        )

        if status_ok:
            status_correct += 1

        if capability_ok:
            capability_correct += 1

        if arguments_ok:
            arguments_correct += 1

        if ambiguity_kind_ok:
            ambiguity_kind_correct += 1

        if attempts_ok:
            attempts_correct += 1

        if broad_ok:
            broad_correct += 1

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
            repr(
                case["message"]
            ),
        )

        print(
            "EXPECTED STATUS:",
            case[
                "expected_status"
            ],
        )

        print(
            "RESULT STATUS:",
            result.status,
        )

        print(
            "EXPECTED CAPABILITY:",
            case[
                "expected_capability"
            ],
        )

        print(
            "RESULT CAPABILITY:",
            result.capability,
        )

        print(
            "EXPECTED ARGS:",
            case[
                "expected_arguments"
            ],
        )

        print(
            "RESULT ARGS:",
            result.arguments,
        )

        print(
            "EXPECTED AMBIGUITY KIND:",
            case[
                "expected_ambiguity_kind"
            ],
        )

        print(
            "RESULT AMBIGUITY KIND:",
            result.ambiguity_kind,
        )

        print(
            "EXPECTED ATTEMPTS:",
            case[
                "expected_attempts"
            ],
        )

        print(
            "RESULT ATTEMPTS:",
            result.attempts,
        )

        print(
            "EXPECTED BROAD:",
            case[
                "expected_broad"
            ],
        )

        print(
            "RESULT BROAD:",
            result.used_broad_candidates,
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
                if arguments_ok
                else "FAIL"
            ),
        )

        print(
            "AMBIGUITY KIND:",
            (
                "PASS"
                if ambiguity_kind_ok
                else "FAIL"
            ),
        )

        print(
            "ATTEMPTS:",
            (
                "PASS"
                if attempts_ok
                else "FAIL"
            ),
        )

        print(
            "BROAD RETRY:",
            (
                "PASS"
                if broad_ok
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
            f"LATENCY: "
            f"{latency_ms:.2f} ms"
        )

    total_cases = len(
        TEST_CASES
    )

    print()
    print("=" * 80)

    print(
        "FINAL ORCHESTRATOR RESULTS"
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
        "Ambiguity kind accuracy: "
        f"{ambiguity_kind_correct / total_cases:.2%}"
    )

    print(
        "Attempts accuracy: "
        f"{attempts_correct / total_cases:.2%}"
    )

    print(
        "Broad retry accuracy: "
        f"{broad_correct / total_cases:.2%}"
    )

    print(
        "Full accuracy: "
        f"{full_correct / total_cases:.2%}"
    )

    print()

    print(
        "TOTAL LATENCY P50: "
        f"{percentile(latencies, 50):.2f} ms"
    )

    print(
        "TOTAL LATENCY P95: "
        f"{percentile(latencies, 95):.2f} ms"
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )