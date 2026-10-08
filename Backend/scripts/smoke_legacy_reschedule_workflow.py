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

from medmind.workflows.reschedule import (
    RescheduleWorkflow,
)


# ============================================================
# TEST DATA
# ============================================================

TEST_NATIONAL_ID = (
    "29901010000001"
)

TEST_PATIENT_ID = (
    "941bfa69-bdf6-4d14-9715-51b4dd557478"
)

TEST_PATIENT_NAME = (
    "أية أحمد"
)

TEST_PHONE = (
    "01000000003"
)

TEST_APPOINTMENT_REFERENCE = (
    "APT-260818-7733DB38"
)

TEST_OLD_SLOT_ID = (
    "cb4115c8-35c1-4510-a797-740dc31a655f"
)

TEST_OLD_DATE = (
    "2026-08-20"
)

TEST_OLD_TIME = (
    "13:30"
)


# ============================================================
# HELPERS
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


def ensure_list(
    value,
) -> list:

    if value is None:
        return []

    if isinstance(
        value,
        list,
    ):
        return value

    if isinstance(
        value,
        dict,
    ):
        return [
            value
        ]

    return []


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
    # NLU
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

    workflow = RescheduleWorkflow(
        tools=tools
    )

    # ========================================================
    # VERIFY FIXTURE BEFORE TEST
    # ========================================================

    print()
    print("=" * 70)
    print(
        "VERIFY BOOKING BEFORE RESCHEDULE FLOW"
    )
    print("=" * 70)

    booking_before = await tools.call(
        "lookup_booking",

        national_id=
            TEST_NATIONAL_ID,

        appointment_reference=
            TEST_APPOINTMENT_REFERENCE,
    )

    print(
        json.dumps(
            booking_before,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    assert isinstance(
        booking_before,
        dict,
    )

    assert (
        booking_before.get(
            "appointment_reference"
        )
        == TEST_APPOINTMENT_REFERENCE
    )

    assert (
        booking_before.get(
            "status"
        )
        == "confirmed"
    )

    assert (
        booking_before.get(
            "slot_id"
        )
        == TEST_OLD_SLOT_ID
    )

    assert (
        booking_before.get(
            "scheduled_date"
        )
        == TEST_OLD_DATE
    )

    assert str(
        booking_before.get(
            "start_time",
            ""
        )
    ).startswith(
        TEST_OLD_TIME
    )

    assert (
        booking_before.get(
            "reschedule_count"
        )
        == 0
    )

    # ========================================================
    # STATE
    #
    # Simulate the same patient/session after a previous
    # successful booking.
    # ========================================================

    state = SessionState(
        session_id=
            "reschedule-workflow-test-001",

        tenant_id=
            tenant_id,

        language=
            "ar",

        operation_type=
            "book_appointment",

        stage=
            "booking_completed",

        patient_id=
            TEST_PATIENT_ID,

        national_id=
            TEST_NATIONAL_ID,

        patient_name=
            TEST_PATIENT_NAME,

        phone=
            TEST_PHONE,

        appointment_reference=
            TEST_APPOINTMENT_REFERENCE,
    )

    history: list[
        ChatMessage
    ] = []

    # ========================================================
    # TURN 1 - REQUEST RESCHEDULE
    # ========================================================

    message = (
        "عايزة أغير ميعاد الحجز"
    )

    language = detect_language(
        message
    )

    state.language = (
        language
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
        "TURN 1 - REQUEST RESCHEDULE"
    )
    print("=" * 70)

    print(
        "USER:",
        message,
    )

    print()
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
    # VERIFY CURRENT BOOKING LOADED
    # ========================================================

    assert (
        state.operation_type
        == "reschedule_appointment"
    )

    assert (
        state.stage
        == "awaiting_reschedule_date"
    )

    assert (
        state.appointment_reference
        == TEST_APPOINTMENT_REFERENCE
    )

    assert (
        state.patient_id
        == TEST_PATIENT_ID
    )

    assert (
        state.national_id
        == TEST_NATIONAL_ID
    )

    assert (
        state.slot_id
        == TEST_OLD_SLOT_ID
    )

    assert (
        state.slot_date
        == TEST_OLD_DATE
    )

    assert (
        state.slot_time
        == TEST_OLD_TIME
    )

    assert (
        state.doctor_id
        is not None
    )

    assert (
        state.new_slot_id
        is None
    )

    assert (
        state.new_slot_date
        is None
    )

    assert (
        state.new_slot_time
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

    # ========================================================
    # TURN 2 - SELECT NEW DATE
    # ========================================================

    message = "20/8"

    nlu_result = await nlu.understand(
        message=message,
        language=state.language,
        state=state,
        history=history,
    )

    print()
    print("=" * 70)
    print(
        "TURN 2 - SELECT NEW DATE"
    )
    print("=" * 70)

    print(
        "USER:",
        message,
    )

    print()
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

    # --------------------------------------------------------
    # Should now have available target slots
    # --------------------------------------------------------

    assert (
        state.stage
        == "awaiting_reschedule_time"
    )

    assert (
        state.new_slot_date
        == TEST_OLD_DATE
    )

    assert (
        state.recent_slots
    )

    # ========================================================
    # CHOOSE A TARGET SLOT
    #
    # Prefer 14:00, but if unavailable choose the first
    # backend-provided available slot.
    # ========================================================

    target_slot = next(
        (
            slot
            for slot
            in state.recent_slots

            if (
                slot.start_time[:5]
                == "14:00"
            )
        ),
        state.recent_slots[0],
    )

    target_slot_id = (
        target_slot.id
    )

    target_time = (
        target_slot.start_time[:5]
    )

    assert (
        target_slot_id
        != TEST_OLD_SLOT_ID
    )

    assert (
        target_time
        != TEST_OLD_TIME
    )

    print()
    print("=" * 70)
    print(
        "TARGET RESCHEDULE SLOT"
    )
    print("=" * 70)

    print(
        "new_slot_id:",
        target_slot_id,
    )

    print(
        "new_date:",
        target_slot.slot_date,
    )

    print(
        "new_time:",
        target_time,
    )

    # ========================================================
    # TURN 3 - SELECT NEW TIME
    # ========================================================

    message = (
        target_time
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
        "TURN 3 - SELECT NEW TIME"
    )
    print("=" * 70)

    print(
        "USER:",
        message,
    )

    print()
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
    # VERIFY CONFIRMATION GATE
    # ========================================================

    print()
    print("=" * 70)
    print(
        "RESCHEDULE STATE CHECK"
    )
    print("=" * 70)

    print(
        "stage:",
        state.stage,
    )

    print(
        "old_slot_id:",
        state.slot_id,
    )

    print(
        "old_date:",
        state.slot_date,
    )

    print(
        "old_time:",
        state.slot_time,
    )

    print(
        "new_slot_id:",
        state.new_slot_id,
    )

    print(
        "new_date:",
        state.new_slot_date,
    )

    print(
        "new_time:",
        state.new_slot_time,
    )

    print(
        "awaiting_confirmation:",
        state.awaiting_confirmation,
    )

    print(
        "pending_action:",
        state.pending_action,
    )

    assert (
        state.stage
        == "awaiting_reschedule_confirmation"
    )

    assert (
        state.awaiting_confirmation
        is True
    )

    assert (
        state.pending_action
        == "reschedule_booking"
    )

    assert (
        state.slot_id
        == TEST_OLD_SLOT_ID
    )

    assert (
        state.slot_date
        == TEST_OLD_DATE
    )

    assert (
        state.slot_time
        == TEST_OLD_TIME
    )

    assert (
        state.new_slot_id
        == target_slot_id
    )

    assert (
        state.new_slot_date
        == TEST_OLD_DATE
    )

    assert (
        state.new_slot_time
        == target_time
    )

    # ========================================================
    # VERIFY NO RESCHEDULE WRITE OCCURRED
    # ========================================================

    print()
    print("=" * 70)
    print(
        "VERIFY BOOKING STILL UNCHANGED"
    )
    print("=" * 70)

    booking_after = await tools.call(
        "lookup_booking",

        national_id=
            TEST_NATIONAL_ID,

        appointment_reference=
            TEST_APPOINTMENT_REFERENCE,
    )

    print(
        json.dumps(
            booking_after,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    assert isinstance(
        booking_after,
        dict,
    )

    assert (
        booking_after.get(
            "status"
        )
        == "confirmed"
    )

    # Appointment must still point to old slot.
    assert (
        booking_after.get(
            "slot_id"
        )
        == TEST_OLD_SLOT_ID
    )

    assert (
        booking_after.get(
            "scheduled_date"
        )
        == TEST_OLD_DATE
    )

    assert str(
        booking_after.get(
            "start_time",
            ""
        )
    ).startswith(
        TEST_OLD_TIME
    )

    assert (
        booking_after.get(
            "reschedule_count"
        )
        == 0
    )

    # ========================================================
    # VERIFY OLD + NEW SLOT STATUS BEFORE CONFIRMATION
    # ========================================================

    print()
    print("=" * 70)
    print(
        "VERIFY SLOT SAFETY BEFORE CONFIRMATION"
    )
    print("=" * 70)

    slots_result = await tools.call(
        "list_available_slots",

        doctor_id=
            state.doctor_id,

        slot_date=
            TEST_OLD_DATE,

        limit=100,
    )

    print(
        json.dumps(
            slots_result,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    slot_items = ensure_list(
        slots_result
    )

    # --------------------------------------------------------
    # Old slot must still be locked because original
    # booking has NOT been moved yet.
    # --------------------------------------------------------

    old_slot_available = any(

        str(
            slot.get(
                "id",
                ""
            )
        )
        == TEST_OLD_SLOT_ID

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

    # --------------------------------------------------------
    # New slot must still be available because user
    # has NOT confirmed the reschedule yet.
    # --------------------------------------------------------

    new_slot_available = any(

        str(
            slot.get(
                "id",
                ""
            )
        )
        == str(
            target_slot_id
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
        f"OLD {TEST_OLD_TIME} AVAILABLE:",
        old_slot_available,
    )

    print(
        f"NEW {target_time} AVAILABLE:",
        new_slot_available,
    )

    assert (
        old_slot_available
        is False
    )

    assert (
        new_slot_available
        is True
    )

    # ========================================================
    # SUCCESS
    # ========================================================

    print()
    print("=" * 70)
    print(
        "RESCHEDULE READ + SAFETY TEST PASSED"
    )
    print("=" * 70)

    print(
        "Current booking was loaded successfully."
    )

    print(
        "Old appointment slot was preserved."
    )

    print(
        "New target slot was selected."
    )

    print(
        "Reschedule reached explicit confirmation."
    )

    print(
        "No reschedule write was executed."
    )

    print(
        "Old slot is still locked."
    )

    print(
        "New slot is still available."
    )

    # ========================================================
    # TURN 4 - DENY RESCHEDULE
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
        "TURN 4 - DENY RESCHEDULE"
    )
    print("=" * 70)

    print(
        "USER:",
        message,
    )

    print()
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

    # ========================================================
    # VERIFY DENIAL STATE
    # ========================================================

    print()
    print("=" * 70)
    print(
        "RESCHEDULE DENIAL STATE CHECK"
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
        "old_slot_id:",
        state.slot_id,
    )

    print(
        "new_slot_id:",
        state.new_slot_id,
    )

    assert (
        nlu_result.intent
        == "deny_action"
        or
        nlu_result.confirmation
        == "no"
    )

    assert (
        state.stage
        == "reschedule_declined"
    )

    assert (
        state.awaiting_confirmation
        is False
    )

    assert (
        state.pending_action
        is None
    )

    # Old appointment must remain intact.
    assert (
        state.slot_id
        == TEST_OLD_SLOT_ID
    )

    assert (
        state.slot_date
        == TEST_OLD_DATE
    )

    assert (
        state.slot_time
        == TEST_OLD_TIME
    )

    # Target slot data should be cleared.
    assert (
        state.new_slot_id
        is None
    )

    assert (
        state.new_slot_date
        is None
    )

    assert (
        state.new_slot_time
        is None
    )

    # ========================================================
    # VERIFY BOOKING STILL UNCHANGED IN BACKEND
    # ========================================================

    print()
    print("=" * 70)
    print(
        "VERIFY BOOKING AFTER RESCHEDULE DENIAL"
    )
    print("=" * 70)

    booking_after_denial = await tools.call(
        "lookup_booking",

        national_id=
            TEST_NATIONAL_ID,

        appointment_reference=
            TEST_APPOINTMENT_REFERENCE,
    )

    print(
        json.dumps(
            booking_after_denial,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    assert isinstance(
        booking_after_denial,
        dict,
    )

    assert (
        booking_after_denial.get(
            "status"
        )
        == "confirmed"
    )

    assert (
        booking_after_denial.get(
            "slot_id"
        )
        == TEST_OLD_SLOT_ID
    )

    assert (
        booking_after_denial.get(
            "scheduled_date"
        )
        == TEST_OLD_DATE
    )

    assert str(
        booking_after_denial.get(
            "start_time",
            ""
        )
    ).startswith(
        TEST_OLD_TIME
    )

    assert (
        booking_after_denial.get(
            "reschedule_count"
        )
        == 0
    )

    # ========================================================
    # VERIFY SLOT STATUS AFTER DENIAL
    # ========================================================

    print()
    print("=" * 70)
    print(
        "VERIFY SLOT STATUS AFTER DENIAL"
    )
    print("=" * 70)

    slots_after_denial = await tools.call(
        "list_available_slots",

        doctor_id=
            state.doctor_id,

        slot_date=
            TEST_OLD_DATE,

        limit=100,
    )

    print(
        json.dumps(
            slots_after_denial,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    slot_items = ensure_list(
        slots_after_denial
    )

    old_slot_available = any(

        str(
            slot.get(
                "id",
                ""
            )
        )
        == TEST_OLD_SLOT_ID

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

    new_slot_available = any(

        str(
            slot.get(
                "id",
                ""
            )
        )
        == str(
            target_slot_id
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
        f"OLD {TEST_OLD_TIME} AVAILABLE:",
        old_slot_available,
    )

    print(
        f"NEW {target_time} AVAILABLE:",
        new_slot_available,
    )

    assert (
        old_slot_available
        is False
    )

    assert (
        new_slot_available
        is True
    )

    # ========================================================
    # SUCCESS
    # ========================================================

    print()
    print("=" * 70)
    print(
        "RESCHEDULE DENIAL TEST PASSED"
    )
    print("=" * 70)

    print(
        "User denied the reschedule."
    )

    print(
        "No reschedule_booking write was executed."
    )

    print(
        "Original booking is still confirmed."
    )

    print(
        "Old slot is still locked."
    )

    print(
        "New slot is still available."
    )
if __name__ == "__main__":

    asyncio.run(
        main()
    )