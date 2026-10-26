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
# TEST VALUES
# ============================================================
#
# استخدمي National ID تجريبي موجود في seed data فقط.
# ماتستخدميش رقم قومي حقيقي لشخص.
#
# تقدري تحطيه في .env:
#
# TEST_EXISTING_NATIONAL_ID=xxxxxxxxxxxxxx
#

NOT_FOUND_NATIONAL_ID = (
    "29901010000001"
)


async def print_lookup(
    *,
    tools: MCPToolExecutor,
    national_id: str,
    title: str,
) -> None:

    print()
    print(
        "=" * 70
    )

    print(
        title
    )

    print(
        "=" * 70
    )

    print(
        "National ID:",
        national_id,
    )

    try:

        result = await tools.call(
            "lookup_patient",

            national_id=
                national_id,

            language=
                "ar",
        )

        print()

        print(
            "RESULT:"
        )

        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

    except Exception as exc:

        print()

        print(
            "ERROR TYPE:"
        )

        print(
            type(exc).__name__
        )

        print()

        print(
            "ERROR:"
        )

        print(
            str(exc)
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

    existing_national_id = os.getenv(
        "TEST_EXISTING_NATIONAL_ID"
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
    # NOT FOUND TEST
    # ========================================================

    await print_lookup(
        tools=tools,

        national_id=
            NOT_FOUND_NATIONAL_ID,

        title=
            "TEST 1 - PATIENT NOT FOUND",
    )

    # ========================================================
    # EXISTING PATIENT TEST
    # ========================================================

    if existing_national_id:

        await print_lookup(
            tools=tools,

            national_id=
                existing_national_id,

            title=
                "TEST 2 - EXISTING PATIENT",
        )

    else:

        print()
        print(
            "=" * 70
        )

        print(
            "TEST 2 - EXISTING PATIENT SKIPPED"
        )

        print(
            "=" * 70
        )

        print(
            "Set TEST_EXISTING_NATIONAL_ID "
            "in .env using a demo/seed patient."
        )


if __name__ == "__main__":

    asyncio.run(
        main()
    )