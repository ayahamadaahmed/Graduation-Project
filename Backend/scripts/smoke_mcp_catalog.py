from __future__ import annotations

import asyncio
import json
import os

from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient


# ============================================================
# ENV
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
                "transport": "http",

                "url": MCP_URL,

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

def find_tool(
    tools,
    name: str,
):

    for tool in tools:

        if tool.name == name:

            return tool

    raise RuntimeError(
        f"MCP tool not found: {name}"
    )


def extract_payload(
    result,
):
    """
    Convert MCP content blocks into
    normal Python objects.

    If MCP returns multiple text blocks,
    collect all of them instead of
    returning only the first one.
    """

    if not isinstance(
        result,
        list,
    ):
        return result

    payloads = []

    for item in result:

        if not isinstance(
            item,
            dict,
        ):
            payloads.append(
                item
            )
            continue

        if item.get(
            "type"
        ) != "text":

            payloads.append(
                item
            )
            continue

        text = item.get(
            "text",
            "",
        )

        try:

            parsed = json.loads(
                text
            )

        except json.JSONDecodeError:

            parsed = text

        # If one content block itself
        # contains a list, flatten it.
        if isinstance(
            parsed,
            list,
        ):

            payloads.extend(
                parsed
            )

        else:

            payloads.append(
                parsed
            )

    # Keep a single object as an object.
    if len(
        payloads
    ) == 1:

        return payloads[0]

    return payloads


def pretty_print(
    title: str,
    data,
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

    if isinstance(
        data,
        (dict, list),
    ):

        print(
            json.dumps(
                data,
                indent=2,
                ensure_ascii=False,
            )
        )

    else:

        print(
            data
        )


# ============================================================
# TEST SPECIALTIES
# ============================================================

async def test_specialties(
    tools,
):

    tool = find_tool(
        tools,
        "list_specialties",
    )

    result = await tool.ainvoke(
        {}
    )

    payload = extract_payload(
        result
    )

    pretty_print(
        "SPECIALTIES",
        payload,
    )

    return payload


# ============================================================
# TEST DOCTORS
# ============================================================

async def test_doctors(
    tools,
):

    tool = find_tool(
        tools,
        "list_doctors",
    )

    result = await tool.ainvoke(
        {}
    )

    payload = extract_payload(
        result
    )

    pretty_print(
        "DOCTORS",
        payload,
    )

    return payload


# ============================================================
# TEST SERVICES
# ============================================================

async def test_services(
    tools,
):

    tool = find_tool(
        tools,
        "list_services",
    )

    result = await tool.ainvoke(
        {}
    )

    payload = extract_payload(
        result
    )

    pretty_print(
        "SERVICES",
        payload,
    )

    return payload


# ============================================================
# MAIN
# ============================================================

async def main() -> None:

    print(
        "Healthcare Catalog MCP Test"
    )

    print(
        f"MCP URL: {MCP_URL}"
    )

    print(
        f"Tenant: {TENANT_ID}"
    )

    client = (
        create_mcp_client()
    )

    print()
    print(
        "Connecting to MCP..."
    )

    tools = await (
        client.get_tools()
    )

    print(
        f"Loaded {len(tools)} tools."
    )

    # --------------------------------------------------------
    # SPECIALTIES
    # --------------------------------------------------------

    await test_specialties(
        tools
    )

    # --------------------------------------------------------
    # DOCTORS
    # --------------------------------------------------------

    await test_doctors(
        tools
    )

    # --------------------------------------------------------
    # SERVICES
    # --------------------------------------------------------

    await test_services(
        tools
    )

    print()
    print(
        "=" * 70
    )

    print(
        "CATALOG MCP TEST COMPLETED"
    )

    print(
        "=" * 70
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )