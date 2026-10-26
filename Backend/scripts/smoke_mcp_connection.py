from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

from langchain_mcp_adapters.client import (
    MultiServerMCPClient,
)


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv(
    override=True,
)


MCP_URL = os.getenv(
    "MCP_URL",
    "http://127.0.0.1:9000/mcp",
)

TENANT_ID = os.getenv(
    "TENANT_ID",
    "clinic-001",
)


# ============================================================
# MCP CLIENT
# ============================================================

def create_mcp_client() -> MultiServerMCPClient:

    return MultiServerMCPClient(
        {
            "healthcare": {
                "transport":
                    "http",

                "url":
                    MCP_URL,

                "headers": {
                    # Agent -> MCP credential (MCP_AUTH_MODE).
                    **(
                        {"X-MedMind-Service-Token": os.environ["MCP_SERVER_TOKEN"]}
                        if os.getenv("MCP_SERVER_TOKEN")
                        else {}
                    ),
                    "X-Tenant-ID":
                        TENANT_ID,
                },
            }
        }
    )


# ============================================================
# HELPERS
# ============================================================

def print_tools(
    tools,
) -> None:

    print()
    print(
        "=" * 70
    )

    print(
        f"LOADED MCP TOOLS: {len(tools)}"
    )

    print(
        "=" * 70
    )

    for index, tool in enumerate(
        tools,
        start=1,
    ):

        print()
        print(
            f"[{index}] {tool.name}"
        )

        print(
            f"Description: {tool.description}"
        )


def print_schemas(
    tools,
) -> None:

    print()
    print(
        "=" * 70
    )

    print(
        "TOOL SCHEMAS"
    )

    print(
        "=" * 70
    )

    for tool in tools:

        print()
        print(
            "-" * 70
        )

        print(
            tool.name
        )

        args_schema = getattr(
            tool,
            "args_schema",
            None,
        )

        if args_schema is None:

            print(
                "No schema"
            )

            continue

        try:

            schema = (
                args_schema
                .model_json_schema()
            )

            print(
                schema
            )

        except Exception:

            print(
                args_schema
            )


def find_tool(
    tools,
    name: str,
):

    for tool in tools:

        if tool.name == name:

            return tool

    return None


# ============================================================
# MANUAL TOOL TEST
# ============================================================

async def test_provider_info(
    tools,
) -> None:

    tool = find_tool(
        tools,
        "get_provider_info",
    )

    if tool is None:

        print()
        print(
            "get_provider_info tool not found."
        )

        return

    print()
    print(
        "=" * 70
    )

    print(
        "MANUAL TOOL TEST"
    )

    print(
        "=" * 70
    )

    print(
        "Calling get_provider_info..."
    )

    result = await tool.ainvoke(
        {}
    )

    print()
    print(
        "RESULT:"
    )

    print(
        result
    )
async def test_specialties(
    tools,
) -> None:

    tool = find_tool(
        tools,
        "list_specialties",
    )

    assert tool is not None

    print()
    print(
        "=" * 70
    )

    print(
        "SPECIALTIES TEST"
    )

    print(
        "=" * 70
    )

    result = await tool.ainvoke(
        {}
    )

    print(
        result
    )

# ============================================================
# MAIN
# ============================================================

async def main() -> None:

    print(
        "Healthcare MCP Test"
    )

    print(
        f"MCP URL: {MCP_URL}"
    )

    print(
        f"Tenant: {TENANT_ID}"
    )

    # --------------------------------------------------------
    # Connect
    # --------------------------------------------------------

    client = (
        create_mcp_client()
    )

    print()
    print(
        "Connecting to MCP..."
    )

    # --------------------------------------------------------
    # Load tools
    # --------------------------------------------------------

    tools = await (
        client.get_tools()
    )

    print_tools(
        tools
    )

    # --------------------------------------------------------
    # Show tool schemas
    # --------------------------------------------------------

    print_schemas(
        tools
    )

    # --------------------------------------------------------
    # Manual MCP -> Backend -> DB test
    # --------------------------------------------------------

    await test_provider_info(
        tools
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )