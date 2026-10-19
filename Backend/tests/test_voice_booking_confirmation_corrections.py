from __future__ import annotations

import pytest

from medmind.state.models import (
    SessionState,
)

from medmind.understanding.types import (
    NLUEntities,
    NLUResult,
)

from medmind.workflows.booking import (
    BookingWorkflow,
)


# ============================================================
# FAKE TOOLS
# ============================================================

class FakeCorrectionTools:

    def __init__(
        self,
    ) -> None:

        self.calls: list[
            tuple[str, dict]
        ] = []

    async def call(
        self,
        name: str,
        **kwargs,
    ):

        self.calls.append(
            (
                name,
                kwargs,
            )
        )

        # ----------------------------------------------------
        # Doctors
        # ----------------------------------------------------

        if name == "list_doctors":

            return [
                {
                    "id":
                        "doctor-1",

                    "specialty_id":
                        "spec-1",

                    "full_name_ar":
                        "دكتور ماهر محمود",

                    "full_name_en":
                        "Dr Maher Mahmoud",
                },
                {
                    "id":
                        "doctor-2",

                    "specialty_id":
                        "spec-1",

                    "full_name_ar":
                        "دكتور منى صلاح",

                    "full_name_en":
                        "Dr Mona Salah",
                },
            ]

        # ----------------------------------------------------
        # Available slots
        # ----------------------------------------------------

        if name == "list_available_slots":

            doctor_id = (
                kwargs["doctor_id"]
            )

            slot_date = (
                kwargs["slot_date"]
            )

            # --------------------------------------------
            # Doctor 1
            # --------------------------------------------

            if (
                doctor_id == "doctor-1"
                and
                slot_date == "2026-08-27"
            ):

                return [
                    {
                        "id":
                            "slot-d1-27-1700",

                        "doctor_id":
                            "doctor-1",

                        "branch_id":
                            "branch-1",

                        "slot_date":
                            "2026-08-27",

                        "start_time":
                            "17:00:00",

                        "end_time":
                            "17:30:00",

                        "status":
                            "available",
                    },
                    {
                        "id":
                            "slot-d1-27-1930",

                        "doctor_id":
                            "doctor-1",

                        "branch_id":
                            "branch-1",

                        "slot_date":
                            "2026-08-27",

                        "start_time":
                            "19:30:00",

                        "end_time":
                            "20:00:00",

                        "status":
                            "available",
                    },
                ]

            if (
                doctor_id == "doctor-1"
                and
                slot_date == "2026-08-28"
            ):

                return [
                    {
                        "id":
                            "slot-d1-28-1700",

                        "doctor_id":
                            "doctor-1",

                        "branch_id":
                            "branch-1",

                        "slot_date":
                            "2026-08-28",

                        "start_time":
                            "17:00:00",

                        "end_time":
                            "17:30:00",

                        "status":
                            "available",
                    },
                    {
                        "id":
                            "slot-d1-28-1930",

                        "doctor_id":
                            "doctor-1",

                        "branch_id":
                            "branch-1",

                        "slot_date":
                            "2026-08-28",

                        "start_time":
                            "19:30:00",

                        "end_time":
                            "20:00:00",

                        "status":
                            "available",
                    },
                ]

            # --------------------------------------------
            # Doctor 2
            # --------------------------------------------

            if (
                doctor_id == "doctor-2"
                and
                slot_date == "2026-08-27"
            ):

                return [
                    {
                        "id":
                            "slot-d2-27-1700",

                        "doctor_id":
                            "doctor-2",

                        "branch_id":
                            "branch-1",

                        "slot_date":
                            "2026-08-27",

                        "start_time":
                            "17:00:00",

                        "end_time":
                            "17:30:00",

                        "status":
                            "available",
                    },
                    {
                        "id":
                            "slot-d2-27-1930",

                        "doctor_id":
                            "doctor-2",

                        "branch_id":
                            "branch-1",

                        "slot_date":
                            "2026-08-27",

                        "start_time":
                            "19:30:00",

                        "end_time":
                            "20:00:00",

                        "status":
                            "available",
                    },
                ]

            return []

        # ----------------------------------------------------
        # Services for corrected doctor
        # ----------------------------------------------------

        if name == "list_services":

            return [
                {
                    "id":
                        "service-1",

                    "code":
                        "DERM-CONSULT",

                    "name_ar":
                        "كشف جلدية",

                    "name_en":
                        "Dermatology Consultation",

                    "price":
                        "500",
                }
            ]

        # ----------------------------------------------------
        # Booking MUST NOT happen in correction tests
        # ----------------------------------------------------
        if name == "update_patient_profile":

            return {
                "patient_id":
                    kwargs["patient_id"],

                "display_name":
                    (
                        kwargs.get(
                            "patient_name"
                        )
                        or
                        "آية أحمد"
                    ),

                "phone":
                    (
                        kwargs.get(
                            "phone"
                        )
                        or
                        "01023456789"
                    ),

                "updated_fields":
                    [
                        field
                        for field in (
                            "patient_name",
                            "phone",
                        )
                        if kwargs.get(
                            field
                        )
                        is not None
                    ],
            }


        if name == "create_booking":

            raise AssertionError(
                "create_booking must not run "
                "while correcting booking details"
            )

        raise AssertionError(
            f"Unexpected tool call: {name}"
        )


# ============================================================
# NLU FACTORY
# ============================================================

def make_nlu(
    *,
    intent: str = "unknown",
    confirmation: str = "unknown",
    **entities,
) -> NLUResult:

    return NLUResult(
        intent=
            intent,

        confirmation=
            confirmation,

        confidence=
            1.0,

        entities=
            NLUEntities(
                **entities
            ),
    )


# ============================================================
# READY CONFIRMATION STATE
# ============================================================

def ready_confirmation_state(
) -> SessionState:

    return SessionState(
        session_id=
            "voice-correction-test",

        tenant_id=
            "clinic-001",

        language=
            "ar",

        channel=
            "voice",

        operation_type=
            "book_appointment",

        stage=
            "awaiting_confirmation",

        specialty_id=
            "spec-1",

        specialty_name=
            "جلدية",

        doctor_id=
            "doctor-1",

        doctor_name=
            "دكتور ماهر محمود",

        service_id=
            "service-1",

        service_name=
            "كشف جلدية",

        slot_id=
            "slot-d1-27-1930",

        slot_date=
            "2026-08-27",

        slot_time=
            "19:30",

        national_id=
            "29901010000001",

        patient_id=
            "patient-1",

        patient_name=
            "آية أحمد",

        phone=
            "01023456789",

        phone_confirmed=
            True,

        awaiting_confirmation=
            True,

        pending_action=
            "create_booking",
    )


# ============================================================
# TEST 1
#
# PATIENT NAME CORRECTION
#
# Important:
# Even if NLU also says deny_action/no,
# replacement entity must win.
# ============================================================

@pytest.mark.asyncio
async def test_patient_name_correction_is_not_booking_rejection(
) -> None:

    tools = (
        FakeCorrectionTools()
    )

    workflow = (
        BookingWorkflow(
            tools=tools,
        )
    )

    state = (
        ready_confirmation_state()
    )

    result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "deny_action",

                confirmation=
                    "no",

                patient_name=
                    "آية محمد",
            ),
        )
    )

    assert (
        state.patient_name
        == "آية أحمد"
    )

    assert (
        state.stage
        == "awaiting_patient_name_correction"
    )

    assert (
        state.awaiting_confirmation
        is False
    )

    assert (
        state.pending_action
        is None
    )

    assert (
        result.response_type
        == "ask_patient_name_correction"
    )

    assert (
        state.stage
        != "booking_cancelled_before_create"
    )

    # No DB write and no booking yet.
    assert (
        tools.calls
        == []
    )

    assert (
        state.pending_patient_profile_updates
        == {}
    )


# ============================================================
# TEST 2
#
# PHONE CORRECTION
# → must require fresh Voice confirmation
# ============================================================

@pytest.mark.asyncio
async def test_phone_correction_requires_voice_reconfirmation(
) -> None:

    tools = (
        FakeCorrectionTools()
    )

    workflow = (
        BookingWorkflow(
            tools=tools,
        )
    )

    state = (
        ready_confirmation_state()
    )

    result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "deny_action",

                confirmation=
                    "no",

                phone=
                    "01123456789",
            ),
        )
    )

    assert (
        state.phone
        == "01123456789"
    )

    assert (
        state.phone_confirmed
        is False
    )

    assert (
        state.stage
        == "awaiting_phone_confirmation"
    )

    assert (
        state.awaiting_confirmation
        is False
    )

    assert (
        state.pending_action
        is None
    )

    assert (
        result.response_type
        == "phone_confirmation"
    )

    assert (
        "رقم الموبايل"
        in result.reply
    )

    assert (
        state.stage
        != "booking_cancelled_before_create"
    )

    assert tools.calls == []


# ============================================================
# TEST 3
#
# DOCTOR CORRECTION
#
# Doctor change must:
# - validate doctor
# - reload slots
# - select a real slot
# - revalidate service
# - return to confirmation
# ============================================================

@pytest.mark.asyncio
async def test_doctor_correction_revalidates_slot_and_service(
) -> None:

    tools = (
        FakeCorrectionTools()
    )

    workflow = (
        BookingWorkflow(
            tools=tools,
        )
    )

    state = (
        ready_confirmation_state()
    )

    result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "provide_doctor",

                doctor_name=
                    "دكتور منى صلاح",
            ),
        )
    )

    assert (
        state.doctor_id
        == "doctor-2"
    )

    assert (
        state.doctor_name
        == "دكتور منى صلاح"
    )

    # Old time was 19:30.
    # It exists for doctor-2,
    # therefore it may be safely preserved.
    assert (
        state.slot_id
        == "slot-d2-27-1930"
    )

    assert (
        state.slot_date
        == "2026-08-27"
    )

    assert (
        state.slot_time
        == "19:30"
    )

    # Service exists for new doctor.
    assert (
        state.service_id
        == "service-1"
    )

    assert (
        state.service_name
        == "كشف جلدية"
    )

    assert (
        state.stage
        == "awaiting_confirmation"
    )

    assert (
        result.response_type
        == "booking_confirmation"
    )

    tool_names = [
        name
        for name, _
        in tools.calls
    ]

    assert (
        "list_doctors"
        in tool_names
    )

    assert (
        "list_available_slots"
        in tool_names
    )

    assert (
        "list_services"
        in tool_names
    )

    assert (
        "create_booking"
        not in tool_names
    )


# ============================================================
# TEST 4
#
# DATE CORRECTION
#
# New date → reload backend slots.
# Old time can only stay if real slot exists.
# ============================================================

@pytest.mark.asyncio
async def test_date_correction_reloads_slots(
) -> None:

    tools = (
        FakeCorrectionTools()
    )

    workflow = (
        BookingWorkflow(
            tools=tools,
        )
    )

    state = (
        ready_confirmation_state()
    )

    result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "provide_date",

                date_text=
                    "2026-08-28",
            ),
        )
    )

    assert (
        state.slot_date
        == "2026-08-28"
    )

    # Previous time 19:30 is available
    # on corrected date.
    assert (
        state.slot_time
        == "19:30"
    )

    assert (
        state.slot_id
        == "slot-d1-28-1930"
    )

    assert (
        state.stage
        == "awaiting_confirmation"
    )

    assert (
        result.response_type
        == "booking_confirmation"
    )

    slot_calls = [
        kwargs
        for name, kwargs
        in tools.calls
        if name
        == "list_available_slots"
    ]

    assert (
        len(slot_calls)
        == 1
    )

    assert (
        slot_calls[0]["slot_date"]
        == "2026-08-28"
    )


# ============================================================
# TEST 5
#
# TIME CORRECTION
#
# Must select trusted backend slot,
# not simply replace slot_time string.
# ============================================================

@pytest.mark.asyncio
async def test_time_correction_selects_real_available_slot(
) -> None:

    tools = (
        FakeCorrectionTools()
    )

    workflow = (
        BookingWorkflow(
            tools=tools,
        )
    )

    state = (
        ready_confirmation_state()
    )

    result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "provide_time",

                time_text=
                    "17:00",
            ),
        )
    )

    assert (
        state.slot_time
        == "17:00"
    )

    assert (
        state.slot_id
        == "slot-d1-27-1700"
    )

    assert (
        state.slot_date
        == "2026-08-27"
    )

    assert (
        state.stage
        == "awaiting_confirmation"
    )

    assert (
        result.response_type
        == "booking_confirmation"
    )

    slot_calls = [
        kwargs
        for name, kwargs
        in tools.calls
        if name
        == "list_available_slots"
    ]

    assert (
        len(slot_calls)
        == 1
    )


# ============================================================
# TEST 6
#
# MULTIPLE CORRECTIONS IN SAME TURN
#
# name + phone + time
#
# All must apply.
# Phone reconfirmation wins as next stage.
# ============================================================

@pytest.mark.asyncio
async def test_multiple_corrections_are_applied_together(
) -> None:

    tools = (
        FakeCorrectionTools()
    )

    workflow = (
        BookingWorkflow(
            tools=tools,
        )
    )

    state = (
        ready_confirmation_state()
    )

    result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "deny_action",

                confirmation=
                    "no",

                patient_name=
                    "آية محمد",

                phone=
                    "01123456789",

                time_text=
                    "17:00",
            ),
        )
    )

    assert (
        state.patient_name
        == "آية أحمد"
    )

    assert (
        state.phone
        == "01023456789"
    )

    assert (
        state.slot_time
        == "19:30"
    )

    assert (
        state.slot_id
        == "slot-d1-27-1930"
    )

    assert (
        state.stage
        == "awaiting_patient_name_correction"
    )

    assert (
        state.awaiting_confirmation
        is False
    )

    assert (
        state.pending_action
        is None
    )

    assert (
        result.response_type
        == "ask_patient_name_correction"
    )

    assert (
        state.pending_patient_profile_updates
        == {}
    )

    assert (
        tools.calls
        == []
    )



# ============================================================
# TEST 9
#
# SCHEDULE CORRECTION REQUEST WITHOUT NEW VALUE
#
# Real-call bug regression:
#
# "أنا عايزة أغير الميعاد الحالي"
#
# NLU may understand this semantically as provide_date,
# but there is no replacement date/time entity yet.
#
# This MUST NOT cancel the pending booking even if
# confirmation=no is also detected.
# ============================================================

@pytest.mark.asyncio
async def test_schedule_correction_request_without_value_is_not_cancelled(
) -> None:

    tools = (
        FakeCorrectionTools()
    )

    workflow = (
        BookingWorkflow(
            tools=tools,
        )
    )

    state = (
        ready_confirmation_state()
    )

    result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "provide_date",

                confirmation=
                    "no",
            ),
        )
    )

    # Booking draft must remain alive.
    assert (
        state.stage
        == "awaiting_confirmation"
    )

    assert (
        state.awaiting_confirmation
        is True
    )

    assert (
        state.pending_action
        == "create_booking"
    )

    assert (
        result.response_type
        == "ask_schedule_correction"
    )

    assert (
        state.stage
        != "booking_cancelled_before_create"
    )

    # Nothing should be written yet.
    assert tools.calls == []


# ============================================================
# TEST 10
#
# SCHEDULE CORRECTION REQUEST
# → NEW TIME ON NEXT TURN
#
# Turn 1:
#   "عايزة أغير الميعاد"
#
# Turn 2:
#   "خلي الساعة 5"
#
# Must validate a REAL backend slot and then
# return to final confirmation.
# ============================================================

@pytest.mark.asyncio
async def test_schedule_correction_request_can_accept_time_on_next_turn(
) -> None:

    tools = (
        FakeCorrectionTools()
    )

    workflow = (
        BookingWorkflow(
            tools=tools,
        )
    )

    state = (
        ready_confirmation_state()
    )

    # ========================================================
    # TURN 1
    # User asks to change appointment schedule
    # without providing the new value.
    # ========================================================

    first_result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "provide_date",

                confirmation=
                    "no",
            ),
        )
    )

    assert (
        first_result.response_type
        == "ask_schedule_correction"
    )

    assert (
        state.stage
        == "awaiting_confirmation"
    )

    assert (
        state.pending_action
        == "create_booking"
    )

    assert tools.calls == []

    # ========================================================
    # TURN 2
    # User provides new time.
    # ========================================================

    second_result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "provide_time",

                time_text=
                    "17:00",
            ),
        )
    )

    assert (
        state.slot_time
        == "17:00"
    )

    assert (
        state.slot_id
        == "slot-d1-27-1700"
    )

    assert (
        state.slot_date
        == "2026-08-27"
    )

    assert (
        state.stage
        == "awaiting_confirmation"
    )

    assert (
        state.awaiting_confirmation
        is True
    )

    assert (
        state.pending_action
        == "create_booking"
    )

    assert (
        second_result.response_type
        == "booking_confirmation"
    )

    tool_names = [
        name
        for name, _
        in tools.calls
    ]

    assert (
        "list_available_slots"
        in tool_names
    )

    assert (
        "create_booking"
        not in tool_names
    )


# ============================================================
# TEST 11
#
# PHONE CORRECTION REQUEST WITHOUT NEW VALUE
#
# "رقم الموبايل غلط"
#
# Must enter awaiting_phone so Voice Gateway switches
# to protected digit collection.
#
# Important:
# keep the previous phone temporarily so _handle_phone()
# can detect that the replacement value actually changed.
# ============================================================

@pytest.mark.asyncio
async def test_phone_correction_request_moves_to_phone_collection(
) -> None:

    tools = (
        FakeCorrectionTools()
    )

    workflow = (
        BookingWorkflow(
            tools=tools,
        )
    )

    state = (
        ready_confirmation_state()
    )

    previous_phone = (
        state.phone
    )

    result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "provide_phone",

                confirmation=
                    "no",
            ),
        )
    )

    assert (
        state.stage
        == "awaiting_phone"
    )

    assert (
        state.awaiting_confirmation
        is False
    )

    assert (
        state.pending_action
        is None
    )

    assert (
        state.phone_confirmed
        is False
    )

    # Keep previous value until replacement arrives.
    assert (
        state.phone
        == previous_phone
    )

    assert (
        result.response_type
        == "ask_phone_correction"
    )

    assert (
        state.stage
        != "booking_cancelled_before_create"
    )

    assert tools.calls == []


# ============================================================
# TEST 12
#
# FULL PHONE CORRECTION REQUEST FLOW
#
# Turn 1:
#   "رقم الموبايل غلط"
#
# Turn 2:
#   01123456789
#
# Turn 3:
#   "أيوه"
#
# Must:
# - collect protected phone digits
# - read back phone
# - persist only after confirmation
# - return to final booking confirmation
# ============================================================

@pytest.mark.asyncio
async def test_phone_correction_request_full_flow(
) -> None:

    tools = (
        FakeCorrectionTools()
    )

    workflow = (
        BookingWorkflow(
            tools=tools,
        )
    )

    state = (
        ready_confirmation_state()
    )

    # ========================================================
    # TURN 1
    # Request correction
    # ========================================================

    first_result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "provide_phone",

                confirmation=
                    "no",
            ),
        )
    )

    assert (
        first_result.response_type
        == "ask_phone_correction"
    )

    assert (
        state.stage
        == "awaiting_phone"
    )

    assert tools.calls == []

    # ========================================================
    # TURN 2
    # Replacement phone
    # ========================================================

    second_result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "provide_phone",

                phone=
                    "01123456789",
            ),
        )
    )

    assert (
        state.phone
        == "01123456789"
    )

    assert (
        state.phone_confirmed
        is False
    )

    assert (
        state.stage
        == "awaiting_phone_confirmation"
    )

    assert (
        second_result.response_type
        == "phone_confirmation"
    )

    # Still not persisted.
    assert tools.calls == []

    # ========================================================
    # TURN 3
    # Confirm replacement phone
    # ========================================================

    third_result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "confirm_action",

                confirmation=
                    "yes",
            ),
        )
    )

    assert (
        state.phone_confirmed
        is True
    )

    assert (
        state.phone
        == "01123456789"
    )

    assert (
        state.stage
        == "awaiting_confirmation"
    )

    assert (
        state.awaiting_confirmation
        is True
    )

    assert (
        state.pending_action
        == "create_booking"
    )

    assert (
        third_result.response_type
        == "booking_confirmation"
    )

    assert (
        len(
            tools.calls
        )
        == 1
    )

    tool_name, kwargs = (
        tools.calls[0]
    )

    assert (
        tool_name
        == "update_patient_profile"
    )

    assert (
        kwargs["phone"]
        == "01123456789"
    )

    # The backend verifies identity with the patient's national ID.
    assert (
        kwargs["national_id"]
        == "29901010000001"
    )

    assert (
        kwargs["channel"]
        == "voice"
    )


# ============================================================
# TEST 13
#
# DOCTOR CORRECTION REQUEST WITHOUT NEW VALUE
#
# "عايزة أغير الدكتور"
#
# Must ask which doctor instead of treating "لا"
# or correction intent as booking cancellation.
# ============================================================
# ============================================================
# INLINE PHONE CORRECTION
#
# User supplies the replacement phone in the same turn:
# "No, the correct number is ..."
#
# Must:
# - accept the replacement immediately
# - validate it through the normal phone path
# - stay in phone confirmation
# - not ask for the number again
# - make no backend call before confirmation
# ============================================================

@pytest.mark.asyncio
async def test_phone_correction_inline_replacement(
) -> None:

    tools = FakeCorrectionTools()

    workflow = BookingWorkflow(
        tools=tools,
    )

    state = ready_confirmation_state()

    replacement_phone = "01123456789"

    result = await workflow.handle(
        state=state,

        nlu=make_nlu(
            intent="provide_phone",
            phone=replacement_phone,
        ),
    )

    assert (
        state.phone
        == replacement_phone
    )

    assert (
        state.phone_confirmed
        is False
    )

    assert (
        state.stage
        == "awaiting_phone_confirmation"
    )

    assert (
        result.response_type
        == "phone_confirmation"
    )

    assert tools.calls == []
    
@pytest.mark.asyncio
async def test_doctor_correction_request_without_value_is_not_cancelled(
) -> None:

    tools = (
        FakeCorrectionTools()
    )

    workflow = (
        BookingWorkflow(
            tools=tools,
        )
    )

    state = (
        ready_confirmation_state()
    )

    result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "provide_doctor",

                confirmation=
                    "no",
            ),
        )
    )

    assert (
        state.stage
        == "awaiting_confirmation"
    )

    assert (
        state.awaiting_confirmation
        is True
    )

    assert (
        state.pending_action
        == "create_booking"
    )

    assert (
        result.response_type
        == "ask_doctor_correction"
    )

    assert (
        state.stage
        != "booking_cancelled_before_create"
    )

    assert tools.calls == []


# ============================================================
# TEST 14
#
# DOCTOR CORRECTION REQUEST
# → DOCTOR VALUE ON NEXT TURN
#
# Must run the same trusted doctor / slot / service
# validation as a direct correction.
# ============================================================

@pytest.mark.asyncio
async def test_doctor_correction_request_can_accept_doctor_on_next_turn(
) -> None:

    tools = (
        FakeCorrectionTools()
    )

    workflow = (
        BookingWorkflow(
            tools=tools,
        )
    )

    state = (
        ready_confirmation_state()
    )

    # Turn 1
    first_result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "provide_doctor",
            ),
        )
    )

    assert (
        first_result.response_type
        == "ask_doctor_correction"
    )

    # Turn 2
    second_result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "provide_doctor",

                doctor_name=
                    "دكتور منى صلاح",
            ),
        )
    )

    assert (
        state.doctor_id
        == "doctor-2"
    )

    assert (
        state.doctor_name
        == "دكتور منى صلاح"
    )

    assert (
        state.slot_id
        == "slot-d2-27-1930"
    )

    assert (
        state.slot_time
        == "19:30"
    )

    assert (
        state.stage
        == "awaiting_confirmation"
    )

    assert (
        second_result.response_type
        == "booking_confirmation"
    )

    tool_names = [
        name
        for name, _
        in tools.calls
    ]

    assert (
        "list_doctors"
        in tool_names
    )

    assert (
        "list_available_slots"
        in tool_names
    )

    assert (
        "list_services"
        in tool_names
    )

    assert (
        "create_booking"
        not in tool_names
    )


# ============================================================
# TEST 15
#
# PATIENT NAME CORRECTION REQUEST WITHOUT NEW VALUE
#
# "الاسم غلط"
#
# Must ask for the correct patient name,
# not cancel the booking.
# ============================================================

@pytest.mark.asyncio
async def test_patient_name_correction_request_without_value_is_not_cancelled(
) -> None:

    tools = (
        FakeCorrectionTools()
    )

    workflow = (
        BookingWorkflow(
            tools=tools,
        )
    )

    state = (
        ready_confirmation_state()
    )

    result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "provide_patient_name",

                confirmation=
                    "no",
            ),
        )
    )

    assert (
        state.stage
        == "awaiting_patient_name_correction"
    )

    assert (
        state.awaiting_confirmation
        is False
    )

    assert (
        state.pending_action
        is None
    )

    assert (
        result.response_type
        == "ask_patient_name_correction"
    )

    assert (
        state.stage
        != "booking_cancelled_before_create"
    )

    assert tools.calls == []


# ============================================================
# TEST 16
#
# PATIENT NAME CORRECTION REQUEST
# → NAME VALUE ON NEXT TURN
# ============================================================

@pytest.mark.asyncio
async def test_patient_name_correction_request_can_accept_name_on_next_turn(
) -> None:

    tools = (
        FakeCorrectionTools()
    )

    workflow = (
        BookingWorkflow(
            tools=tools,
        )
    )

    state = (
        ready_confirmation_state()
    )

    # Turn 1
    first_result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "provide_patient_name",
            ),
        )
    )

    assert (
        first_result.response_type
        == "ask_patient_name_correction"
    )

    # Turn 2
    second_result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "provide_patient_name",

                patient_name=
                    "آية محمد",
            ),
        )
    )

    assert (
        state.patient_name
        == "آية محمد"
    )

    assert (
        state.stage
        == "awaiting_confirmation"
    )

    assert (
        second_result.response_type
        == "booking_confirmation"
    )

    assert (
        tools.calls
        == []
    )

    assert (
        state.pending_patient_profile_updates[
            "patient_name"
        ]
        == "آية محمد"
    )

    assert (
        "create_booking"
        not in [
            name
            for name, _
            in tools.calls
        ]
    )

    assert (
        "create_booking"
        not in [
            name
            for name, _
            in tools.calls
        ]
    )


# ============================================================
# TEST 17
#
# NATIONAL ID CORRECTION REQUEST
#
# National ID is identity, not just a display field.
# A correction must invalidate the current resolved patient
# and restart identity collection.
# ============================================================

@pytest.mark.asyncio
async def test_national_id_correction_restarts_patient_identity(
) -> None:

    tools = (
        FakeCorrectionTools()
    )

    workflow = (
        BookingWorkflow(
            tools=tools,
        )
    )

    state = (
        ready_confirmation_state()
    )

    result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "provide_national_id",

                confirmation=
                    "no",
            ),
        )
    )

    assert (
        state.stage
        == "awaiting_national_id"
    )

    assert (
        state.national_id
        is None
    )

    assert (
        state.patient_id
        is None
    )

    assert (
        state.patient_name
        is None
    )

    assert (
        state.phone
        is None
    )

    assert (
        state.phone_confirmed
        is False
    )

    assert (
        state.awaiting_confirmation
        is False
    )

    assert (
        state.pending_action
        is None
    )

    assert (
        result.response_type
        == "ask_national_id_correction"
    )

    assert (
        state.stage
        != "booking_cancelled_before_create"
    )

    assert tools.calls == []
# ============================================================
# TEST 7
#
# PURE DENY
#
# If user provides NO replacement entity,
# it is still a real rejection.
# ============================================================

@pytest.mark.asyncio
async def test_pure_deny_still_rejects_pending_booking(
) -> None:

    tools = (
        FakeCorrectionTools()
    )

    workflow = (
        BookingWorkflow(
            tools=tools,
        )
    )

    state = (
        ready_confirmation_state()
    )

    result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "deny_action",

                confirmation=
                    "no",
            ),
        )
    )

    assert (
        state.stage
        == "booking_cancelled_before_create"
    )

    assert (
        state.awaiting_confirmation
        is False
    )

    assert (
        state.pending_action
        is None
    )

    assert (
        result.response_type
        == "booking_not_confirmed"
    )

    assert tools.calls == []




@pytest.mark.asyncio
async def test_confirmed_corrected_phone_is_persisted(
) -> None:

    tools = (
        FakeCorrectionTools()
    )

    workflow = (
        BookingWorkflow(
            tools=tools,
        )
    )

    state = (
        ready_confirmation_state()
    )

    # ========================================================
    # TURN 1
    # User corrects phone
    # ========================================================

    first_result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "provide_phone",

                phone=
                    "01123456789",
            ),
        )
    )

    assert (
        first_result.response_type
        == "phone_confirmation"
    )

    assert (
        state.phone
        == "01123456789"
    )

    assert (
        state.phone_confirmed
        is False
    )

    # Critical:
    # DB must NOT be updated before confirmation.
    assert tools.calls == []

    # ========================================================
    # TURN 2
    # User confirms corrected phone
    # ========================================================

    second_result = await (
        workflow.handle(
            state=state,

            nlu=make_nlu(
                intent=
                    "confirm_action",

                confirmation=
                    "yes",
            ),
        )
    )

    assert (
        state.phone_confirmed
        is True
    )

    assert (
        state.phone
        == "01123456789"
    )

    assert (
        state.stage
        == "awaiting_confirmation"
    )

    assert (
        second_result.response_type
        == "booking_confirmation"
    )

    assert (
        len(
            tools.calls
        )
        == 1
    )

    tool_name, kwargs = (
        tools.calls[0]
    )

    assert (
        tool_name
        == "update_patient_profile"
    )

    assert (
        kwargs[
            "phone"
        ]
        == "01123456789"
    )

    assert (
        kwargs[
            "channel"
        ]
        == "voice"
    )

    assert (
        state.pending_patient_profile_updates
        == {}
    )   

# ============================================================
# REGRESSION
#
# STT GARBAGE MUST NOT OVERWRITE CONFIRMED PATIENT NAME
#
# Real-call regression:
#
# Existing confirmed name:
#     "آية أحمد"
#
# STT accidentally produced:
#     "كدخل"
#
# NLU may still classify it as provide_patient_name.
#
# A one-word noisy transcript must NOT overwrite
# the trusted patient name during final confirmation.
# ============================================================

@pytest.mark.asyncio
async def test_stt_garbage_does_not_overwrite_patient_name(
) -> None:

    tools = (
        FakeCorrectionTools()
    )

    workflow = (
        BookingWorkflow(
            tools=tools,
        )
    )

    state = (
        ready_confirmation_state()
    )

    original_name = (
        state.patient_name
    )

    result = await (
        workflow.handle(
            state=state,

            user_message=
                "كدخل",

            nlu=make_nlu(
                intent=
                    "provide_patient_name",

                patient_name=
                    "كدخل",
            ),
        )
    )

    # Existing trusted name must survive.
    assert (
        state.patient_name
        == original_name
    )

    assert (
        state.patient_name
        == "آية أحمد"
    )

    # Booking confirmation must remain active.
    assert (
        state.stage
        == "awaiting_patient_name_correction"
    )

    assert (
        state.awaiting_confirmation
        is False
    )

    assert (
        state.pending_action
        is None
    )

    # Do not persist garbage to DB.
    assert (
        state.pending_patient_profile_updates
        == {}
    )

    assert (
        tools.calls
        == []
    )

    assert (
        result.response_type
        == "ask_patient_name_correction"
    ) 


@pytest.mark.asyncio
async def test_patient_name_correction_sentence_requires_clean_name_turn(
) -> None:

    tools = FakeCorrectionTools()

    workflow = BookingWorkflow(
        tools=tools,
    )

    state = ready_confirmation_state()

    original_name = state.patient_name

    result = await workflow.handle(
        state=state,

        user_message=
            "لا، اسم الوليد آية أحمد",

        nlu=make_nlu(
            intent=
                "provide_patient_name",

            confirmation=
                "no",

            patient_name=
                "الوليد آية أحمد",
        ),
    )

    # Do not trust the name extracted from
    # the correction sentence itself.
    assert (
        state.patient_name
        == original_name
    )

    assert (
        state.stage
        == "awaiting_patient_name_correction"
    )

    assert (
        state.awaiting_confirmation
        is False
    )

    assert (
        state.pending_action
        is None
    )

    assert (
        state.pending_patient_profile_updates
        == {}
    )

    assert (
        result.response_type
        == "ask_patient_name_correction"
    )

    assert tools.calls == []    