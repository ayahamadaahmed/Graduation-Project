from __future__ import annotations

import asyncio
import json
import os

from dotenv import load_dotenv

from langchain_mcp_adapters.client import (
    MultiServerMCPClient,
)

from medmind.core.tool_executor import (
    MCPToolExecutor,
)


# ============================================================
# REAL IDS FROM CURRENT DATABASE
# ============================================================

MONA_DOCTOR_ID = (
    "955ed459-1f70-5bf3-a88c-709019974a1f"
)


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

    client = MultiServerMCPClient(
        {
            "healthcare": {
                "transport": "http",

                "url": mcp_url,

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

    print(
        "=" * 70
    )

    print(
        "AVAILABLE SLOTS TEST"
    )

    print(
        "=" * 70
    )

    # --------------------------------------------------------
    # 2026-08-20 instead of tomorrow.
    #
    # This is just a manual contract test so we have a
    # better chance of getting actual slots back and can
    # inspect their real JSON structure.
    # --------------------------------------------------------

    result = await tools.call(
        "list_available_slots",

        doctor_id=
            MONA_DOCTOR_ID,

        slot_date=
            "2026-08-20",

        limit=100,
    )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )