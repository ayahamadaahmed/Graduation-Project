from __future__ import annotations

import asyncio
import json
import os

from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient

from medmind.core.tool_executor import MCPToolExecutor


NATIONAL_ID = "29901010000001"

APPOINTMENT_REFERENCE = (
    "APT-260818-551A45D5"
)

DOCTOR_ID = (
    "955ed459-1f70-5bf3-a88c-709019974a1f"
)

SLOT_DATE = "2026-08-20"


async def main() -> None:

    load_dotenv(
        override=True
    )

    client = MultiServerMCPClient(
        {
            "healthcare": {
                "transport": "http",

                "url": os.getenv(
                    "MCP_URL",
                    "http://127.0.0.1:9000/mcp",
                ),

                "headers": {
                    # Agent -> MCP credential (MCP_AUTH_MODE).
                    **(
                        {"X-MedMind-Service-Token": os.environ["MCP_SERVER_TOKEN"]}
                        if os.getenv("MCP_SERVER_TOKEN")
                        else {}
                    ),
                    "X-Tenant-ID":
                        os.getenv(
                            "TENANT_ID",
                            "clinic-001",
                        ),
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

    # ====================================================
    # 1. VERIFY APPOINTMENT EXISTS
    # ====================================================

    print()
    print("=" * 70)
    print("VERIFY CREATED APPOINTMENT")
    print("=" * 70)

    booking = await tools.call(
        "lookup_booking",

        national_id=
            NATIONAL_ID,

        appointment_reference=
            APPOINTMENT_REFERENCE,
    )

    print(
        json.dumps(
            booking,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    # ====================================================
    # 2. VERIFY SLOT IS NO LONGER AVAILABLE
    # ====================================================

    print()
    print("=" * 70)
    print("VERIFY SLOT LOCK")
    print("=" * 70)

    slots = await tools.call(
        "list_available_slots",

        slot_date=
            SLOT_DATE,

        doctor_id=
            DOCTOR_ID,

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

    # ====================================================
    # CHECK 13:30
    # ====================================================

    if isinstance(
        slots,
        dict,
    ):
        slot_items = [slots]

    elif isinstance(
        slots,
        list,
    ):
        slot_items = slots

    else:
        slot_items = []

    still_available = any(
        str(
            item.get(
                "start_time",
                ""
            )
        ).startswith(
            "13:30"
        )
        for item in slot_items
        if isinstance(
            item,
            dict,
        )
    )

    print()
    print(
        "13:30 STILL AVAILABLE:",
        still_available,
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )