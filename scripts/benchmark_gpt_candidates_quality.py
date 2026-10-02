from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
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


TOP_K = 8


# ============================================================
# COMPACT CANDIDATE PLANNER
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
# TEST CASE
# ============================================================

@dataclass
class TestCase:
    name: str
    message: str
    expected_capability: str

    context: dict[str, Any] = field(
        default_factory=dict
    )

    expected_arguments: dict[str, Any] = field(
        default_factory=dict
    )

    expected_confirmation: str | None = None


CASES = [

    TestCase(
        name="new_booking",
        message="عايز أحجز كشف جلدية بكرة",
        expected_capability="appointment.create",
    ),

    TestCase(
        name="search_existing_booking",
        message="عايز أعرف تفاصيل حجزي",
        expected_capability="appointment.search",
    ),

    TestCase(
        name="cancel_booking",
        message="عايز ألغي الحجز",
        expected_capability="appointment.cancel",
    ),

    TestCase(
        name="reschedule_booking",
        message="عايز أغير ميعاد الحجز",
        expected_capability="appointment.reschedule",
    ),

    TestCase(
        name="search_doctors",
        message="مين دكاترة الجلدية؟",
        expected_capability="provider.search_doctors",
    ),

    TestCase(
        name="get_services",
        message="إيه الخدمات المتاحة؟",
        expected_capability="provider.get_services",
    ),

    TestCase(
        name="get_slots",
        message="في مواعيد بكرة؟",
        expected_capability="provider.get_slots",
    ),

    TestCase(
        name="working_hours",
        message="مواعيد العمل إيه؟",
        expected_capability="provider.get_working_hours",
    ),

    TestCase(
        name="policy",
        message="سياسة إلغاء الحجز إيه؟",
        expected_capability="provider.get_policy",
    ),

    TestCase(
        name="human_support",
        message="عايز أكلم موظف",
        expected_capability="human_support.transfer",
    ),

    # --------------------------------------------------------
    # Contextual correction
    # --------------------------------------------------------

    TestCase(
        name="reschedule_date_correction",
        message="لا خليه الاتنين",
        expected_capability="appointment.reschedule",
        context={
            "active_capability": (
                "appointment.reschedule"
            ),
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,
            "collected_arguments": {
                "date_text": "الأحد",
                "time_text": "الساعة ستة",
            },
        },
        expected_arguments={
            "date_text": "الاتنين",
        },
        expected_confirmation="unknown",
    ),

    # --------------------------------------------------------
    # Explicit operation switch
    # --------------------------------------------------------

    TestCase(
        name="cancel_to_reschedule_switch",
        message="لا متلغهوش، غيره للسبت",
        expected_capability="appointment.reschedule",
        context={
            "active_capability": (
                "appointment.cancel"
            ),
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,
        },
        expected_confirmation="unknown",
    ),
]


# ============================================================
# VALIDATION
# ============================================================

def validate_result(
    *,
    case: TestCase,
    result,
) -> tuple[bool, list[str]]:

    errors: list[str] = []

    if result.status != "selected":
        errors.append(
            f"status={result.status}"
        )

    if (
        result.capability
        != case.expected_capability
    ):
        errors.append(
            (
                "capability="
                f"{result.capability}"
            )
        )

    for key, expected_value in (
        case.expected_arguments.items()
    ):

        actual_value = (
            result.arguments.get(
                key
            )
        )

        if actual_value != expected_value:
            errors.append(
                (
                    f"argument[{key}]="
                    f"{actual_value!r}"
                )
            )

    if (
        case.expected_confirmation
        is not None
        and result.confirmation
        != case.expected_confirmation
    ):
        errors.append(
            (
                "confirmation="
                f"{result.confirmation}"
            )
        )

    return (
        len(errors) == 0,
        errors,
    )


# ============================================================
# RUN PLANNER
# ============================================================

async def run_case(
    *,
    planner: ToolPlanner,
    router: SemanticCapabilityRouter,
    case: TestCase,
):

    candidates = (
        select_capability_candidates(
            router=router,
            message=case.message,
            context=case.context,
            top_k=TOP_K,
        )
    )

    result = await planner.plan(
        message=case.message,
        candidates=candidates,
        context=case.context,
    )

    passed, errors = validate_result(
        case=case,
        result=result,
    )

    return (
        result,
        candidates,
        passed,
        errors,
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
        "Cases:",
        len(CASES),
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

    full_planner = ToolPlanner(
        model=model
    )

    compact_planner = (
        CompactCandidateToolPlanner(
            model=model
        )
    )

    full_passes = 0
    compact_passes = 0

    disagreements = 0

    for index, case in enumerate(
        CASES,
        start=1,
    ):

        print()
        print("=" * 70)
        print(
            f"{index:02d}. {case.name}"
        )
        print("=" * 70)

        print(
            "USER:",
            case.message,
        )

        print(
            "EXPECTED:",
            case.expected_capability,
        )

        # Alternate execution order to reduce
        # provider timing/order bias.

        if index % 2 == 1:

            full_result, candidates, full_ok, full_errors = (
                await run_case(
                    planner=full_planner,
                    router=router,
                    case=case,
                )
            )

            compact_result, _, compact_ok, compact_errors = (
                await run_case(
                    planner=compact_planner,
                    router=router,
                    case=case,
                )
            )

        else:

            compact_result, candidates, compact_ok, compact_errors = (
                await run_case(
                    planner=compact_planner,
                    router=router,
                    case=case,
                )
            )

            full_result, _, full_ok, full_errors = (
                await run_case(
                    planner=full_planner,
                    router=router,
                    case=case,
                )
            )

        if full_ok:
            full_passes += 1

        if compact_ok:
            compact_passes += 1

        same_result = (
            full_result.status
            == compact_result.status
            and full_result.capability
            == compact_result.capability
            and full_result.arguments
            == compact_result.arguments
            and full_result.confirmation
            == compact_result.confirmation
            and full_result.correction_target
            == compact_result.correction_target
        )

        if not same_result:
            disagreements += 1

        print(
            "CANDIDATES:",
            [
                candidate.name
                for candidate in candidates
            ],
        )

        print()

        print(
            "FULL:"
        )

        print(
            "  status:",
            full_result.status,
        )

        print(
            "  capability:",
            full_result.capability,
        )

        print(
            "  arguments:",
            full_result.arguments,
        )

        print(
            "  confirmation:",
            full_result.confirmation,
        )

        print(
            "  correction_target:",
            full_result.correction_target,
        )

        print(
            "  result:",
            "PASS" if full_ok else "FAIL",
        )

        if full_errors:
            print(
                "  errors:",
                full_errors,
            )

        print()

        print(
            "COMPACT:"
        )

        print(
            "  status:",
            compact_result.status,
        )

        print(
            "  capability:",
            compact_result.capability,
        )

        print(
            "  arguments:",
            compact_result.arguments,
        )

        print(
            "  confirmation:",
            compact_result.confirmation,
        )

        print(
            "  correction_target:",
            compact_result.correction_target,
        )

        print(
            "  result:",
            (
                "PASS"
                if compact_ok
                else "FAIL"
            ),
        )

        if compact_errors:
            print(
                "  errors:",
                compact_errors,
            )

        print(
            "SAME OUTPUT:",
            (
                "YES"
                if same_result
                else "NO"
            ),
        )

    # ========================================================
    # SUMMARY
    # ========================================================

    total_cases = len(
        CASES
    )

    full_accuracy = (
        full_passes
        / total_cases
        * 100
    )

    compact_accuracy = (
        compact_passes
        / total_cases
        * 100
    )

    print()
    print("=" * 70)
    print(
        "QUALITY REGRESSION SUMMARY"
    )
    print("=" * 70)

    print(
        f"FULL:"
        f" {full_passes}/{total_cases}"
        f" ({full_accuracy:.2f}%)"
    )

    print(
        f"COMPACT:"
        f" {compact_passes}/{total_cases}"
        f" ({compact_accuracy:.2f}%)"
    )

    print(
        "Output disagreements:",
        disagreements,
    )

    print()

    if (
        compact_passes == total_cases
        and compact_accuracy
        >= full_accuracy
    ):
        print(
            "DECISION: "
            "COMPACT CANDIDATES PASSED "
            "THE INITIAL QUALITY GATE."
        )

    else:
        print(
            "DECISION: "
            "DO NOT MOVE COMPACT "
            "CANDIDATES TO PRODUCTION YET."
        )


if __name__ == "__main__":
    asyncio.run(
        main()
    )