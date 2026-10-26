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

from medmind.state.models import (
    SessionState,
)

from medmind.understanding.llm import (
    LLMNLU,
)

from medmind.workflows.cancel import (
    CancelWorkflow,
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
    "APT-260818-551A45D5"
)

TEST_DOCTOR_ID = (
    "955ed459-1f70-5bf3-a88c-709019974a1f"
)

TEST_SLOT_DATE = (
    "2026-08-20"
)

TEST_SLOT_TIME = (
    "13:30"
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
                    # Agent -> MCP credential (MCP_AUTH_MODE).
                    **(
                        {"X-MedMind-Service-Token": os.environ["MCP_SERVER_TOKEN"]}
                        if os.getenv("MCP_SERVER_TOKEN")
                        else {}
                    ),
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

    workflow = CancelWorkflow(
        tools=tools
    )

    # ========================================================
    # VERIFY BOOKING BEFORE EXECUTION
    # ========================================================

    print()
    print("=" * 70)
    print(
        "VERIFY BOOKING BEFORE CANCELLATION"
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

    # ========================================================
    # STATE
    # ========================================================

    state = SessionState(
        session_id=
            "cancel-execution-test-001",

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

    history = []

    # ========================================================
    # TURN 1 - REQUEST CANCELLATION
    # ========================================================

    message = (
        "عايزة ألغي الحجز"
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
        "TURN 1 - REQUEST CANCELLATION"
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

    # --------------------------------------------------------
    # Must wait for confirmation
    # --------------------------------------------------------

    assert (
        state.operation_type
        == "cancel_appointment"
    )

    assert (
        state.stage
        == "awaiting_cancel_confirmation"
    )

    assert (
        state.awaiting_confirmation
        is True
    )

    assert (
        state.pending_action
        == "cancel_booking"
    )

    assert (
        state.appointment_reference
        == TEST_APPOINTMENT_REFERENCE
    )

    # ========================================================
    # TURN 2 - CONFIRM REAL CANCELLATION
    # ========================================================

    message = "أيوه"

    nlu_result = await nlu.understand(
        message=message,
        language=state.language,
        state=state,
        history=history,
    )

    print()
    print("=" * 70)
    print(
        "TURN 2 - CONFIRM CANCELLATION"
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

    assert (
        nlu_result.intent
        == "confirm_action"
        or
        nlu_result.confirmation
        == "yes"
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
    # VERIFY WORKFLOW SUCCESS
    # ========================================================

    print()
    print("=" * 70)
    print(
        "CANCEL EXECUTION STATE CHECK"
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
        == "cancel_completed"
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
        == TEST_APPOINTMENT_REFERENCE
    )

    assert (
        workflow_result.response_type
        == "booking_cancelled"
    )

    # ========================================================
    # VERIFY DATABASE
    # ========================================================

    print()
    print("=" * 70)
    print(
        "VERIFY CANCELLED BOOKING IN BACKEND"
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
            "appointment_reference"
        )
        == TEST_APPOINTMENT_REFERENCE
    )

    assert (
        booking_after.get(
            "status"
        )
        == "cancelled"
    )

    assert (
        booking_after.get(
            "cancelled_at"
        )
        is not None
    )

    # ========================================================
    # VERIFY SLOT RELEASE
    # ========================================================

    print()
    print("=" * 70)
    print(
        "VERIFY SLOT RELEASE"
    )
    print("=" * 70)

    slots = await tools.call(
        "list_available_slots",

        doctor_id=
            TEST_DOCTOR_ID,

        slot_date=
            TEST_SLOT_DATE,

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

    slot_released = any(

        str(
            slot.get(
                "start_time",
                ""
            )
        ).startswith(
            TEST_SLOT_TIME
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
        f"{TEST_SLOT_TIME} AVAILABLE AGAIN:",
        slot_released,
    )

    assert (
        slot_released
        is True
    )

    # ========================================================
    # SUCCESS
    # ========================================================

    print()
    print("=" * 70)
    print(
        "CANCEL EXECUTION TEST PASSED"
    )
    print("=" * 70)

    print(
        "Cancellation was explicitly confirmed."
    )

    print(
        "cancel_booking was executed through MCP."
    )

    print(
        "Backend stored status=cancelled."
    )

    print(
        "cancelled_at was stored."
    )

    print(
        "The old appointment slot was released."
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )