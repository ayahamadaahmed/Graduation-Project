from __future__ import annotations

import asyncio
import os
import time

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)
from medmind.understanding.orchestrator import (
    UnderstandingOrchestrator,
)
from medmind.understanding.tool_planner import (
    ToolPlanner,
)
from medmind.understanding.qwen_tool_planner import (
    QwenToolPlanner,
)

from medmind.understanding.fallback_tool_planner import (
    FallbackToolPlanner,
)

TOP_K = 8


TEST_CASES = [

    # ========================================================
    # A. BOOKING CONFIRMATION
    # ========================================================

    {
        "name": "booking_confirm_yes",
        "message": "أيوه",

        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,

            "collected_arguments": {
                "patient_name": "آية أحمد",
                "doctor_name": "ماهر محمود",
                "date_text": "الخميس",
                "time_text": "الساعة خمسة",
                "phone": "01123456789",
            },
        },

        "expected_status": "selected",
        "expected_capability": "appointment.create",
        "expected_arguments": {},
        "expected_confirmation": "yes",
    },

    {
        "name": "booking_confirm_no",
        "message": "لا",

        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,

            "collected_arguments": {
                "patient_name": "آية أحمد",
                "doctor_name": "ماهر محمود",
                "date_text": "الخميس",
                "time_text": "الساعة خمسة",
            },
        },

        "expected_status": "selected",
        "expected_capability": "appointment.create",
        "expected_arguments": {},
        "expected_confirmation": "no",
    },

    # ========================================================
    # B. BOOKING CORRECTIONS
    #
    # A correction is NOT a rejection.
    # confirmation must remain unknown.
    # ========================================================

    {
        "name": "booking_correct_name",
        "message": "لا الاسم الصح آية محمد",

        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,

            "collected_arguments": {
                "patient_name": "آية أحمد",
                "doctor_name": "ماهر محمود",
                "date_text": "الخميس",
                "time_text": "الساعة خمسة",
            },
        },

        "expected_status": "selected",
        "expected_capability": "appointment.create",

        "expected_arguments": {
            "patient_name": "آية محمد",
        },

        "expected_confirmation": "unknown",
    },

    {
        "name": "booking_correct_time",
        "message": "لا الساعة الصح ستة",

        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,

            "collected_arguments": {
                "patient_name": "آية أحمد",
                "doctor_name": "ماهر محمود",
                "date_text": "الخميس",
                "time_text": "الساعة خمسة",
            },
        },

        "expected_status": "selected",
        "expected_capability": "appointment.create",

        "expected_arguments": {
             "time_text": "الساعة ستة",
        },

        "expected_confirmation": "unknown",
    },

    {
        "name": "booking_multiple_corrections",
        "message": (
            "لا الاسم آية محمد "
            "والميعاد الجمعة الساعة خمسة"
        ),

        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,

            "collected_arguments": {
                "patient_name": "آية أحمد",
                "doctor_name": "ماهر محمود",
                "date_text": "الخميس",
                "time_text": "الساعة ستة",
            },
        },

        "expected_status": "selected",
        "expected_capability": "appointment.create",

        "expected_arguments": {
            "patient_name": "آية محمد",
            "date_text": "الجمعة",
            "time_text": "الساعة خمسة",
        },

        "expected_confirmation": "unknown",
    },

    {
        "name": "booking_correct_doctor",
        "message": "لا الدكتور دكتورة منى",

        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,

            "collected_arguments": {
                "patient_name": "آية أحمد",
                "doctor_name": "ماهر محمود",
                "date_text": "الخميس",
                "time_text": "الساعة خمسة",
            },
        },

        "expected_status": "selected",
        "expected_capability": "appointment.create",

        "expected_arguments": {
            "doctor_name": "منى",
        },

        "expected_confirmation": "unknown",
    },

    # ========================================================
    # C. CANCELLATION CONFIRMATION
    # ========================================================

    {
        "name": "cancel_confirm_yes",
        "message": "أيوه الغيه",

        "context": {
            "active_capability": "appointment.cancel",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,

            "collected_arguments": {
                "appointment_reference":
                    "APT-260815-A9CD16BB",
            },
        },

        "expected_status": "selected",
        "expected_capability": "appointment.cancel",
        "expected_arguments": {},
        "expected_confirmation": "yes",
    },

    {
        "name": "cancel_confirm_no",
        "message": "لا متلغهوش",

        "context": {
            "active_capability": "appointment.cancel",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,

            "collected_arguments": {
                "appointment_reference":
                    "APT-260815-A9CD16BB",
            },
        },

        "expected_status": "selected",
        "expected_capability": "appointment.cancel",
        "expected_arguments": {},
        "expected_confirmation": "no",
    },

    # ========================================================
    # D. RESCHEDULE CONFIRMATION
    # ========================================================

    {
        "name": "reschedule_confirm_yes",
        "message": "أيوه تمام",

        "context": {
            "active_capability":
                "appointment.reschedule",

            "stage":
                "awaiting_confirmation",

            "pending_confirmation": True,

            "collected_arguments": {
                "appointment_reference":
                    "APT-260815-A9CD16BB",

                "date_text":
                    "الأحد",

                "time_text":
                    "الساعة ستة",
            },
        },

        "expected_status": "selected",
        "expected_capability":
            "appointment.reschedule",

        "expected_arguments": {},
        "expected_confirmation": "yes",
    },

    {
        "name": "reschedule_confirm_no",
        "message": "لا",

        "context": {
            "active_capability":
                "appointment.reschedule",

            "stage":
                "awaiting_confirmation",

            "pending_confirmation": True,

            "collected_arguments": {
                "appointment_reference":
                    "APT-260815-A9CD16BB",

                "date_text":
                    "الأحد",

                "time_text":
                    "الساعة ستة",
            },
        },

        "expected_status": "selected",
        "expected_capability":
            "appointment.reschedule",

        "expected_arguments": {},
        "expected_confirmation": "no",
    },

    # ========================================================
    # E. RESCHEDULE CORRECTION
    #
    # The appointment is not yet rescheduled.
    # User is correcting the pending new date.
    # ========================================================

    {
        "name": "reschedule_correct_date",
        "message": "لا خليه الاتنين",

        "context": {
            "active_capability":
                "appointment.reschedule",

            "stage":
                "awaiting_confirmation",

            "pending_confirmation": True,

            "collected_arguments": {
                "appointment_reference":
                    "APT-260815-A9CD16BB",

                "date_text":
                    "الأحد",

                "time_text":
                    "الساعة ستة",
            },
        },

        "expected_status": "selected",
        "expected_capability":
            "appointment.reschedule",

        "expected_arguments": {
            "date_text": "الاتنين",
        },

        "expected_confirmation": "unknown",
    },


        # ========================================================
    # F. CORRECTION REQUEST WITHOUT REPLACEMENT VALUE
    #
    # User identifies the field that is wrong but does not
    # provide the new value yet.
    # ========================================================

    {
        "name": "booking_request_correct_phone",
        "message": "رقم الموبايل غلط",

        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,

            "collected_arguments": {
                "patient_name": "آية أحمد",
                "doctor_name": "ماهر محمود",
                "date_text": "الخميس",
                "time_text": "الساعة خمسة",
                "phone": "01123456789",
            },
        },

        "expected_status": "selected",
        "expected_capability": "appointment.create",
        "expected_arguments": {},
        "expected_confirmation": "unknown",
        "expected_correction_target": "phone",
    },

    {
        "name": "booking_request_correct_name",
        "message": "عايزة أغير الاسم",

        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,

            "collected_arguments": {
                "patient_name": "آية أحمد",
                "doctor_name": "ماهر محمود",
                "date_text": "الخميس",
                "time_text": "الساعة خمسة",
            },
        },

        "expected_status": "selected",
        "expected_capability": "appointment.create",
        "expected_arguments": {},
        "expected_confirmation": "unknown",
        "expected_correction_target": "patient_name",
    },

    {
        "name": "booking_request_correct_doctor",
        "message": "الدكتور غلط",

        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,

            "collected_arguments": {
                "patient_name": "آية أحمد",
                "doctor_name": "ماهر محمود",
                "date_text": "الخميس",
                "time_text": "الساعة خمسة",
            },
        },

        "expected_status": "selected",
        "expected_capability": "appointment.create",
        "expected_arguments": {},
        "expected_confirmation": "unknown",
        "expected_correction_target": "doctor",
    },

    {
        "name": "booking_request_correct_schedule",
        "message": "عايزة أغير الميعاد",

        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,

            "collected_arguments": {
                "patient_name": "آية أحمد",
                "doctor_name": "ماهر محمود",
                "date_text": "الخميس",
                "time_text": "الساعة خمسة",
            },
        },

        "expected_status": "selected",
        "expected_capability": "appointment.create",
        "expected_arguments": {},
        "expected_confirmation": "unknown",
        "expected_correction_target": "schedule",
    },

    {
        "name": "booking_request_correct_time",
        "message": "الساعة غلط",

        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,

            "collected_arguments": {
                "patient_name": "آية أحمد",
                "doctor_name": "ماهر محمود",
                "date_text": "الخميس",
                "time_text": "الساعة خمسة",
            },
        },

        "expected_status": "selected",
        "expected_capability": "appointment.create",
        "expected_arguments": {},
        "expected_confirmation": "unknown",
        "expected_correction_target": "time",
    },

    {
        "name": "booking_request_correct_national_id",
        "message": "الرقم القومي غلط",

        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,

            "collected_arguments": {
                "patient_name": "آية أحمد",
                "doctor_name": "ماهر محمود",
                "date_text": "الخميس",
                "time_text": "الساعة خمسة",
            },
        },

        "expected_status": "selected",
        "expected_capability": "appointment.create",
        "expected_arguments": {},
        "expected_confirmation": "unknown",
        "expected_correction_target": "national_id",
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

    gpt_model = ChatOpenAI(
        model=model_name,
        temperature=0,
        timeout=30,
    )

    gpt_planner = ToolPlanner(
        model=gpt_model
    )

    qwen_planner = QwenToolPlanner(
        api_key=os.environ[
            "GROQ_API_KEY"
        ],

        model=os.getenv(
            "QWEN_PLANNER_MODEL",
            "qwen/qwen3.6-27b",
        ),

        timeout=float(
            os.getenv(
                "QWEN_PLANNER_TIMEOUT",
                "3",
            )
        ),

        max_tokens=int(
            os.getenv(
                "QWEN_PLANNER_MAX_TOKENS",
                "160",
            )
        ),
    )

    planner = FallbackToolPlanner(
        primary=qwen_planner,
        fallback=gpt_planner,
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

    status_correct = 0
    capability_correct = 0
    arguments_correct = 0
    confirmation_correct = 0
    correction_target_correct = 0
    no_copy_correct = 0
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

        confirmation_ok = (
            result.confirmation
            == case[
                "expected_confirmation"
            ]
        )

        expected_correction_target = (
            case.get(
                "expected_correction_target"
            )
        )

        correction_target_ok = (
            result.correction_target
            == expected_correction_target
        )

        # ----------------------------------------------------
        # Turn-delta guard:
        #
        # Existing state values must not suddenly appear in
        # result.arguments unless this test explicitly expects
        # them as a correction.
        # ----------------------------------------------------

        expected_argument_keys = set(
            case[
                "expected_arguments"
            ].keys()
        )

        actual_argument_keys = set(
            result.arguments.keys()
        )

        no_copy_ok = (
            actual_argument_keys
            == expected_argument_keys
        )

        full_ok = (
            status_ok
            and capability_ok
            and arguments_ok
            and confirmation_ok
            and correction_target_ok
            and no_copy_ok
        )

        if status_ok:
            status_correct += 1

        if capability_ok:
            capability_correct += 1

        if arguments_ok:
            arguments_correct += 1

        if confirmation_ok:
            confirmation_correct += 1

        if correction_target_ok:
            correction_target_correct += 1

        if no_copy_ok:
            no_copy_correct += 1

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
            case["message"],
        )

        print(
            "ACTIVE CAPABILITY:",
            case["context"].get(
                "active_capability"
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
            "EXPECTED CONFIRMATION:",
            case[
                "expected_confirmation"
            ],
        )

        print(
            "CORRECTION TARGET:",
            (
                "PASS"
                if correction_target_ok
                else "FAIL"
            ),
        )

        print(
            "RESULT CONFIRMATION:",
            result.confirmation,
        )

        print(
            "EXPECTED CORRECTION TARGET:",
            expected_correction_target,
        )

        print(
            "RESULT CORRECTION TARGET:",
            result.correction_target,
        )

        print(
            "AMBIGUITY KIND:",
            result.ambiguity_kind,
        )

        print(
            "ATTEMPTS:",
            result.attempts,
        )

        print(
            "BROAD:",
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
            "CONFIRMATION:",
            (
                "PASS"
                if confirmation_ok
                else "FAIL"
            ),
        )

        print(
            "NO OLD ARGUMENT COPY:",
            (
                "PASS"
                if no_copy_ok
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
        "FINAL CONFIRMATION RESULTS"
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
        "Confirmation accuracy: "
        f"{confirmation_correct / total_cases:.2%}"
    )

    print(
        "Correction-target accuracy: "
        f"{correction_target_correct / total_cases:.2%}"
    )

    print(
        "No old argument copy: "
        f"{no_copy_correct / total_cases:.2%}"
    )

    print(
        "Full accuracy: "
        f"{full_correct / total_cases:.2%}"
    )

    print()

    if latencies:

        sorted_latencies = sorted(
            latencies
        )

        middle = (
            len(sorted_latencies)
            // 2
        )

        print(
            "Approx P50 latency: "
            f"{sorted_latencies[middle]:.2f} ms"
        )


if __name__ == "__main__":

    asyncio.run(
        main()
    )