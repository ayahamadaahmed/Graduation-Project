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
# DEMO TEST DATA
# ============================================================

DEMO_NATIONAL_ID = "29901010000002"
DEMO_PATIENT_NAME = "Test Patient"
DEMO_PHONE = "01000000002"


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

    # ========================================================
    # TEST 1 - RESOLVE / CREATE PATIENT
    # ========================================================

    print()
    print(
        "=" * 70
    )

    print(
        "TEST 1 - RESOLVE PATIENT"
    )

    print(
        "=" * 70
    )

    resolved = await tools.call(
        "resolve_patient",

        national_id=
            DEMO_NATIONAL_ID,

        patient_name=
            DEMO_PATIENT_NAME,

        phone=
            DEMO_PHONE,

        preferred_language=
            "ar",

        channel=
            "web",
    )

    print(
        json.dumps(
            resolved,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    # ========================================================
    # TEST 2 - LOOKUP SAME PATIENT
    # ========================================================

    print()
    print(
        "=" * 70
    )

    print(
        "TEST 2 - LOOKUP CREATED PATIENT"
    )

    print(
        "=" * 70
    )

    lookup = await tools.call(
        "lookup_patient",

        national_id=
            DEMO_NATIONAL_ID,

        language=
            "ar",
    )

    print(
        json.dumps(
            lookup,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )