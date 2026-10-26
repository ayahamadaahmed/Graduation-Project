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

    # ========================================================
    # MCP
    # ========================================================

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
    # TEST
    # ========================================================

    print(
        "=" * 70
    )

    print(
        "DOCTOR SERVICES MCP TEST"
    )

    print(
        "=" * 70
    )

    result = await tools.call(
        "list_services",

        doctor_id=
            MONA_DOCTOR_ID,

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