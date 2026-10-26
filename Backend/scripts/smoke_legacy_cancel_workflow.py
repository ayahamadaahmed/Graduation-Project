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

from medmind.workflows.cancel import (
    CancelWorkflow,
)


# ============================================================
# CONSTANTS
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
    # LLM / NLU
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

    # --------------------------------------------------------
    # Simulate state after previous successful booking
    # --------------------------------------------------------

    state = SessionState(
        session_id=
            "cancel-workflow-test-001",

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
    # VERIFY BOOKING EXISTS BEFORE CANCEL FLOW
    # ========================================================

    print()
    print("=" * 70)
    print(
        "VERIFY BOOKING BEFORE CANCEL FLOW"
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
    # TURN 1 - REQUEST CANCELLATION
    # ========================================================

    message = (
        "عايزة ألغي الحجز"
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
        "TURN 1 - CANCEL REQUEST"
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
    # VERIFY CANCEL FLOW STATE
    # ========================================================

    print()
    print("=" * 70)
    print(
        "CANCEL STATE CHECK"
    )
    print("=" * 70)

    print(
        "operation_type:",
        state.operation_type,
    )

    print(
        "stage:",
        state.stage,
    )

    print(
        "appointment_reference:",
        state.appointment_reference,
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
        "awaiting_confirmation:",
        state.awaiting_confirmation,
    )

    print(
        "pending_action:",
        state.pending_action,
    )

    # --------------------------------------------------------
    # Correct operation switch
    # --------------------------------------------------------

    assert (
        state.operation_type
        == "cancel_appointment"
    )

    # --------------------------------------------------------
    # Existing patient identity must survive reset
    # --------------------------------------------------------

    assert (
        state.patient_id
        == TEST_PATIENT_ID
    )

    assert (
        state.national_id
        == TEST_NATIONAL_ID
    )

    assert (
        state.patient_name
        == TEST_PATIENT_NAME
    )

    assert (
        state.phone
        == TEST_PHONE
    )

    # --------------------------------------------------------
    # Previous booking reference must survive operation switch
    # --------------------------------------------------------

    assert (
        state.appointment_reference
        == TEST_APPOINTMENT_REFERENCE
    )

    # --------------------------------------------------------
    # Real booking must be loaded and waiting for confirmation
    # --------------------------------------------------------

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

    # ========================================================
    # VERIFY NO WRITE OCCURRED
    # ========================================================

    print()
    print("=" * 70)
    print(
        "VERIFY BOOKING WAS NOT CANCELLED"
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
        == "confirmed"
    )

    # ========================================================
    # SUCCESS
    # ========================================================

    print()
    print("=" * 70)
    print(
        "CANCEL READ + SAFETY TEST PASSED"
    )
    print("=" * 70)

    print(
        "Booking was found successfully."
    )

    print(
        "Patient identity was preserved."
    )

    print(
        "Booking reference was preserved."
    )

    print(
        "Cancellation reached confirmation."
    )

    print(
        "No cancellation write was executed."
    )

    # ========================================================
    # TURN 2 - DENY CANCELLATION
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
        "TURN 2 - DENY CANCELLATION"
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
        "CANCEL DENIAL STATE CHECK"
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
        nlu_result.intent
        == "deny_action"
        or
        nlu_result.confirmation
        == "no"
    )

    assert (
        state.stage
        == "cancel_declined"
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

    # ========================================================
    # VERIFY BACKEND BOOKING STILL CONFIRMED
    # ========================================================

    print()
    print("=" * 70)
    print(
        "VERIFY BOOKING AFTER CANCEL DENIAL"
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
            "appointment_reference"
        )
        == TEST_APPOINTMENT_REFERENCE
    )

    assert (
        booking_after_denial.get(
            "status"
        )
        == "confirmed"
    )

    print()
    print("=" * 70)
    print(
        "CANCEL DENIAL TEST PASSED"
    )
    print("=" * 70)

    print(
        "User denied cancellation."
    )

    print(
        "No cancel_booking write was executed."
    )

    print(
        "Booking is still confirmed in backend."
    )
# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )