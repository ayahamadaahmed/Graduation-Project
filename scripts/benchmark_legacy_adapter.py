from __future__ import annotations

from medmind.state.models import (
    SessionState,
)
from medmind.understanding.legacy_adapter import (
    adapt_understanding_to_nlu,
)
from medmind.understanding.orchestrator import (
    UnderstandingResult,
)


# ============================================================
# HELPERS
# ============================================================

def make_state(
    *,
    operation_type=None,
    stage: str = "new",
    awaiting_confirmation: bool = False,
) -> SessionState:

    return SessionState(
        channel="web",
        session_id="legacy-adapter-test",
        tenant_id="test-tenant",
        operation_type=operation_type,
        stage=stage,
        awaiting_confirmation=awaiting_confirmation,
    )


def make_result(
    *,
    capability: str,
    arguments: dict[str, str] | None = None,
    confirmation: str = "unknown",
    correction_target: str | None = None,
) -> UnderstandingResult:

    return UnderstandingResult(
        status="selected",
        capability=capability,
        arguments=arguments or {},
        confirmation=confirmation,
        correction_target=correction_target,
        ambiguity_kind=None,
        reason="benchmark",
        attempts=1,
        used_broad_candidates=False,
    )


# ============================================================
# TEST CASES
# ============================================================

TEST_CASES = [

    # --------------------------------------------------------
    # New booking
    # --------------------------------------------------------

    {
        "name": "new_booking",
        "state": make_state(),
        "result": make_result(
            capability="appointment.create",
            arguments={
                "date_text": "بكرة",
            },
        ),
        "expected_intent": "book_appointment",
        "expected_operation": "book_appointment",
        "expected_confirmation": "unknown",
        "expected_entities": {
            "date_text": "بكرة",
        },
    },

    # --------------------------------------------------------
    # Active booking contextual values
    # --------------------------------------------------------

    {
        "name": "booking_context_date",
        "state": make_state(
            operation_type="book_appointment",
            stage="awaiting_date",
        ),
        "result": make_result(
            capability="appointment.create",
            arguments={
                "date_text": "بكرة",
            },
        ),
        "expected_intent": "provide_date",
        "expected_operation": None,
        "expected_confirmation": "unknown",
        "expected_entities": {
            "date_text": "بكرة",
        },
    },

    {
        "name": "booking_context_doctor",
        "state": make_state(
            operation_type="book_appointment",
            stage="awaiting_doctor",
        ),
        "result": make_result(
            capability="appointment.create",
            arguments={
                "doctor_name": "دكتور ماهر",
            },
        ),
        "expected_intent": "provide_doctor",
        "expected_operation": None,
        "expected_confirmation": "unknown",
        "expected_entities": {
            "doctor_name": "دكتور ماهر",
        },
    },

    # --------------------------------------------------------
    # Same operation with stage=new
    # --------------------------------------------------------

    {
        "name": "active_booking_stage_new",
        "state": make_state(
            operation_type="book_appointment",
            stage="new",
        ),
        "result": make_result(
            capability="appointment.create",
            arguments={
                "doctor_name": "دكتور ماهر",
            },
        ),
        "expected_intent": "provide_doctor",
        "expected_operation": None,
        "expected_confirmation": "unknown",
        "expected_entities": {
            "doctor_name": "دكتور ماهر",
        },
    },

    # --------------------------------------------------------
    # Booking confirmation
    # --------------------------------------------------------

    {
        "name": "booking_confirm_yes",
        "state": make_state(
            operation_type="book_appointment",
            stage="awaiting_confirmation",
            awaiting_confirmation=True,
        ),
        "result": make_result(
            capability="appointment.create",
            confirmation="yes",
        ),
        "expected_intent": "confirm_action",
        "expected_operation": None,
        "expected_confirmation": "yes",
        "expected_entities": {},
    },

    {
        "name": "booking_confirm_no",
        "state": make_state(
            operation_type="book_appointment",
            stage="awaiting_confirmation",
            awaiting_confirmation=True,
        ),
        "result": make_result(
            capability="appointment.create",
            confirmation="no",
        ),
        "expected_intent": "deny_action",
        "expected_operation": None,
        "expected_confirmation": "no",
        "expected_entities": {},
    },

    # --------------------------------------------------------
    # Correction with replacement value
    # --------------------------------------------------------

    {
        "name": "booking_correct_name",
        "state": make_state(
            operation_type="book_appointment",
            stage="awaiting_confirmation",
            awaiting_confirmation=True,
        ),
        "result": make_result(
            capability="appointment.create",
            arguments={
                "patient_name": "آية محمد",
            },
        ),
        "expected_intent": "provide_patient_name",
        "expected_operation": None,
        "expected_confirmation": "unknown",
        "expected_entities": {
            "patient_name": "آية محمد",
        },
    },

    # --------------------------------------------------------
    # Multiple corrections
    # --------------------------------------------------------

    {
        "name": "booking_multiple_corrections",
        "state": make_state(
            operation_type="book_appointment",
            stage="awaiting_confirmation",
            awaiting_confirmation=True,
        ),
        "result": make_result(
            capability="appointment.create",
            arguments={
                "patient_name": "آية محمد",
                "date_text": "الجمعة",
                "time_text": "الساعة خمسة",
            },
        ),
        "expected_intent": "provide_patient_name",
        "expected_operation": None,
        "expected_confirmation": "unknown",
        "expected_entities": {
            "patient_name": "آية محمد",
            "date_text": "الجمعة",
            "time_text": "الساعة خمسة",
        },
    },

    # --------------------------------------------------------
    # Correction request without replacement
    # --------------------------------------------------------

    {
        "name": "booking_request_correct_phone",
        "state": make_state(
            operation_type="book_appointment",
            stage="awaiting_confirmation",
            awaiting_confirmation=True,
        ),
        "result": make_result(
            capability="appointment.create",
            correction_target="phone",
        ),
        "expected_intent": "provide_phone",
        "expected_operation": None,
        "expected_confirmation": "unknown",
        "expected_entities": {},
    },

    {
        "name": "booking_request_correct_schedule",
        "state": make_state(
            operation_type="book_appointment",
            stage="awaiting_confirmation",
            awaiting_confirmation=True,
        ),
        "result": make_result(
            capability="appointment.create",
            correction_target="schedule",
        ),
        "expected_intent": "provide_date",
        "expected_operation": None,
        "expected_confirmation": "unknown",
        "expected_entities": {},
    },

    {
        "name": "booking_request_correct_national_id",
        "state": make_state(
            operation_type="book_appointment",
            stage="awaiting_confirmation",
            awaiting_confirmation=True,
        ),
        "result": make_result(
            capability="appointment.create",
            correction_target="national_id",
        ),
        "expected_intent": "provide_national_id",
        "expected_operation": None,
        "expected_confirmation": "unknown",
        "expected_entities": {},
    },

    # --------------------------------------------------------
    # Cancel
    # --------------------------------------------------------

    {
        "name": "new_cancel",
        "state": make_state(),
        "result": make_result(
            capability="appointment.cancel",
            arguments={
                "appointment_reference":
                    "APT-260815-A9CD16BB",
            },
        ),
        "expected_intent": "cancel_appointment",
        "expected_operation": "cancel_appointment",
        "expected_confirmation": "unknown",
        "expected_entities": {
            "appointment_reference":
                "APT-260815-A9CD16BB",
        },
    },

    {
        "name": "cancel_confirm_yes",
        "state": make_state(
            operation_type="cancel_appointment",
            stage="awaiting_confirmation",
            awaiting_confirmation=True,
        ),
        "result": make_result(
            capability="appointment.cancel",
            confirmation="yes",
        ),
        "expected_intent": "confirm_action",
        "expected_operation": None,
        "expected_confirmation": "yes",
        "expected_entities": {},
    },

    # --------------------------------------------------------
    # Operation switch
    # cancel -> reschedule
    # --------------------------------------------------------

    {
        "name": "cancel_to_reschedule",
        "state": make_state(
            operation_type="cancel_appointment",
            stage="awaiting_confirmation",
            awaiting_confirmation=True,
        ),
        "result": make_result(
            capability="appointment.reschedule",
            arguments={
                "date_text": "السبت",
            },
        ),
        "expected_intent": "reschedule_appointment",
        "expected_operation": "reschedule_appointment",
        "expected_confirmation": "unknown",
        "expected_entities": {
            "date_text": "السبت",
        },
    },

    # --------------------------------------------------------
    # Active reschedule contextual value
    # --------------------------------------------------------

    {
        "name": "reschedule_context_time",
        "state": make_state(
            operation_type="reschedule_appointment",
            stage="awaiting_time",
        ),
        "result": make_result(
            capability="appointment.reschedule",
            arguments={
                "time_text": "الساعة ستة",
            },
        ),
        "expected_intent": "provide_time",
        "expected_operation": None,
        "expected_confirmation": "unknown",
        "expected_entities": {
            "time_text": "الساعة ستة",
        },
    },

    # --------------------------------------------------------
    # Appointment search
    # --------------------------------------------------------

    {
        "name": "appointment_search_general",
        "state": make_state(),
        "result": make_result(
            capability="appointment.search",
        ),
        "expected_intent": "search_appointments",
        "expected_operation": "search_appointments",
        "expected_confirmation": "unknown",
        "expected_entities": {},
    },

    {
        "name": "appointment_lookup_by_reference",
        "state": make_state(),
        "result": make_result(
            capability="appointment.search",
            arguments={
                "appointment_reference":
                    "APT-260815-A9CD16BB",
            },
        ),
        "expected_intent": "lookup_appointment",
        "expected_operation": "lookup_appointment",
        "expected_confirmation": "unknown",
        "expected_entities": {
            "appointment_reference":
                "APT-260815-A9CD16BB",
        },
    },

    # --------------------------------------------------------
    # Read capabilities
    # --------------------------------------------------------

    {
        "name": "search_doctors",
        "state": make_state(),
        "result": make_result(
            capability="provider.search_doctors",
            arguments={
                "specialty_name": "جلدية",
            },
        ),
        "expected_intent": "ask_doctor",
        "expected_operation": None,
        "expected_confirmation": "unknown",
        "expected_entities": {
            "specialty_name": "جلدية",
        },
    },

    {
        "name": "get_services",
        "state": make_state(),
        "result": make_result(
            capability="provider.get_services",
            arguments={
                "service_name": "كشف عيون",
            },
        ),
        "expected_intent": "ask_service",
        "expected_operation": None,
        "expected_confirmation": "unknown",
        "expected_entities": {
            "service_name": "كشف عيون",
        },
    },

    {
        "name": "get_slots",
        "state": make_state(),
        "result": make_result(
            capability="provider.get_slots",
            arguments={
                "doctor_name": "ماهر",
                "date_text": "بكرة",
                "time_text": "بالليل",
            },
        ),
        "expected_intent": "ask_available_slots",
        "expected_operation": None,
        "expected_confirmation": "unknown",
        "expected_entities": {
            "doctor_name": "ماهر",
            "date_text": "بكرة",
            "time_text": "بالليل",
        },
    },

    {
        "name": "provider_policy",
        "state": make_state(),
        "result": make_result(
            capability="provider.get_policy",
        ),
        "expected_intent": "ask_provider",
        "expected_operation": None,
        "expected_confirmation": "unknown",
        "expected_entities": {},
    },

    {
        "name": "provider_working_hours",
        "state": make_state(),
        "result": make_result(
            capability="provider.get_working_hours",
        ),
        "expected_intent": "ask_provider",
        "expected_operation": None,
        "expected_confirmation": "unknown",
        "expected_entities": {},
    },

    {
        "name": "knowledge_search",
        "state": make_state(),
        "result": make_result(
            capability="knowledge.search",
        ),
        "expected_intent": "ask_provider",
        "expected_operation": None,
        "expected_confirmation": "unknown",
        "expected_entities": {},
    },

    {
        "name": "human_support",
        "state": make_state(),
        "result": make_result(
            capability="human_support.transfer",
        ),
        "expected_intent": "help",
        "expected_operation": None,
        "expected_confirmation": "unknown",
        "expected_entities": {},
    },
]


# ============================================================
# ENTITY CHECK
# ============================================================

def entities_match(
    *,
    actual,
    expected: dict[str, str],
) -> bool:

    actual_data = (
        actual.model_dump()
    )

    # Expected values must exist exactly.
    for key, expected_value in (
        expected.items()
    ):

        if (
            actual_data.get(key)
            != expected_value
        ):
            return False

    # Fields that were NOT expected must remain empty.
    for key, actual_value in (
        actual_data.items()
    ):

        if (
            key not in expected
            and
            actual_value is not None
        ):
            return False

    return True


# ============================================================
# RUNNER
# ============================================================

def main() -> None:

    total = len(
        TEST_CASES
    )

    passed = 0

    print()
    print("=" * 80)
    print("LEGACY ADAPTER BENCHMARK")
    print("=" * 80)

    for case in TEST_CASES:

        nlu = (
            adapt_understanding_to_nlu(
                result=case["result"],
                state=case["state"],
            )
        )

        intent_ok = (
            nlu.intent
            == case["expected_intent"]
        )

        operation_ok = (
            nlu.operation_type
            == case[
                "expected_operation"
            ]
        )

        confirmation_ok = (
            nlu.confirmation
            == case[
                "expected_confirmation"
            ]
        )

        entities_ok = (
            entities_match(
                actual=nlu.entities,
                expected=case[
                    "expected_entities"
                ],
            )
        )

        full_ok = (
            intent_ok
            and operation_ok
            and confirmation_ok
            and entities_ok
        )

        if full_ok:
            passed += 1

        print()
        print("-" * 80)

        print(
            "CASE:",
            case["name"],
        )

        print(
            "INTENT:",
            nlu.intent,
            "|",
            (
                "PASS"
                if intent_ok
                else "FAIL"
            ),
        )

        print(
            "OPERATION:",
            nlu.operation_type,
            "|",
            (
                "PASS"
                if operation_ok
                else "FAIL"
            ),
        )

        print(
            "CONFIRMATION:",
            nlu.confirmation,
            "|",
            (
                "PASS"
                if confirmation_ok
                else "FAIL"
            ),
        )

        print(
            "ENTITIES:",
            nlu.entities.model_dump(),
        )

        print(
            "ENTITY CHECK:",
            (
                "PASS"
                if entities_ok
                else "FAIL"
            ),
        )

        print(
            "FULL:",
            (
                "PASS"
                if full_ok
                else "FAIL"
            ),
        )

    print()
    print("=" * 80)
    print("FINAL RESULTS")
    print("=" * 80)

    print(
        f"Cases: {total}"
    )

    print(
        f"Passed: {passed}"
    )

    print(
        f"Accuracy: "
        f"{passed / total:.2%}"
    )


if __name__ == "__main__":
    main()