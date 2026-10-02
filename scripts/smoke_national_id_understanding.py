from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)
from medmind.understanding.orchestrator import (
    UnderstandingOrchestrator,
)
from medmind.understanding.tool_planner import (
    ToolPlanner,
)


async def main() -> None:

    load_dotenv(
        override=False
    )

    model = ChatOpenAI(
        model=(
            os.getenv("TOOL_PLANNER_MODEL")
            or os.getenv("OPENAI_MODEL")
            or "gpt-4.1"
        ),
        temperature=0,
        timeout=30,
    )

    orchestrator = UnderstandingOrchestrator(
        router=SemanticCapabilityRouter(),
        planner=ToolPlanner(
            model=model
        ),
        top_k=8,
    )

    result = await orchestrator.understand(
        message="12345678912345",
        context={
            "active_capability":
                "appointment.create",

            "stage":
                "awaiting_national_id",

            "pending_confirmation":
                False,

            "collected_arguments": {},
        },
    )

    print(
        "status =",
        result.status,
    )

    print(
        "capability =",
        result.capability,
    )

    print(
        "arguments =",
        result.arguments,
    )

    print(
        "confirmation =",
        result.confirmation,
    )

    print(
        "attempts =",
        result.attempts,
    )

    print(
        "broad =",
        result.used_broad_candidates,
    )


asyncio.run(
    main()
)
