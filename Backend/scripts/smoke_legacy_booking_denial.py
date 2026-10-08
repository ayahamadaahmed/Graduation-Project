from __future__ import annotations

import asyncio
import json
import os

from dotenv import (
    load_dotenv,
)

from langchain_openai import (
    ChatOpenAI,
)

from langchain_mcp_adapters.client import (
    MultiServerMCPClient,
)

from medmind.core.tool_executor import (
    MCPToolExecutor,
)

from medmind.language import (
    detect_language,
)

from medmind.memory.models import (
    ChatMessage,
)

from medmind.state.models import (
    SessionState,
)

from medmind.understanding.llm import (
    LLMNLU,
)

from medmind.workflows.booking import (
    BookingWorkflow,
)


# ============================================================
# PRINT STATE
# ============================================================

def print_state(
    state: SessionState,
) -> None:

    print()
    print(
        "STATE:"
    )

    print(
        json.dumps(
            state.model_dump(),
            ensure_ascii=False,
            indent=2,
        )
    )


# ============================================================
# ADD TURN TO HISTORY
# ============================================================

def add_to_history(
    *,
    history: list[ChatMessage],
    user_message: str,
    assistant_message: str,
) -> None:

    history.append(
        ChatMessage(
            role="user",
            content=user_message,
        )
    )

    history.append(
        ChatMessage(
            role="assistant",
            content=assistant_message,
        )
    )


# ============================================================
# MAIN
# ============================================================

async def main() -> None:

    load_dotenv(
        override=True
    )

    model_name = os.getenv(
        "OPENAI_MODEL",
        "gpt-4.1",
    )

    mcp_url = os.getenv(
        "MCP_URL",
        "http://127.0.0.1:9000/mcp",
    )

    tenant_id = os.getenv(
        "TENANT_ID",
        "clinic-001",
    )

    # --------------------------------------------------------
    # LLM
    # --------------------------------------------------------

    model = ChatOpenAI(
        model=model_name,
        temperature=0,
        timeout=60,
    )

    nlu = LLMNLU(
        model=model
    )

    # --------------------------------------------------------
    # MCP
    # --------------------------------------------------------

    client = MultiServerMCPClient(
        {
            "healthcare": {
                "transport":
                    "http",

                "url":
                    mcp_url,

                "headers": {
                    "X-Tenant-ID":
                        tenant_id,
                },
            }
        }
    )

    mcp_tools = await (
        client.get_tools()
    )

    tools = MCPToolExecutor(
        mcp_tools
    )

    # --------------------------------------------------------
    # Workflow
    # --------------------------------------------------------

    workflow = BookingWorkflow(
        tools=tools
    )

    # --------------------------------------------------------
    # State
    # --------------------------------------------------------

    state = SessionState(
        session_id=
            "booking-denial-test-001",

        tenant_id=
            tenant_id,
    )

    history: list[
        ChatMessage
    ] = []

    # ========================================================
    # TURN 1 - START BOOKING
    # ========================================================

    message = (
        "عايزة احجز جلدية"
    )

    language = detect_language(
        message
    )

    state.language = language

    nlu_result = await nlu.understand(
        message=message,
        language=state.language,
        state=state,
        history=history,
    )

    print()
    print("=" * 70)
    print("TURN 1 - START BOOKING")
    print("=" * 70)

    print(
        "USER:",
        message,
    )

    print(
        "NLU:"
    )

    print(
        json.dumps(
            nlu_result.model_dump(),
            ensure_ascii=False,
            indent=2,
        )
    )

    workflow_result = await workflow.handle(
        state=state,
        nlu=nlu_result,
    )

    print()
    print(
        "MEDMIND:",
        workflow_result.reply,
    )

    print_state(
        state
    )

    add_to_history(
        history=history,
        user_message=message,
        assistant_message=
            workflow_result.reply,
    )

    assert (
        state.operation_type
        == "book_appointment"
    )

    assert (
        state.stage
        == "awaiting_doctor"
    )

    # ========================================================
    # TURN 2 - SELECT DOCTOR
    # ========================================================

    message = "منى"

    nlu_result = await nlu.understand(
        message=message,
        language=state.language,
        state=state,
        history=history,
    )

    print()
    print("=" * 70)
    print("TURN 2 - SELECT DOCTOR")
    print("=" * 70)

    print(
        "USER:",
        message,
    )

    print(
        "NLU:"
    )

    print(
        json.dumps(
            nlu_result.model_dump(),
            ensure_ascii=False,
            indent=2,
        )
    )

    workflow_result = await workflow.handle(
        state=state,
        nlu=nlu_result,
    )

    print()
    print(
        "MEDMIND:",
        workflow_result.reply,
    )

    print_state(
        state
    )

    add_to_history(
        history=history,
        user_message=message,
        assistant_message=
            workflow_result.reply,
    )

    assert (
        state.stage
        == "awaiting_date"
    )

    assert (
        state.doctor_id
        is not None
    )

    # ========================================================
    # TURN 3 - SELECT DATE
    # ========================================================

    message = "بعد بكرة"

    nlu_result = await nlu.understand(
        message=message,
        language=state.language,
        state=state,
        history=history,
    )

    print()
    print("=" * 70)
    print("TURN 3 - SELECT DATE")
    print("=" * 70)

    print(
        "USER:",
        message,
    )

    print(
        "NLU:"
    )

    print(
        json.dumps(
            nlu_result.model_dump(),
            ensure_ascii=False,
            indent=2,
        )
    )

    workflow_result = await workflow.handle(
        state=state,
        nlu=nlu_result,
    )

    print()
    print(
        "MEDMIND:",
        workflow_result.reply,
    )

    print_state(
        state
    )

    add_to_history(
        history=history,
        user_message=message,
        assistant_message=
            workflow_result.reply,
    )

    assert (
        state.stage
        == "awaiting_time"
    )

    assert (
        state.slot_date
        is not None
    )

    # ========================================================
    # TURN 4 - SELECT AVAILABLE TIME
    # ========================================================

    message = "14:00"

    nlu_result = await nlu.understand(
        message=message,
        language=state.language,
        state=state,
        history=history,
    )

    print()
    print("=" * 70)
    print("TURN 4 - SELECT TIME")
    print("=" * 70)

    print(
        "USER:",
        message,
    )

    print(
        "NLU:"
    )

    print(
        json.dumps(
            nlu_result.model_dump(),
            ensure_ascii=False,
            indent=2,
        )
    )

    workflow_result = await workflow.handle(
        state=state,
        nlu=nlu_result,
    )

    print()
    print(
        "MEDMIND:",
        workflow_result.reply,
    )

    print_state(
        state
    )

    add_to_history(
        history=history,
        user_message=message,
        assistant_message=
            workflow_result.reply,
    )

    assert (
        state.stage
        == "awaiting_national_id"
    )

    assert (
        state.slot_id
        is not None
    )

    assert (
        state.slot_time
        == "14:00"
    )

    assert (
        state.service_id
        is not None
    )

    # ========================================================
    # TURN 5 - EXISTING PATIENT NATIONAL ID
    # ========================================================

    message = "29901010000001"

    nlu_result = await nlu.understand(
        message=message,
        language=state.language,
        state=state,
        history=history,
    )

    print()
    print("=" * 70)
    print(
        "TURN 5 - EXISTING PATIENT"
    )
    print("=" * 70)

    print(
        "USER:",
        message,
    )

    print(
        "NLU:"
    )

    print(
        json.dumps(
            nlu_result.model_dump(),
            ensure_ascii=False,
            indent=2,
        )
    )

    workflow_result = await workflow.handle(
        state=state,
        nlu=nlu_result,
    )

    print()
    print(
        "MEDMIND:",
        workflow_result.reply,
    )

    print_state(
        state
    )

    add_to_history(
        history=history,
        user_message=message,
        assistant_message=
            workflow_result.reply,
    )

    # ========================================================
    # PRE-DENIAL ASSERTIONS
    # ========================================================

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
        state.appointment_reference
        is None
    )

    assert (
        state.patient_id
        is not None
    )

    assert (
        state.national_id
        == "29901010000001"
    )

    # ========================================================
    # TURN 6 - DENY BOOKING
    # ========================================================

    message = "لأ"

    nlu_result = await nlu.understand(
        message=message,
        language=state.language,
        state=state,
        history=history,
    )

    print()
    print("=" * 70)
    print(
        "TURN 6 - DENY BOOKING"
    )
    print("=" * 70)

    print(
        "USER:",
        message,
    )

    print(
        "NLU:"
    )

    print(
        json.dumps(
            nlu_result.model_dump(),
            ensure_ascii=False,
            indent=2,
        )
    )

    workflow_result = await workflow.handle(
        state=state,
        nlu=nlu_result,
    )

    print()
    print(
        "MEDMIND:",
        workflow_result.reply,
    )

    print()
    print(
        "WORKFLOW RESULT:"
    )

    print(
        json.dumps(
            {
                "handled":
                    workflow_result.handled,

                "response_type":
                    workflow_result.response_type,

                "data":
                    workflow_result.data,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    print_state(
        state
    )

    add_to_history(
        history=history,
        user_message=message,
        assistant_message=
            workflow_result.reply,
    )

    # ========================================================
    # VERIFY STATE AFTER DENIAL
    # ========================================================

    print()
    print("=" * 70)
    print(
        "DENIAL STATE CHECK"
    )
    print("=" * 70)

    print(
        "stage:",
        state.stage,
    )

    print(
        "awaiting_confirmation:",
        state.awaiting_confirmation,
    )

    print(
        "pending_action:",
        state.pending_action,
    )

    print(
        "appointment_reference:",
        state.appointment_reference,
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
        state.appointment_reference
        is None
    )

    # ========================================================
    # VERIFY THE SLOT WAS NOT BOOKED
    # ========================================================

    print()
    print("=" * 70)
    print(
        "VERIFY SLOT STILL AVAILABLE"
    )
    print("=" * 70)

    selected_slot_date = (
        state.slot_date
    )

    selected_doctor_id = (
        state.doctor_id
    )

    selected_time = (
        state.slot_time
    )

    slots = await tools.call(
        "list_available_slots",

        slot_date=
            selected_slot_date,

        doctor_id=
            selected_doctor_id,

        limit=100,
    )

    print(
        json.dumps(
            slots,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    # --------------------------------------------------------
    # MCP parser may return one dict or a list
    # --------------------------------------------------------

    if isinstance(
        slots,
        dict,
    ):

        slot_items = [
            slots
        ]

    elif isinstance(
        slots,
        list,
    ):

        slot_items = (
            slots
        )

    else:

        slot_items = []

    still_available = any(

        str(
            slot.get(
                "start_time",
                ""
            )
        ).startswith(
            selected_time
        )

        and

        slot.get(
            "status"
        )
        == "available"

        for slot
        in slot_items

        if isinstance(
            slot,
            dict,
        )
    )

    print()

    print(
        f"{selected_time} STILL AVAILABLE:",
        still_available,
    )

    assert (
        still_available
        is True
    )

    print()
    print("=" * 70)
    print(
        "DENIAL TEST PASSED"
    )
    print("=" * 70)

    print(
        "No appointment was created."
    )

    print(
        "The selected slot remained available."
    )

    # ========================================================
    # SAVE PATIENT IDENTITY BEFORE NEW BOOKING
    # ========================================================

    original_patient_id = (
        state.patient_id
    )

    original_national_id = (
        state.national_id
    )

    original_patient_name = (
        state.patient_name
    )

    original_phone = (
        state.phone
    )

    # ========================================================
    # TURN 7 - START SECOND BOOKING
    # ========================================================

    message = (
        "عايزة احجز جلدية كمان"
    )

    nlu_result = await nlu.understand(
        message=message,
        language=state.language,
        state=state,
        history=history,
    )

    print()
    print("=" * 70)
    print(
        "TURN 7 - START SECOND BOOKING"
    )
    print("=" * 70)

    print(
        "USER:",
        message,
    )

    print(
        "NLU:"
    )

    print(
        json.dumps(
            nlu_result.model_dump(),
            ensure_ascii=False,
            indent=2,
        )
    )

    workflow_result = await workflow.handle(
        state=state,
        nlu=nlu_result,
    )

    print()
    print(
        "MEDMIND:",
        workflow_result.reply,
    )

    print_state(
        state
    )

    add_to_history(
        history=history,
        user_message=message,
        assistant_message=
            workflow_result.reply,
    )

    # ========================================================
    # VERIFY OLD BOOKING RESET
    # AND PATIENT IDENTITY PRESERVED
    # ========================================================

    assert (
        state.operation_type
        == "book_appointment"
    )

    assert (
        state.stage
        == "awaiting_doctor"
    )

    assert (
        state.patient_id
        == original_patient_id
    )

    assert (
        state.national_id
        == original_national_id
    )

    assert (
        state.patient_name
        == original_patient_name
    )

    assert (
        state.phone
        == original_phone
    )

    assert (
        state.appointment_reference
        is None
    )

    assert (
        state.awaiting_confirmation
        is False
    )

    assert (
        state.pending_action
        is None
    )

    # New booking should already have a new specialty.
    assert (
        state.specialty_id
        is not None
    )

    # But old doctor/service/slot must be cleared.
    assert (
        state.doctor_id
        is None
    )

    assert (
        state.service_id
        is None
    )

    assert (
        state.slot_id
        is None
    )

    # ========================================================
    # TURN 8 - SELECT DOCTOR
    # ========================================================

    message = "منى"

    nlu_result = await nlu.understand(
        message=message,
        language=state.language,
        state=state,
        history=history,
    )

    print()
    print("=" * 70)
    print(
        "TURN 8 - SELECT DOCTOR"
    )
    print("=" * 70)

    print(
        "USER:",
        message,
    )

    print(
        "NLU:"
    )

    print(
        json.dumps(
            nlu_result.model_dump(),
            ensure_ascii=False,
            indent=2,
        )
    )

    workflow_result = await workflow.handle(
        state=state,
        nlu=nlu_result,
    )

    print()
    print(
        "MEDMIND:",
        workflow_result.reply,
    )

    print_state(
        state
    )

    add_to_history(
        history=history,
        user_message=message,
        assistant_message=
            workflow_result.reply,
    )

    assert (
        state.stage
        == "awaiting_date"
    )

    assert (
        state.doctor_id
        is not None
    )

    # ========================================================
    # TURN 9 - SELECT DATE
    # ========================================================

    message = "بعد بكرة"

    nlu_result = await nlu.understand(
        message=message,
        language=state.language,
        state=state,
        history=history,
    )

    print()
    print("=" * 70)
    print(
        "TURN 9 - SELECT DATE"
    )
    print("=" * 70)

    print(
        "USER:",
        message,
    )

    print(
        "NLU:"
    )

    print(
        json.dumps(
            nlu_result.model_dump(),
            ensure_ascii=False,
            indent=2,
        )
    )

    workflow_result = await workflow.handle(
        state=state,
        nlu=nlu_result,
    )

    print()
    print(
        "MEDMIND:",
        workflow_result.reply,
    )

    print_state(
        state
    )

    add_to_history(
        history=history,
        user_message=message,
        assistant_message=
            workflow_result.reply,
    )

    assert (
        state.stage
        == "awaiting_time"
    )

    assert (
        state.slot_date
        is not None
    )

    # ========================================================
    # TURN 10 - SELECT TIME
    # ========================================================

    message = "14:30"

    nlu_result = await nlu.understand(
        message=message,
        language=state.language,
        state=state,
        history=history,
    )

    print()
    print("=" * 70)
    print(
        "TURN 10 - SELECT TIME"
    )
    print("=" * 70)

    print(
        "USER:",
        message,
    )

    print(
        "NLU:"
    )

    print(
        json.dumps(
            nlu_result.model_dump(),
            ensure_ascii=False,
            indent=2,
        )
    )

    workflow_result = await workflow.handle(
        state=state,
        nlu=nlu_result,
    )

    print()
    print(
        "MEDMIND:",
        workflow_result.reply,
    )

    print_state(
        state
    )

    add_to_history(
        history=history,
        user_message=message,
        assistant_message=
            workflow_result.reply,
    )

    # ========================================================
    # VERIFY SECOND BOOKING
    # ========================================================

    print()
    print("=" * 70)
    print(
        "SECOND BOOKING STATE CHECK"
    )
    print("=" * 70)

    print(
        "stage:",
        state.stage,
    )

    print(
        "patient_id:",
        state.patient_id,
    )

    print(
        "patient_name:",
        state.patient_name,
    )

    print(
        "slot_time:",
        state.slot_time,
    )

    print(
        "awaiting_confirmation:",
        state.awaiting_confirmation,
    )

    print(
        "pending_action:",
        state.pending_action,
    )

    # --------------------------------------------------------
    # Must skip national ID/name/phone and go directly
    # to confirmation because patient is already known.
    # --------------------------------------------------------

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
    # Patient identity must be preserved
    # --------------------------------------------------------

    assert (
        state.patient_id
        == original_patient_id
    )

    assert (
        state.national_id
        == original_national_id
    )

    assert (
        state.patient_name
        == original_patient_name
    )

    assert (
        state.phone
        == original_phone
    )

    # --------------------------------------------------------
    # Second booking data must exist
    # --------------------------------------------------------

    assert (
        state.specialty_id
        is not None
    )

    assert (
        state.doctor_id
        is not None
    )

    assert (
        state.service_id
        is not None
    )

    assert (
        state.slot_id
        is not None
    )

    assert (
        state.slot_time
        == "14:30"
    )

    # --------------------------------------------------------
    # We deliberately do NOT confirm the second booking.
    # Nothing should be written.
    # --------------------------------------------------------

    assert (
        state.appointment_reference
        is None
    )

    print()
    print("=" * 70)
    print(
        "SECOND BOOKING SESSION TEST PASSED"
    )
    print("=" * 70)

    print(
        "Old booking operation was reset."
    )

    print(
        "Patient identity was preserved."
    )

    print(
        "National ID, name and phone "
        "were not requested again."
    )

    print(
        "Second booking reached confirmation "
        "without creating it."
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )