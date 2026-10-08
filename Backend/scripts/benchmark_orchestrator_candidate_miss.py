from __future__ import annotations

import asyncio
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
from agent.medmind.understanding.orchestrator import (
    UnderstandingOrchestrator,
)
from agent.medmind.understanding.tool_planner import (
    ToolPlanner,
)


# Intentionally small.
#
# We WANT the semantic shortlist to miss the correct
# capability so we can test:
#
# candidate_miss
#     ↓
# broad retry
#     ↓
# selected
TOP_K = 1


TEST_CASES = [

    {
        "name": "cancel_to_search_candidate_miss",

        "message":
            "سيب الإلغاء، وريني حجوزاتي",

        "context": {
            "active_capability":
                "appointment.cancel",

            "stage":
                "awaiting_confirmation",
        },

        "expected_capability":
            "appointment.search",

        "expected_arguments": {},
    },

    {
        "name": "cancel_to_reschedule_candidate_miss",

        "message":
            "متلغهوش، خليه الأحد بدل كده",

        "context": {
            "active_capability":
                "appointment.cancel",

            "stage":
                "awaiting_confirmation",
        },

        "expected_capability":
            "appointment.reschedule",

        "expected_arguments": {
            "date_text": "الأحد",
        },
    },

    {
        "name": "policy_to_create_candidate_miss",

        "message":
            "خلاص فهمت، احجزلي بقى",

        "context": {
            "active_capability":
                "provider.get_policy",

            "stage":
                "answering_policy",
        },

        "expected_capability":
            "appointment.create",

        "expected_arguments": {},
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

        actual_value = actual.get(
            key
        )

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
        "Forced Retriever Top-K:",
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

    total_cases = len(
        TEST_CASES
    )

    full_correct = 0

    for case in TEST_CASES:

        message = case[
            "message"
        ]

        context = case[
            "context"
        ]

        expected_capability = case[
            "expected_capability"
        ]

        expected_arguments = case[
            "expected_arguments"
        ]

        # ====================================================
        # Inspect the INITIAL shortlist.
        #
        # The test is valid only if the correct capability
        # is NOT present before broad retry.
        # ====================================================

        initial_candidates = (
            select_capability_candidates(
                router=router,
                message=message,
                context=context,
                top_k=TOP_K,
            )
        )

        initial_names = [
            candidate.name
            for candidate
            in initial_candidates
        ]

        initial_miss_ok = (
            expected_capability
            not in initial_names
        )

        started = (
            time.perf_counter()
        )

        result = (
            await orchestrator.understand(
                message=message,
                context=context,
            )
        )

        latency_ms = (
            time.perf_counter()
            - started
        ) * 1000

        status_ok = (
            result.status
            == "selected"
        )

        capability_ok = (
            result.capability
            == expected_capability
        )

        arguments_ok = (
            arguments_match(
                result.arguments,
                expected_arguments,
            )
        )

        attempts_ok = (
            result.attempts
            == 2
        )

        broad_ok = (
            result.used_broad_candidates
            is True
        )

        ambiguity_ok = (
            result.ambiguity_kind
            is None
        )

        full_ok = (
            initial_miss_ok
            and status_ok
            and capability_ok
            and arguments_ok
            and attempts_ok
            and broad_ok
            and ambiguity_ok
        )

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
            "INITIAL CANDIDATES:",
            initial_names,
        )

        print(
            "EXPECTED CAPABILITY:",
            expected_capability,
        )

        print(
            "INITIAL MISS:",
            (
                "PASS"
                if initial_miss_ok
                else "FAIL"
            ),
        )

        print(
            "RESULT STATUS:",
            result.status,
        )

        print(
            "RESULT CAPABILITY:",
            result.capability,
        )

        print(
            "RESULT ARGS:",
            result.arguments,
        )

        print(
            "RESULT AMBIGUITY KIND:",
            result.ambiguity_kind,
        )

        print(
            "RESULT ATTEMPTS:",
            result.attempts,
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

    print()
    print("=" * 80)
    print(
        "FINAL CANDIDATE MISS RESULTS"
    )
    print("=" * 80)

    print(
        f"Cases: {total_cases}"
    )

    print(
        "Full accuracy: "
        f"{full_correct / total_cases:.2%}"
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )