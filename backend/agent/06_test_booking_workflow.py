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

from medmind.workflows.booking import (
    BookingWorkflow,
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
    # LLM
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

    workflow = BookingWorkflow(
        tools=tools
    )

    # --------------------------------------------------------
    # State
    # --------------------------------------------------------

    state = SessionState(
        session_id=
            "booking-workflow-test-001",

        tenant_id=
            tenant_id,
    )

    history: list[
        ChatMessage
    ] = []

    # ========================================================
    # TURN 1
    # ========================================================

    message = (
        "عايزة احجز جلدية"
    )

    language = detect_language(
        message
    )

    state.language = language

    nlu_result = await (
        nlu.understand(
            message=message,
            language=language,
            state=state,
            history=history,
        )
    )

    print()
    print(
        "=" * 70
    )
    print(
        "TURN 1"
    )
    print(
        "=" * 70
    )

    print(
        "USER:",
        message,
    )

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

    workflow_result = await (
        workflow.handle(
            state=state,
            nlu=nlu_result,
        )
    )

    print()
    print(
        "MEDMIND:",
        workflow_result.reply,
    )

    print_state(
        state
    )

    history.append(
        ChatMessage(
            role="user",
            content=message,
        )
    )

    history.append(
        ChatMessage(
            role="assistant",
            content=
                workflow_result.reply,
        )
    )

    # ========================================================
    # TURN 2
    # ========================================================

    message = "منى"

    language = detect_language(
        message
    )

    state.language = language

    nlu_result = await (
        nlu.understand(
            message=message,
            language=language,
            state=state,
            history=history,
        )
    )

    print()
    print(
        "=" * 70
    )
    print(
        "TURN 2"
    )
    print(
        "=" * 70
    )

    print(
        "USER:",
        message,
    )

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

    workflow_result = await (
        workflow.handle(
            state=state,
            nlu=nlu_result,
        )
    )

    print()
    print(
        "MEDMIND:",
        workflow_result.reply,
    )

    print_state(
        state
    )

    history.append(
        ChatMessage(
            role="user",
            content=message,
        )
    )

    history.append(
        ChatMessage(
            role="assistant",
            content=
                workflow_result.reply,
        )
    )

    # ========================================================
    # TURN 3
    # ========================================================

    message = "بعد بكرة"

    language = detect_language(
        message
    )

    state.language = language

    nlu_result = await (
        nlu.understand(
            message=message,
            language=language,
            state=state,
            history=history,
        )
    )

    print()
    print(
        "=" * 70
    )
    print(
        "TURN 3"
    )
    print(
        "=" * 70
    )

    print(
        "USER:",
        message,
    )

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

    workflow_result = await (
        workflow.handle(
            state=state,
            nlu=nlu_result,
        )
    )

    print()
    print(
        "MEDMIND:",
        workflow_result.reply,
    )

    print_state(
        state
    )


    history.append(
        ChatMessage(
            role="user",
            content=message,
        )
    )

    history.append(
        ChatMessage(
            role="assistant",
            content=
                workflow_result.reply,
        )
    )


    # ========================================================
    # TURN 4
    # ========================================================

    message = "1 ونص"

    language = detect_language(
        message
    )

    state.language = language

    nlu_result = await (
        nlu.understand(
            message=message,
            language=language,
            state=state,
            history=history,
        )
    )

    print()
    print(
        "=" * 70
    )

    print(
        "TURN 4"
    )

    print(
        "=" * 70
    )

    print(
        "USER:",
        message,
    )

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

    workflow_result = await (
        workflow.handle(
            state=state,
            nlu=nlu_result,
        )
    )

    print()
    print(
        "MEDMIND:",
        workflow_result.reply,
    )

    print_state(
        state
    )


    history.append(
        ChatMessage(
            role="user",
            content=message,
        )
    )

    history.append(
        ChatMessage(
            role="assistant",
            content=
                workflow_result.reply,
        )
    )


    # ========================================================
    # TURN 5 - NATIONAL ID NOT FOUND
    # ========================================================

    message = "29901010000001"

    language = detect_language(
        message
    )

    # Digits-only message has no language signal,
    # so preserve the current conversation language.
    if language not in {
        "ar",
        "en",
        "mixed",
    }:
        language = state.language

    state.language = (
        state.language
    )

    nlu_result = await (
        nlu.understand(
            message=message,
            language=state.language,
            state=state,
            history=history,
        )
    )

    print()
    print(
        "=" * 70
    )
    print(
        "TURN 5"
    )
    print(
        "=" * 70
    )

    print(
        "USER:",
        message,
    )

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

    workflow_result = await (
        workflow.handle(
            state=state,
            nlu=nlu_result,
        )
    )

    print()
    print(
        "MEDMIND:",
        workflow_result.reply,
    )

    print_state(
        state
    )

    # ========================================================
    # TURN 6 - PATIENT NAME
    # ========================================================

    message = "أية أحمد"

    nlu_result = await nlu.understand(
        message=message,
        language=state.language,
        state=state,
        history=history,
    )

    print()
    print("=" * 70)
    print("TURN 6")
    print("=" * 70)

    print(
        "USER:",
        message,
    )

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

    print_state(
        state
    )

    # ========================================================
    # TURN 7 - PHONE
    # ========================================================

    message = "01000000003"

    nlu_result = await nlu.understand(
        message=message,
        language=state.language,
        state=state,
        history=history,
    )

    print()
    print("=" * 70)
    print("TURN 7")
    print("=" * 70)

    print(
        "USER:",
        message,
    )

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

    print_state(
        state
    )

    # ========================================================
    # TURN 8 - CONFIRM BOOKING
    # ========================================================

    message = "أيوه"

    nlu_result = await nlu.understand(
        message=message,
        language=state.language,
        state=state,
        history=history,
    )

    print()
    print("=" * 70)
    print("TURN 8")
    print("=" * 70)

    print(
        "USER:",
        message,
    )

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


if __name__ == "__main__":

    asyncio.run(
        main()
    )
