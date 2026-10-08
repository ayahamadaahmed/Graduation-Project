from medmind.state.context import (
    remember_conversation_focus,
    remember_pending_operation_entities,
    resolve_effective_context,
)

from medmind.state.models import (
    SessionState,
)

from medmind.understanding.types import (
    NLUEntities,
    NLUResult,
)


# ============================================================
# HELPERS
# ============================================================

def make_state(
    **overrides,
) -> SessionState:

    values = {
        "channel": "web",
        "session_id": "context-test-session",
        "tenant_id": "context-test-tenant",
        "language": "ar",
    }

    values.update(
        overrides
    )

    return SessionState(
        **values
    )


def make_nlu(
    *,
    intent: str = "unknown",
    operation_type=None,
    specialty_name=None,
    doctor_name=None,
    service_name=None,
    date_text=None,
    time_text=None,
) -> NLUResult:

    return NLUResult(
        intent=intent,
        operation_type=operation_type,

        entities=NLUEntities(
            specialty_name=
                specialty_name,

            doctor_name=
                doctor_name,

            service_name=
                service_name,

            date_text=
                date_text,

            time_text=
                time_text,
        ),

        confirmation="unknown",
        confidence=1.0,
    )


# ============================================================
# 1. MULTI-ENTITY TURN
# ============================================================

def test_pending_entities_keep_full_booking_turn():

    state = make_state(
        operation_type=
            "book_appointment",
    )

    nlu = make_nlu(
        intent=
            "book_appointment",

        operation_type=
            "book_appointment",

        specialty_name=
            "جلدية",

        doctor_name=
            "دكتور أحمد",

        service_name=
            "كشف",

        date_text=
            "بكرة",

        time_text=
            "الساعة 5",
    )

    remember_pending_operation_entities(
        state=state,
        nlu=nlu,
    )

    assert (
        state.pending_operation_entities
        ==
        {
            "specialty_name":
                "جلدية",

            "doctor_name":
                "دكتور أحمد",

            "service_name":
                "كشف",

            "date_text":
                "بكرة",

            "time_text":
                "الساعة 5",
        }
    )


# ============================================================
# 2. DATE/TIME SURVIVE A CLARIFICATION TURN
# ============================================================

def test_booking_date_and_time_survive_doctor_question():

    state = make_state(
        operation_type=
            "book_appointment",
    )

    # --------------------------------------------------------
    # First turn:
    #
    # "عايز أحجز جلدية بكرة الساعة 5"
    # --------------------------------------------------------

    first_turn = make_nlu(
        intent=
            "book_appointment",

        operation_type=
            "book_appointment",

        specialty_name=
            "جلدية",

        date_text=
            "بكرة",

        time_text=
            "الساعة 5",
    )

    remember_pending_operation_entities(
        state=state,
        nlu=first_turn,
    )

    # --------------------------------------------------------
    # Second turn:
    #
    # Agent asked which doctor.
    # User says only:
    #
    # "دكتور أحمد"
    # --------------------------------------------------------

    second_turn = make_nlu(
        intent=
            "provide_doctor",

        doctor_name=
            "دكتور أحمد",
    )

    remember_pending_operation_entities(
        state=state,
        nlu=second_turn,
    )

    context = (
        resolve_effective_context(
            state=state,
            nlu=second_turn,
        )
    )

    assert (
        context.specialty_name
        == "جلدية"
    )

    assert (
        context.doctor_name
        == "دكتور أحمد"
    )

    assert (
        context.date_text
        == "بكرة"
    )

    assert (
        context.time_text
        == "الساعة 5"
    )


# ============================================================
# 3. CURRENT DOCTOR OVERRIDES OLD CONVERSATION DOCTOR
# ============================================================

def test_current_doctor_overrides_old_doctor_without_reusing_old_id():

    state = make_state(
        conversation_doctor_name=
            "دكتور أحمد",

        conversation_doctor_id=
            "doctor-ahmed",
    )

    nlu = make_nlu(
        intent=
            "provide_doctor",

        doctor_name=
            "دكتور محمود",
    )

    context = (
        resolve_effective_context(
            state=state,
            nlu=nlu,
        )
    )

    assert (
        context.doctor_name
        == "دكتور محمود"
    )

    # Mahmoud has not been validated against DB yet,
    # therefore Ahmed's ID must never be reused.
    assert (
        context.doctor_id
        is None
    )


# ============================================================
# 4. SPECIALTY CHANGE INVALIDATES OLD DOCTOR/SERVICE
# ============================================================

def test_new_specialty_does_not_inherit_old_doctor_or_service():

    state = make_state(
        operation_type=
            "book_appointment",

        conversation_specialty_name=
            "قلب",

        conversation_specialty_id=
            "specialty-cardio",

        conversation_doctor_name=
            "دكتور أحمد",

        conversation_doctor_id=
            "doctor-ahmed",

        conversation_service_name=
            "كشف قلب",

        conversation_service_id=
            "service-cardio",
    )

    nlu = make_nlu(
        intent=
            "book_appointment",

        operation_type=
            "book_appointment",

        specialty_name=
            "جلدية",

        date_text=
            "بكرة",
    )

    remember_pending_operation_entities(
        state=state,
        nlu=nlu,
    )

    context = (
        resolve_effective_context(
            state=state,
            nlu=nlu,
        )
    )

    assert (
        context.specialty_name
        == "جلدية"
    )

    assert (
        context.specialty_id
        is None
    )

    assert (
        context.doctor_name
        is None
    )

    assert (
        context.doctor_id
        is None
    )

    assert (
        context.service_name
        is None
    )

    assert (
        context.service_id
        is None
    )

    assert (
        context.date_text
        == "بكرة"
    )


# ============================================================
# 5. SAME TRUSTED ENTITY MAY REUSE ITS DATABASE ID
# ============================================================

def test_same_current_doctor_can_reuse_trusted_workflow_id():

    state = make_state(
        operation_type=
            "book_appointment",

        specialty_id=
            "specialty-derma",

        specialty_name=
            "جلدية",

        doctor_id=
            "doctor-ahmed",

        doctor_name=
            "دكتور أحمد",
    )

    nlu = make_nlu(
        intent=
            "provide_doctor",

        doctor_name=
            "دكتور أحمد",
    )

    context = (
        resolve_effective_context(
            state=state,
            nlu=nlu,
        )
    )

    assert (
        context.doctor_name
        == "دكتور أحمد"
    )

    assert (
        context.doctor_id
        == "doctor-ahmed"
    )


# ============================================================
# 6. CONVERSATION FOCUS RESPECTS CURRENT TURN
# ============================================================

def test_conversation_focus_uses_new_explicit_doctor():

    state = make_state(
        conversation_doctor_name=
            "دكتور أحمد",

        conversation_doctor_id=
            "doctor-ahmed",
    )

    nlu = make_nlu(
        intent=
            "provide_doctor",

        doctor_name=
            "دكتور محمود",
    )

    remember_conversation_focus(
        state=state,
        nlu=nlu,
        capability=
            "provider.get_working_hours",
    )

    assert (
        state.conversation_doctor_name
        == "دكتور محمود"
    )

    assert (
        state.conversation_doctor_id
        is None
    )

    assert (
        state.conversation_focus_capability
        == "provider.get_working_hours"
    )