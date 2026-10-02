from types import SimpleNamespace

import pytest

from medmind.resolvers.date import (
    resolve_date,
)

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

class FakeTools:

    def __init__(self):

        self.calls = []

    async def call(
        self,
        tool_name: str,
        **kwargs,
    ):

        self.calls.append(
            (
                tool_name,
                kwargs,
            )
        )

        if tool_name == "list_specialties":

            return [
                {
                    "id": "specialty-derma",
                    "name_ar": "جلدية",
                    "name_en": "Dermatology",
                    "code": "DERMA",
                }
            ]

        if tool_name == "list_doctors":

            return [
                {
                    "id": "doctor-maher",
                    "full_name_ar":
                        "دكتور ماهر",
                    "full_name_en":
                        "Dr Maher",
                },
                {
                    "id": "doctor-mahmoud",
                    "full_name_ar":
                        "دكتور محمود",
                    "full_name_en":
                        "Dr Mahmoud",
                },
            ]

        if tool_name == "list_available_slots":

            return [
                {
                    "id": "slot-1",
                    "slot_date":
                        kwargs["slot_date"],
                    "start_time": "17:00:00",
                },
                {
                    "id": "slot-2",
                    "slot_date":
                        kwargs["slot_date"],
                    "start_time": "18:00:00",
                },
                {
                    "id": "slot-3",
                    "slot_date":
                        kwargs["slot_date"],
                    "start_time": "14:00:00",
                },
            ]

        if tool_name == "list_services":

            return [
                {
                    "id": "service-exam",
                    "name_ar": "كشف",
                    "name_en": "Examination",
                    "code": "EXAM",
                }
            ]

        raise AssertionError(
            f"Unexpected tool: {tool_name}"
        )


# ============================================================
# FAKE APPLY TOOL OBSERVATION
#
# We only need the fields BookingWorkflow reads.
# ============================================================

def fake_apply_tool_observation(
    *,
    state,
    tool_name,
    data,
):

    if tool_name == "list_doctors":

        state.recent_doctors = [
            SimpleNamespace(
                id=item["id"],
                full_name_ar=
                    item["full_name_ar"],
                full_name_en=
                    item["full_name_en"],
            )
            for item in data
        ]

    elif (
        tool_name
        == "list_available_slots"
    ):

        state.recent_slots = [
            SimpleNamespace(
                id=item["id"],
                slot_date=
                    item["slot_date"],
                start_time=
                    item["start_time"],
            )
            for item in data
        ]

    elif (
        tool_name
        == "list_services"
    ):

        state.recent_services = [
            SimpleNamespace(
                id=item["id"],
                name_ar=
                    item["name_ar"],
                name_en=
                    item["name_en"],
                code=
                    item["code"],
            )
            for item in data
        ]    


# ============================================================
# HELPERS
# ============================================================

def make_nlu(
    *,
    intent,
    operation_type=None,
    specialty_name=None,
    doctor_name=None,
    service_name=None,
    date_text=None,
    time_text=None,
):

    return NLUResult(
        intent=intent,

        operation_type=
            operation_type,

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
# BOOKING SLOT-FILLING INTEGRATION
# ============================================================

@pytest.mark.asyncio
async def test_booking_keeps_date_while_asking_for_doctor(
    monkeypatch,
):

    # --------------------------------------------------------
    # Replace imported updater with controlled test version.
    # --------------------------------------------------------

    monkeypatch.setattr(
        "medmind.workflows.booking.apply_tool_observation",
        fake_apply_tool_observation,
    )

    tools = FakeTools()

    workflow = BookingWorkflow(
        tools=tools,
    )

    state = SessionState(
        channel="web",
        session_id=
            "booking-slot-test",

        tenant_id=
            "tenant-test",

        language="ar",
    )

    # ========================================================
    # TURN 1
    #
    # "عايز أحجز جلدية بكرة"
    # ========================================================

    first_nlu = make_nlu(
        intent=
            "book_appointment",

        operation_type=
            "book_appointment",

        specialty_name=
            "جلدية",

        date_text=
            "بكرة",
    )

    first_result = await (
        workflow.handle(
            state=state,
            nlu=first_nlu,
            user_message=
                "عايز أحجز جلدية بكرة",
        )
    )

    # More than one doctor exists,
    # therefore doctor clarification is correct.

    assert (
        first_result.response_type
        == "ask_doctor"
    )

    assert (
        state.stage
        == "awaiting_doctor"
    )

    # Critical:
    # the original date must survive.

    assert (
        state
        .pending_operation_entities[
            "date_text"
        ]
        == "بكرة"
    )

    # ========================================================
    # TURN 2
    #
    # User supplies ONLY doctor.
    # ========================================================

    second_nlu = make_nlu(
        intent=
            "provide_doctor",

        doctor_name=
            "دكتور ماهر",
    )

    second_result = await (
        workflow.handle(
            state=state,
            nlu=second_nlu,
            user_message=
                "دكتور ماهر",
        )
    )

    tomorrow = (
        resolve_date(
            "بكرة"
        )
    )

    assert tomorrow is not None

    tomorrow_text = (
        tomorrow.isoformat()
    )

    # ========================================================
    # SHOULD NOT ASK DATE AGAIN
    # ========================================================

    assert (
        second_result.response_type
        != "ask_date"
    )

    # Because no time was provided,
    # next missing slot should be TIME.

    assert (
        second_result.response_type
        == "ask_time"
    )

    assert (
        state.stage
        == "awaiting_time"
    )

    # Trusted doctor resolved.

    assert (
        state.doctor_id
        == "doctor-maher"
    )

    assert (
        state.doctor_name
        == "دكتور ماهر"
    )

    # Original "بكرة" was consumed
    # into trusted ISO slot date.

    assert (
        state.slot_date
        == tomorrow_text
    )

    # Backend slots must have been requested
    # using the preserved date.

    slot_calls = [
        kwargs
        for tool_name, kwargs
        in tools.calls
        if (
            tool_name
            == "list_available_slots"
        )
    ]

    assert len(
        slot_calls
    ) == 1

    assert (
        slot_calls[0][
            "doctor_id"
        ]
        == "doctor-maher"
    )

    assert (
        slot_calls[0][
            "slot_date"
        ]
        == tomorrow_text
    )

@pytest.mark.asyncio
async def test_booking_new_specialty_does_not_reuse_old_conversation_doctor(
    monkeypatch,
):

    monkeypatch.setattr(
        "medmind.workflows.booking.apply_tool_observation",
        fake_apply_tool_observation,
    )

    tools = FakeTools()

    workflow = BookingWorkflow(
        tools=tools,
    )

    state = SessionState(
        channel="web",
        session_id=
            "booking-stale-context-test",

        tenant_id=
            "tenant-test",

        language="ar",

        # ----------------------------------------------------
        # OLD CONVERSATION CONTEXT
        # ----------------------------------------------------

        conversation_specialty_name=
            "قلب",

        conversation_specialty_id=
            "specialty-cardio",

        conversation_doctor_name=
            "دكتور ماهر",

        conversation_doctor_id=
            "doctor-old-ahmed",
    )

    # ========================================================
    # NEW REQUEST
    #
    # User explicitly changes specialty.
    # Doctor from old specialty must NOT be inherited.
    # ========================================================

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

    result = await (
        workflow.handle(
            state=state,
            nlu=nlu,
            user_message=
                "عايز أحجز جلدية بكرة",
        )
    )

    # ========================================================
    # SHOULD ASK FOR DOCTOR
    # ========================================================

    assert (
        result.response_type
        == "ask_doctor"
    )

    assert (
        state.stage
        == "awaiting_doctor"
    )

    # ========================================================
    # OLD DOCTOR MUST NOT LEAK INTO NEW BOOKING
    # ========================================================

    assert (
        state.doctor_id
        is None
    )

    assert (
        state.doctor_name
        is None
    )

    # ========================================================
    # NEW SPECIALTY SHOULD BE TRUSTED/RESOLVED
    # ========================================================

    assert (
        state.specialty_id
        == "specialty-derma"
    )

    assert (
        state.specialty_name
        == "جلدية"
    )

    # Date still preserved while waiting for doctor.
    assert (
        state
        .pending_operation_entities[
            "date_text"
        ]
        == "بكرة"
    )

    # No slot lookup should happen before doctor selection.
    slot_calls = [
        call
        for call in tools.calls
        if (
            call[0]
            == "list_available_slots"
        )
    ]

    assert (
        slot_calls
        == []
    )    

@pytest.mark.asyncio
async def test_booking_consumes_full_multi_entity_turn(
    monkeypatch,
):

    monkeypatch.setattr(
        "medmind.workflows.booking.apply_tool_observation",
        fake_apply_tool_observation,
    )

    tools = FakeTools()

    workflow = BookingWorkflow(
        tools=tools,
    )

    state = SessionState(
        channel="web",
        session_id=
            "booking-full-turn-test",

        tenant_id=
            "tenant-test",

        language="ar",
    )

    # ========================================================
    # ONE USER TURN
    #
    # specialty + doctor + date + time + service
    # ========================================================

    nlu = make_nlu(
        intent=
            "book_appointment",

        operation_type=
            "book_appointment",

        specialty_name=
            "جلدية",

        doctor_name=
            "دكتور ماهر",

        service_name=
            "كشف",

        date_text=
            "بكرة",

        time_text=
            "الساعة 5",
    )

    result = await (
        workflow.handle(
            state=state,
            nlu=nlu,
            user_message=(
                "عايز أحجز كشف جلدية "
                "مع دكتور أحمد بكرة الساعة 5"
            ),
        )
    )

    # ========================================================
    # SHOULD SKIP:
    #
    # ask_specialty
    # ask_doctor
    # ask_date
    # ask_time
    # ask_service
    #
    # First genuinely missing field is patient identity.
    # ========================================================

    assert (
        result.response_type
        == "ask_national_id"
    )

    assert (
        state.stage
        == "awaiting_national_id"
    )

    # ========================================================
    # TRUSTED PROVIDER DATA
    # ========================================================

    assert (
        state.specialty_id
        == "specialty-derma"
    )

    assert (
        state.specialty_name
        == "جلدية"
    )

    assert (
        state.doctor_id
        == "doctor-maher"
    )

    assert (
        state.doctor_name
        == "دكتور ماهر"
    )

    # ========================================================
    # TRUSTED SLOT
    # ========================================================

    tomorrow = (
        resolve_date(
            "بكرة"
        )
    )

    assert tomorrow is not None

    assert (
        state.slot_date
        == tomorrow.isoformat()
    )

    assert (
        state.slot_id
        == "slot-1"
    )

    assert (
        state.slot_time
        == "17:00"
    )

    # ========================================================
    # TRUSTED SERVICE
    # ========================================================

    assert (
        state.service_id
        == "service-exam"
    )

    assert (
        state.service_name
        == "كشف"
    )

    # ========================================================
    # EXPECTED BACKEND CHAIN
    # ========================================================

    tool_names = [
        tool_name
        for tool_name, _
        in tools.calls
    ]

    assert tool_names == [
        "list_specialties",
        "list_doctors",
        "list_available_slots",
        "list_services",
    ]    


@pytest.mark.asyncio
async def test_booking_reuses_read_slots_context_when_user_says_book_that_time(
    monkeypatch,
):

    monkeypatch.setattr(
        "medmind.workflows.booking.apply_tool_observation",
        fake_apply_tool_observation,
    )

    tools = FakeTools()

    workflow = BookingWorkflow(
        tools=tools,
    )

    # ========================================================
    # PREVIOUS READ TURN
    #
    # Represents:
    #
    # "مواعيد دكتور أحمد بعد بكرة"
    #
    # The available-slots direct handler has already resolved
    # and saved trusted provider/date context.
    # ========================================================

    after_tomorrow = (
        resolve_date(
            "بعد بكرة"
        )
    )

    assert after_tomorrow is not None

    after_tomorrow_text = (
        after_tomorrow.isoformat()
    )

    state = SessionState(
        channel="web",

        session_id=
            "booking-read-handoff-test",

        tenant_id=
            "tenant-test",

        language="ar",

        # ----------------------------------------------------
        # TRUSTED SPECIALTY FROM PREVIOUS DOCTOR LOOKUP
        # ----------------------------------------------------

        conversation_specialty_id=
            "specialty-derma",

        conversation_specialty_name=
            "جلدية",

        # ----------------------------------------------------
        # TRUSTED DOCTOR FROM PREVIOUS READ TURN
        # ----------------------------------------------------

        conversation_doctor_id=
            "doctor-maher",

        conversation_doctor_name=
            "دكتور ماهر",

        # ----------------------------------------------------
        # TRUSTED DATE FROM:
        #
        # "بعد بكرة"
        # ----------------------------------------------------

        conversation_date_text=
            after_tomorrow_text,

        # Date inheritance is only allowed from a relevant
        # scheduling/read capability.
        conversation_focus_capability=
            "provider.get_slots",
    )

    # ========================================================
    # CURRENT TURN
    #
    # User gives ONLY the new booking action + time.
    #
    # "احجزلي الساعة 2"
    # ========================================================

    nlu = make_nlu(
        intent=
            "book_appointment",

        operation_type=
            "book_appointment",

        time_text=
            "الساعة 2",
    )

    result = await (
        workflow.handle(
            state=state,
            nlu=nlu,
            user_message=
                "احجزلي الساعة 2",
        )
    )

    # ========================================================
    # MUST NOT ASK AGAIN FOR KNOWN CONTEXT
    # ========================================================

    assert (
        result.response_type
        != "ask_specialty"
    )

    assert (
        result.response_type
        != "ask_doctor"
    )

    assert (
        result.response_type
        != "ask_date"
    )

    assert (
        result.response_type
        != "ask_time"
    )

    # ========================================================
    # ONE SERVICE EXISTS
    #
    # Therefore the next genuinely missing field should be
    # patient identity.
    # ========================================================

    assert (
        result.response_type
        == "ask_national_id"
    )

    assert (
        state.stage
        == "awaiting_national_id"
    )

    # ========================================================
    # PREVIOUS TRUSTED PROVIDER CONTEXT REUSED
    # ========================================================

    assert (
        state.specialty_id
        == "specialty-derma"
    )

    assert (
        state.specialty_name
        == "جلدية"
    )

    assert (
        state.doctor_id
        == "doctor-maher"
    )

    assert (
        state.doctor_name
        == "دكتور ماهر"
    )

    # ========================================================
    # PREVIOUS DATE REUSED
    # ========================================================

    assert (
        state.slot_date
        == after_tomorrow_text
    )

    # ========================================================
    # CURRENT TIME MUST WIN
    #
    # "الساعة 2" should match the available 14:00 slot.
    # ========================================================

    assert (
        state.slot_id
        == "slot-3"
    )

    assert (
        state.slot_time
        == "14:00"
    )

    # ========================================================
    # SERVICE AUTO SELECTED
    # ========================================================

    assert (
        state.service_id
        == "service-exam"
    )

    assert (
        state.service_name
        == "كشف"
    )

    # ========================================================
    # BACKEND CHAIN
    #
    # Even though values came from conversation context,
    # they are still validated against trusted backend data.
    # ========================================================

    tool_names = [
        tool_name
        for tool_name, _
        in tools.calls
    ]

    assert tool_names == [
        "list_specialties",
        "list_doctors",
        "list_available_slots",
        "list_services",
    ]

    # ========================================================
    # CRITICAL:
    # SLOT LOOKUP MUST USE BOTH THE PREVIOUS DOCTOR AND DATE.
    # ========================================================

    slot_calls = [
        kwargs
        for tool_name, kwargs
        in tools.calls
        if (
            tool_name
            == "list_available_slots"
        )
    ]

    assert (
        len(
            slot_calls
        )
        == 1
    )

    assert (
        slot_calls[0][
            "doctor_id"
        ]
        == "doctor-maher"
    )

    assert (
        slot_calls[0][
            "slot_date"
        ]
        == after_tomorrow_text
    )    