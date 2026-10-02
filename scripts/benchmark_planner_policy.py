from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)

from medmind.understanding.candidate_selector import (
    select_capability_candidates,
)

from medmind.understanding.planner_policy import (
    choose_planner_provider,
)


TOP_K = 8


# ============================================================
# TEST CASE
# ============================================================

@dataclass
class PolicyCase:
    name: str
    message: str
    expected_provider: str

    context: dict[str, Any] = field(
        default_factory=dict
    )

    note: str = ""


# ============================================================
# DATASET
#
# qwen:
# - clear one-operation requests
# - short contextual replies
# - simple corrections
#
# gpt:
# - explicit operation switches
# - multiple operations
# - multiple conditions
# - context conflicts / risky interpretation
# ============================================================

CASES = [

    # --------------------------------------------------------
    # SIMPLE NEW REQUESTS -> QWEN
    # --------------------------------------------------------

    PolicyCase(
        name="simple_new_booking",
        message="عايز أحجز كشف جلدية",
        expected_provider="qwen",
        note="Clear single booking operation.",
    ),

    PolicyCase(
        name="simple_booking_with_date",
        message="عايز أحجز جلدية بكرة",
        expected_provider="qwen",
        note="Still one clear booking operation.",
    ),

    PolicyCase(
        name="simple_cancel",
        message="عايز ألغي الحجز",
        expected_provider="qwen",
        note="Clear single cancel operation.",
    ),

    PolicyCase(
        name="simple_reschedule",
        message="عايز أغير ميعاد الحجز",
        expected_provider="qwen",
        note="Clear single reschedule operation.",
    ),

    PolicyCase(
        name="simple_search_booking",
        message="عايز أعرف تفاصيل حجزي",
        expected_provider="qwen",
        note="Clear lookup request.",
    ),

    PolicyCase(
        name="simple_slots",
        message="في مواعيد بكرة؟",
        expected_provider="qwen",
        note="Simple availability query.",
    ),

    PolicyCase(
        name="simple_doctor_search",
        message="مين دكاترة الجلدية؟",
        expected_provider="qwen",
        note="Simple doctor lookup.",
    ),

    PolicyCase(
        name="simple_working_hours",
        message="مواعيد العمل إيه؟",
        expected_provider="qwen",
        note="Simple provider query.",
    ),

    # --------------------------------------------------------
    # SHORT CONTEXTUAL TURNS -> QWEN
    # --------------------------------------------------------

    PolicyCase(
        name="context_specialty",
        message="جلدية",
        expected_provider="qwen",
        context={
            "active_capability": "appointment.create",
            "stage": "awaiting_specialty",
        },
        note="Short contextual answer.",
    ),

    PolicyCase(
        name="context_doctor",
        message="دكتورة منى",
        expected_provider="qwen",
        context={
            "active_capability": "appointment.create",
            "stage": "awaiting_doctor",
        },
        note="Short contextual answer.",
    ),

    PolicyCase(
        name="context_date",
        message="بكرة",
        expected_provider="qwen",
        context={
            "active_capability": "appointment.create",
            "stage": "awaiting_date",
        },
        note="Short contextual date.",
    ),

    PolicyCase(
        name="context_time",
        message="الساعة خمسة",
        expected_provider="qwen",
        context={
            "active_capability": "appointment.create",
            "stage": "awaiting_time",
        },
        note="Short contextual time.",
    ),

    PolicyCase(
        name="simple_name_correction",
        message="الاسم الصح آية محمد",
        expected_provider="qwen",
        context={
            "active_capability": "appointment.create",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,
        },
        note="Single-field correction.",
    ),

    PolicyCase(
        name="simple_reschedule_date_correction",
        message="لا خليه الاتنين",
        expected_provider="qwen",
        context={
            "active_capability": "appointment.reschedule",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,
            "collected_arguments": {
                "date_text": "الأحد",
                "time_text": "الساعة ستة",
            },
        },
        note=(
            "Single contextual correction. "
            "Should not require GPT by default."
        ),
    ),

    # --------------------------------------------------------
    # COMPLEX / RISKY -> GPT
    # --------------------------------------------------------

    PolicyCase(
        name="cancel_to_reschedule_switch",
        message="لا متلغهوش، غيره للسبت",
        expected_provider="gpt",
        context={
            "active_capability": "appointment.cancel",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,
        },
        note="Explicit operation switch.",
    ),

    PolicyCase(
        name="reschedule_to_cancel_switch",
        message="مش عايز أغيره خلاص الغيه",
        expected_provider="gpt",
        context={
            "active_capability": "appointment.reschedule",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,
        },
        note="Context conflict and operation switch.",
    ),

    PolicyCase(
        name="booking_to_cancel_switch",
        message="مش عايز أحجز خلاص، ألغي الموضوع",
        expected_provider="gpt",
        context={
            "active_capability": "appointment.create",
            "stage": "awaiting_doctor",
        },
        note="Explicit active-operation abandonment.",
    ),

    PolicyCase(
        name="multi_condition_doctor",
        message=(
            "لو دكتورة منى مش متاحة "
            "شوفلي دكتور تاني بعد الساعة ستة"
        ),
        expected_provider="gpt",
        context={
            "active_capability": "appointment.create",
            "stage": "awaiting_doctor",
        },
        note="Multiple conditions and fallback preference.",
    ),

    PolicyCase(
        name="multi_condition_slot",
        message=(
            "لو مفيش بكرة شوفلي بعده "
            "بس يكون بعد الساعة خمسة"
        ),
        expected_provider="gpt",
        context={
            "active_capability": "appointment.create",
            "stage": "awaiting_date",
        },
        note="Multiple temporal constraints.",
    ),

    PolicyCase(
        name="doctor_or_any_same_specialty",
        message=(
            "عايز دكتورة منى ولو مش موجودة "
            "أي دكتور في نفس التخصص"
        ),
        expected_provider="gpt",
        context={
            "active_capability": "appointment.create",
            "stage": "awaiting_doctor",
        },
        note="Primary preference plus fallback condition.",
    ),

    PolicyCase(
        name="closest_slot_with_condition",
        message=(
            "هاتلي أقرب ميعاد بس يكون "
            "بعد الساعة ستة"
        ),
        expected_provider="gpt",
        context={
            "active_capability": "appointment.create",
            "stage": "awaiting_time",
        },
        note="Optimization preference plus condition.",
    ),

    PolicyCase(
        name="cancel_then_new_booking",
        message=(
            "ألغي الحجز القديم "
            "واحجزلي واحد جديد السبت"
        ),
        expected_provider="gpt",
        context={
            "active_capability": "appointment.cancel",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,
        },
        note="Two distinct appointment operations.",
    ),

    PolicyCase(
        name="search_then_reschedule",
        message=(
            "شوف حجزي الأول ولو موجود "
            "غيره للاتنين"
        ),
        expected_provider="gpt",
        note="Lookup followed by conditional mutation.",
    ),

    PolicyCase(
        name="complex_doctor_and_time_preference",
        message=(
            "لو منى موجودة احجز معاها "
            "ولو لأ أي دكتورة جلدية "
            "بعد الساعة خمسة"
        ),
        expected_provider="gpt",
        context={
            "active_capability": "appointment.create",
            "stage": "awaiting_doctor",
        },
        note="Multiple fallback rules and constraints.",
    ),
]


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    router = SemanticCapabilityRouter()

    passed = 0

    qwen_expected = 0
    qwen_correct = 0

    gpt_expected = 0
    gpt_correct = 0

    failures: list[
        tuple[
            PolicyCase,
            str,
            str,
            int,
            tuple[str, ...],
            float | None,
        ]
    ] = []

    print(
        "Planner Policy Baseline"
    )

    print(
        "Cases:",
        len(CASES),
    )

    print(
        "Retriever Top-K:",
        TOP_K,
    )

    for index, case in enumerate(
        CASES,
        start=1,
    ):

        candidates = (
            select_capability_candidates(
                router=router,
                message=case.message,
                context=case.context,
                top_k=TOP_K,
            )
        )

        decision = (
            choose_planner_provider(
                message=case.message,
                context=case.context,
                candidates=candidates,
            )
        )

        correct = (
            decision.provider
            == case.expected_provider
        )

        if correct:
            passed += 1

        if case.expected_provider == "qwen":

            qwen_expected += 1

            if correct:
                qwen_correct += 1

        else:

            gpt_expected += 1

            if correct:
                gpt_correct += 1

        if not correct:

            failures.append(
                (
                    case,
                    decision.provider,
                    decision.reason,
                    decision.complexity_score,
                    decision.signals,
                    decision.semantic_margin,
                )
            )

        print()
        print(
            "=" * 72
        )

        print(
            f"{index:02d}. {case.name}"
        )

        print(
            "=" * 72
        )

        print(
            "USER:",
            case.message,
        )

        print(
            "STAGE:",
            case.context.get(
                "stage"
            ),
        )

        print(
            "ACTIVE:",
            case.context.get(
                "active_capability"
            ),
        )

        print(
            "EXPECTED:",
            case.expected_provider,
        )

        print(
            "ACTUAL:",
            decision.provider,
        )

        print(
            "LEVEL:",
            decision.complexity_level,
        )

        print(
            "SCORE:",
            decision.complexity_score,
        )

        print(
            "REASON:",
            decision.reason,
        )

        print(
            "SIGNALS:",
            decision.signals,
        )

        print(
            "SEMANTIC MARGIN:",
            (
                f"{decision.semantic_margin:.4f}"
                if decision.semantic_margin
                is not None
                else "N/A"
            ),
        )

        print(
            "ROUTER TOP 3:",
            [
                (
                    candidate.name,
                    round(
                        float(candidate.score),
                        4,
                    ),
                )
                for candidate
                in candidates[:3]
            ],
        )

        print(
            "RESULT:",
            (
                "PASS"
                if correct
                else "FAIL"
            ),
        )

        print(
            "NOTE:",
            case.note,
        )

    # ========================================================
    # SUMMARY
    # ========================================================

    total = len(
        CASES
    )

    accuracy = (
        passed
        / total
        * 100
    )

    print()
    print(
        "=" * 72
    )

    print(
        "PLANNER POLICY BASELINE SUMMARY"
    )

    print(
        "=" * 72
    )

    print(
        f"Overall:"
        f" {passed}/{total}"
        f" ({accuracy:.2f}%)"
    )

    print(
        f"Expected Qwen:"
        f" {qwen_correct}/{qwen_expected}"
    )

    print(
        f"Expected GPT:"
        f" {gpt_correct}/{gpt_expected}"
    )

    print(
        "Failures:",
        len(failures),
    )

    if failures:

        print()
        print(
            "MISROUTED CASES"
        )

        print(
            "-" * 72
        )

        for (
            case,
            actual_provider,
            reason,
            score,
            signals,
            semantic_margin,
        ) in failures:

            print(
                f"{case.name}: "
                f"expected="
                f"{case.expected_provider}, "
                f"actual="
                f"{actual_provider}, "
                f"score={score}, "
                f"reason={reason}, "
                f"signals={signals}, "
                f"margin="
                f"{semantic_margin}"
            )


if __name__ == "__main__":
    main()