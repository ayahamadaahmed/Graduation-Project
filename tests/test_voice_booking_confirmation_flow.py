from __future__ import annotations

import pytest

from medmind.state.models import SessionState
from medmind.understanding.types import (
    NLUEntities,
    NLUResult,
)
from medmind.workflows.booking import (
    BookingWorkflow,
)


# ============================================================
# FAKE MCP TOOLS
# ============================================================

class FakeTools:

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
        # Existing patient lookup
        # ----------------------------------------------------

        if name == "lookup_patient":

            return {
                "found": True,

                "patient": {
                    "patient_id":
                        "patient-1",

                    "display_name":
                        "آية أحمد",

                    "phone":
                        "01023456789",
                },
            }


        # ----------------------------------------------------
        # New patient resolution
        # ----------------------------------------------------

        if name == "resolve_patient":

            return {
                "patient": {
                    "id":
                        "patient-2",

                    "full_name_ar":
                        "آية أحمد",

                    "full_name_en":
                        None,

                    "phone":
                        kwargs["phone"],
                }
            }


        # ----------------------------------------------------
        # Create booking
        # ----------------------------------------------------

        if name == "create_booking":

            return {
                "appointment_reference":
                    "APT-260827-TEST1234"
            }


        raise AssertionError(
            f"Unexpected tool call: {name}"
        )


# ============================================================
# NLU FACTORY
# ============================================================

def nlu(
    *,
    intent: str = "unknown",
    confirmation: str = "unknown",
    **entities,
) -> NLUResult:

    return NLUResult(
        intent=intent,

        confirmation=
            confirmation,

        confidence=1.0,

        entities=NLUEntities(
            **entities
        ),
    )


# ============================================================
# VOICE STATE FACTORY
# ============================================================

def ready_voice_state(
    *,
    patient_id: str | None = None,
) -> SessionState:

    return SessionState(
        session_id=
            "voice-test",

        tenant_id=
            "clinic-001",

        language=
            "ar",

        channel=
            "voice",

        operation_type=
            "book_appointment",

        stage=
            "awaiting_phone",

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
            "slot-1",

        slot_date=
            "2026-08-27",

        slot_time=
            "19:30",

        national_id=
            "29901010000001",

        patient_id=
            patient_id,

        patient_name=
            "آية أحمد",
    )


# ============================================================
# TEST 1
#
# Existing patient must still confirm stored phone on Voice
# ============================================================

@pytest.mark.asyncio
async def test_existing_voice_patient_must_confirm_saved_phone(
) -> None:

    tools = FakeTools()

    workflow = BookingWorkflow(
        tools=tools,
    )

    state = ready_voice_state()

    state.stage = (
        "awaiting_national_id"
    )

    state.patient_name = None
    state.phone = None
    state.patient_id = None


    result = await workflow.handle(
        state=state,

        nlu=nlu(
            intent=
                "provide_national_id",

            national_id=
                "29901010000001",
        ),
    )


    assert (
        state.stage
        == "awaiting_phone_confirmation"
    )

    assert (
        state.patient_id
        == "patient-1"
    )

    assert (
        state.phone
        == "01023456789"
    )

    assert (
        state.phone_confirmed
        is False
    )

    assert (
        result.response_type
        == "phone_confirmation"
    )

    assert (
        "صفر واحد صفر"
        in result.reply
    )

    assert (
        "اتنين تلاتة أربعة"
        in result.reply
    )


# ============================================================
# TEST 2
#
# Phone must not resolve patient before caller confirms it
# ============================================================

@pytest.mark.asyncio
async def test_voice_phone_is_not_resolved_before_confirmation(
) -> None:

    tools = FakeTools()

    workflow = BookingWorkflow(
        tools=tools,
    )

    state = ready_voice_state()


    result = await workflow.handle(
        state=state,

        nlu=nlu(
            intent=
                "provide_phone",

            phone=
                "01023456789",
        ),
    )


    assert (
        result.response_type
        == "phone_confirmation"
    )

    assert (
        state.stage
        == "awaiting_phone_confirmation"
    )

    assert (
        state.phone_confirmed
        is False
    )

    # No MCP/backend call should happen yet.
    assert tools.calls == []


# ============================================================
# TEST 3
#
# Wrong phone → clear it and collect again
# ============================================================

@pytest.mark.asyncio
async def test_wrong_voice_phone_restarts_collection(
) -> None:

    tools = FakeTools()

    workflow = BookingWorkflow(
        tools=tools,
    )

    state = ready_voice_state()

    state.stage = (
        "awaiting_phone_confirmation"
    )

    state.phone = (
        "01023456789"
    )


    result = await workflow.handle(
        state=state,

        nlu=nlu(
            intent=
                "deny_action",

            confirmation=
                "no",
        ),
    )


    assert (
        result.response_type
        == "ask_phone_again"
    )

    assert (
        state.stage
        == "awaiting_phone"
    )

    assert (
        state.phone
        is None
    )

    assert (
        state.phone_confirmed
        is False
    )


# ============================================================
# TEST 4
#
# Confirmed phone → resolve patient → short confirmation
# ============================================================

@pytest.mark.asyncio
async def test_confirmed_new_patient_phone_prepares_short_voice_summary(
) -> None:

    tools = FakeTools()

    workflow = BookingWorkflow(
        tools=tools,
    )

    state = ready_voice_state()

    state.stage = (
        "awaiting_phone_confirmation"
    )

    state.phone = (
        "01023456789"
    )


    result = await workflow.handle(
        state=state,

        nlu=nlu(
            intent=
                "confirm_action",

            confirmation=
                "yes",
        ),
    )


    assert (
        state.phone_confirmed
        is True
    )

    assert (
        state.patient_id
        == "patient-2"
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


    # --------------------------------------------------------
    # Voice confirmation must include only critical fields
    # --------------------------------------------------------

    assert (
        "آية أحمد"
        in result.reply
    )

    assert (
        "دكتور ماهر محمود"
        in result.reply
    )

    assert (
        "2026-08-27"
        in result.reply
    )

    assert (
        "19:30"
        in result.reply
    )


    # Service should not be read in short Voice confirmation.
    assert (
        "الخدمة"
        not in result.reply
    )


    # --------------------------------------------------------
    # Check MCP call
    # --------------------------------------------------------

    assert (
        tools.calls[0][0]
        == "resolve_patient"
    )

    assert (
        tools.calls[0][1]["channel"]
        == "voice"
    )


# ============================================================
# TEST 5
#
# Booking executes only after BOTH confirmations:
#
# 1. phone confirmed
# 2. booking confirmed
# ============================================================

@pytest.mark.asyncio
async def test_booking_executes_only_after_phone_and_booking_confirmation(
) -> None:

    tools = FakeTools()

    workflow = BookingWorkflow(
        tools=tools,
    )

    state = ready_voice_state(
        patient_id="patient-1",
    )

    state.phone = (
        "01023456789"
    )

    state.phone_confirmed = True

    state.stage = (
        "awaiting_confirmation"
    )

    state.awaiting_confirmation = True

    state.pending_action = (
        "create_booking"
    )


    result = await workflow.handle(
        state=state,

        nlu=nlu(
            intent=
                "confirm_action",

            confirmation=
                "yes",
        ),
    )


    assert (
        state.stage
        == "booking_completed"
    )

    assert (
        state.appointment_reference
        == "APT-260827-TEST1234"
    )

    assert (
        result.response_type
        == "booking_created"
    )


    # Voice should mention WhatsApp.
    assert (
        "واتساب"
        in result.reply
    )


    # But should NOT read long booking reference aloud.
    assert (
        "APT-260827-TEST1234"
        not in result.reply
    )


    # --------------------------------------------------------
    # Make sure backend was called using Voice channel
    # --------------------------------------------------------

    create_call = next(
        call
        for call in tools.calls
        if call[0]
        == "create_booking"
    )


    assert (
        create_call[1]["channel"]
        == "voice"
    )


@pytest.mark.asyncio
async def test_phone_correction_request_during_confirmation_restarts_collection(
) -> None:

    tools = FakeTools()

    workflow = BookingWorkflow(
        tools=tools,
    )

    state = ready_voice_state()

    state.stage = (
        "awaiting_phone_confirmation"
    )

    state.phone = (
        "01023456789"
    )

    state.phone_confirmed = False

    result = await workflow.handle(
        state=state,

        nlu=nlu(
            intent=
                "provide_phone",
        ),
    )

    assert (
        result.response_type
        == "ask_phone_correction"
    )

    assert (
        state.stage
        == "awaiting_phone"
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