from __future__ import annotations

import asyncio
import json
import os

from uuid import uuid4

from dotenv import (
    load_dotenv,
)

from langchain_mcp_adapters.client import (
    MultiServerMCPClient,
)

from medmind.core.tool_executor import (
    MCPToolExecutor,
)


# ============================================================
# TEST DATA
# ============================================================

TEST_NATIONAL_ID = (
    "29901010000001"
)

TEST_DOCTOR_ID = (
    "955ed459-1f70-5bf3-a88c-709019974a1f"
)

TEST_SERVICE_ID = (
    "0c84538e-bac9-5a40-bf70-552360ab8cc8"
)

TEST_SLOT_DATE = (
    "2026-08-20"
)


# ============================================================
# HELPERS
# ============================================================

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

    mcp_url = os.getenv(
        "MCP_URL",
        "http://127.0.0.1:9000/mcp",
    )

    tenant_id = os.getenv(
        "TENANT_ID",
        "clinic-001",
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

    # ========================================================
    # STEP 1 - LOAD AVAILABLE SLOTS
    # ========================================================

    print()
    print("=" * 70)
    print(
        "LOAD AVAILABLE SLOTS"
    )
    print("=" * 70)

    slots_result = await tools.call(
        "list_available_slots",

        doctor_id=
            TEST_DOCTOR_ID,

        slot_date=
            TEST_SLOT_DATE,

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

    slots = ensure_list(
        slots_result
    )

    available_slots = [
        slot
        for slot
        in slots

        if (
            isinstance(
                slot,
                dict,
            )
            and
            slot.get(
                "status"
            )
            == "available"
            and
            slot.get(
                "id"
            )
        )
    ]

    assert (
        available_slots
    ), (
        "No available slot found "
        "for the reschedule fixture."
    )

    # --------------------------------------------------------
    # Prefer 13:30 because the cancelled booking released it.
    # If it is not available, use the first available slot.
    # --------------------------------------------------------

    selected_slot = next(
        (
            slot
            for slot
            in available_slots

            if str(
                slot.get(
                    "start_time",
                    ""
                )
            ).startswith(
                "13:30"
            )
        ),
        available_slots[0],
    )

    selected_slot_id = (
        selected_slot[
            "id"
        ]
    )

    selected_start_time = str(
        selected_slot.get(
            "start_time",
            ""
        )
    )[:5]

    print()
    print("=" * 70)
    print(
        "SELECTED FIXTURE SLOT"
    )
    print("=" * 70)

    print(
        "slot_id:",
        selected_slot_id,
    )

    print(
        "date:",
        TEST_SLOT_DATE,
    )

    print(
        "time:",
        selected_start_time,
    )

    # ========================================================
    # STEP 2 - CREATE REAL BOOKING
    # ========================================================

    print()
    print("=" * 70)
    print(
        "CREATE RESCHEDULE FIXTURE BOOKING"
    )
    print("=" * 70)

    idempotency_key = str(
        uuid4()
    )

    create_result = await tools.call(
        "create_booking",

        national_id=
            TEST_NATIONAL_ID,

        slot_id=
            selected_slot_id,

        service_id=
            TEST_SERVICE_ID,

        idempotency_key=
            idempotency_key,

        channel=
            "web",

        session_reference=
            "reschedule-fixture-001",
    )

    print(
        json.dumps(
            create_result,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    assert isinstance(
        create_result,
        dict,
    )

    appointment_reference = (
        create_result.get(
            "appointment_reference"
        )
    )

    assert (
        appointment_reference
    ), (
        "Backend did not return "
        "appointment_reference."
    )

    assert (
        create_result.get(
            "status"
        )
        == "confirmed"
    )

    # ========================================================
    # STEP 3 - VERIFY BOOKING IN BACKEND
    # ========================================================

    print()
    print("=" * 70)
    print(
        "VERIFY FIXTURE BOOKING"
    )
    print("=" * 70)

    booking = await tools.call(
        "lookup_booking",

        national_id=
            TEST_NATIONAL_ID,

        appointment_reference=
            appointment_reference,
    )

    print(
        json.dumps(
            booking,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    assert isinstance(
        booking,
        dict,
    )

    assert (
        booking.get(
            "appointment_reference"
        )
        == appointment_reference
    )

    assert (
        booking.get(
            "status"
        )
        == "confirmed"
    )

    assert (
        booking.get(
            "scheduled_date"
        )
        == TEST_SLOT_DATE
    )

    assert str(
        booking.get(
            "start_time",
            ""
        )
    ).startswith(
        selected_start_time
    )

    # ========================================================
    # STEP 4 - VERIFY SLOT LOCK
    # ========================================================

    print()
    print("=" * 70)
    print(
        "VERIFY FIXTURE SLOT LOCK"
    )
    print("=" * 70)

    slots_after = await tools.call(
        "list_available_slots",

        doctor_id=
            TEST_DOCTOR_ID,

        slot_date=
            TEST_SLOT_DATE,

        limit=100,
    )

    print(
        json.dumps(
            slots_after,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    slots_after_items = ensure_list(
        slots_after
    )

    selected_slot_still_available = any(

        slot.get(
            "id"
        )
        == selected_slot_id

        and

        slot.get(
            "status"
        )
        == "available"

        for slot
        in slots_after_items

        if isinstance(
            slot,
            dict,
        )
    )

    print()

    print(
        f"{selected_start_time} STILL AVAILABLE:",
        selected_slot_still_available,
    )

    assert (
        selected_slot_still_available
        is False
    )

    # ========================================================
    # FIXTURE SUMMARY
    # ========================================================

    print()
    print("=" * 70)
    print(
        "RESCHEDULE FIXTURE CREATED"
    )
    print("=" * 70)

    print(
        "appointment_reference:",
        appointment_reference,
    )

    print(
        "national_id:",
        TEST_NATIONAL_ID,
    )

    print(
        "doctor_id:",
        TEST_DOCTOR_ID,
    )

    print(
        "service_id:",
        TEST_SERVICE_ID,
    )

    print(
        "old_slot_id:",
        selected_slot_id,
    )

    print(
        "old_date:",
        TEST_SLOT_DATE,
    )

    print(
        "old_time:",
        selected_start_time,
    )

    print()

    print(
        "Booking is confirmed and ready "
        "for the reschedule tests."
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )