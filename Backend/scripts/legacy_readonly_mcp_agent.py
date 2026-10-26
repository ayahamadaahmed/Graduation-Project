from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import (
    MultiServerMCPClient,
)


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv(
    override=True,
)


OPENAI_API_KEY = os.getenv(
    "OPENAI_API_KEY"
)

OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-4.1",
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
# PHASE 1:
# READ-ONLY TOOLS
# ============================================================

READ_TOOL_NAMES = {
    "get_provider_info",
    "list_specialties",
    "list_doctors",
    "list_services",
    "list_available_slots",
}


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
You are MedMind, an AI assistant for a healthcare
booking platform.

You have access to trusted healthcare tools through MCP.

The healthcare backend and database are the source of truth.

GENERAL RULES:

1. Never invent:
   - doctors
   - specialties
   - services
   - prices
   - appointment slots
   - provider information
   - IDs

2. Use the available tools whenever the user asks about
   healthcare provider data.

3. Never write SQL.

4. Never guess UUID values.

5. Reply in the same language as the user.

6. If the user speaks Arabic, reply naturally in
   Egyptian Arabic.

7. Keep responses concise and helpful.


SPECIALTY RULE:

When the user asks for doctors using a specialty name,
for example:

"مين دكاترة الجلدية؟"

you should:

1. Call list_specialties.
2. Find the matching specialty using:
   - name_ar
   - name_en
   - code
3. Read its exact specialty ID.
4. Call list_doctors using that specialty_id.
5. Answer using only the doctors returned by the tool.


DOCTOR RULE:

Never guess a doctor's specialty ID.

If a specialty name is provided instead of an ID,
resolve the specialty first using list_specialties.


SLOTS RULE:

When asking for available slots:

- use list_available_slots
- use the exact doctor_id when a doctor is specified
- never invent appointment times


SERVICE RULE:

When asked about healthcare services or prices,
use list_services.

Do not invent prices or services.
"""


# ============================================================
# VALIDATION
# ============================================================

def validate_environment() -> None:

    if not OPENAI_API_KEY:

        raise RuntimeError(
            "OPENAI_API_KEY is missing.\n"
            "Add it to your .env file."
        )

    print(
        "=" * 70
    )

    print(
        "MEDMIND AGENT V1"
    )

    print(
        "=" * 70
    )

    print(
        f"Model: {OPENAI_MODEL}"
    )

    print(
        f"MCP: {MCP_URL}"
    )

    print(
        f"Tenant: {TENANT_ID}"
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
# FILTER TOOLS
# ============================================================

def filter_read_tools(
    tools,
):

    read_tools = [
        tool
        for tool in tools
        if tool.name in READ_TOOL_NAMES
    ]

    return read_tools


# ============================================================
# DISPLAY TOOLS
# ============================================================

def print_tools(
    tools,
) -> None:

    print()
    print(
        "=" * 70
    )

    print(
        "TOOLS AVAILABLE TO AGENT"
    )

    print(
        "=" * 70
    )

    for tool in tools:

        print(
            f"- {tool.name}"
        )


# ============================================================
# MODEL
# ============================================================

def create_model() -> ChatOpenAI:

    return ChatOpenAI(
        model=OPENAI_MODEL,

        temperature=0,

        timeout=60,
    )


# ============================================================
# BUILD AGENT
# ============================================================

def build_agent(
    model,
    tools,
):

    return create_agent(
        model=model,

        tools=tools,

        system_prompt=
            SYSTEM_PROMPT,
    )


# ============================================================
# TRACE
# ============================================================

def print_trace(
    messages,
) -> None:

    print()
    print(
        "=" * 70
    )

    print(
        "AGENT TRACE"
    )

    print(
        "=" * 70
    )

    for index, message in enumerate(
        messages,
        start=1,
    ):

        print()
        print(
            f"[{index}] "
            f"{type(message).__name__}"
        )

        # ----------------------------------------------------
        # Tool calls requested by the LLM
        # ----------------------------------------------------

        tool_calls = getattr(
            message,
            "tool_calls",
            None,
        )

        if tool_calls:

            for tool_call in tool_calls:

                print(
                    "TOOL CALL:"
                )

                print(
                    f"  name: "
                    f"{tool_call.get('name')}"
                )

                print(
                    f"  args: "
                    f"{tool_call.get('args')}"
                )

        # ----------------------------------------------------
        # ToolMessage name
        # ----------------------------------------------------

        tool_name = getattr(
            message,
            "name",
            None,
        )

        if tool_name:

            print(
                f"TOOL NAME: {tool_name}"
            )

        # ----------------------------------------------------
        # Content
        # ----------------------------------------------------

        content = getattr(
            message,
            "content",
            None,
        )

        if content:

            print(
                "CONTENT:"
            )

            print(
                content
            )


# ============================================================
# RUN ONE QUERY
# ============================================================

async def run_query(
    agent,
    user_message: str,
) -> None:

    print()
    print(
        "=" * 70
    )

    print(
        "USER"
    )

    print(
        "=" * 70
    )

    print(
        user_message
    )

    result = await agent.ainvoke(
        {
            "messages": [
                {
                    "role":
                        "user",

                    "content":
                        user_message,
                }
            ]
        }
    )

    messages = result.get(
        "messages",
        [],
    )

    print_trace(
        messages
    )

    if not messages:

        print(
            "No response returned."
        )

        return

    final_message = (
        messages[-1]
    )

    print()
    print(
        "=" * 70
    )

    print(
        "FINAL RESPONSE"
    )

    print(
        "=" * 70
    )

    print(
        final_message.content
    )


# ============================================================
# MAIN
# ============================================================

async def main() -> None:

    validate_environment()

    # --------------------------------------------------------
    # 1. MCP
    # --------------------------------------------------------

    print()
    print(
        "Connecting to MCP..."
    )

    mcp_client = (
        create_mcp_client()
    )

    all_tools = await (
        mcp_client.get_tools()
    )

    print(
        f"MCP returned "
        f"{len(all_tools)} tools."
    )

    # --------------------------------------------------------
    # 2. READ-ONLY TOOLS
    # --------------------------------------------------------

    tools = filter_read_tools(
        all_tools
    )

    print_tools(
        tools
    )

    expected = (
        READ_TOOL_NAMES
    )

    loaded = {
        tool.name
        for tool in tools
    }

    missing = (
        expected - loaded
    )

    if missing:

        raise RuntimeError(
            "Missing MCP tools: "
            + ", ".join(
                sorted(missing)
            )
        )

    # --------------------------------------------------------
    # 3. LLM
    # --------------------------------------------------------

    print()
    print(
        "Creating OpenAI model..."
    )

    model = create_model()

    # --------------------------------------------------------
    # 4. AGENT
    # --------------------------------------------------------

    print(
        "Creating MedMind agent..."
    )

    agent = build_agent(
        model,
        tools,
    )

    # --------------------------------------------------------
    # 5. FIRST TEST
    # --------------------------------------------------------

    await run_query(
        agent,
        "مين دكاترة الجلدية؟",
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )