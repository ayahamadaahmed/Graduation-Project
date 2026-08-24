from __future__ import annotations

import ast
import json

from dataclasses import dataclass
from typing import Any

from langchain.agents import (
    create_agent,
)

from medmind.memory.models import (
    ChatMessage,
)

from medmind.prompts.system import (
    build_system_prompt,
)

from medmind.state.models import (
    SessionState,
)


# ============================================================
# RESULT TYPES
# ============================================================

@dataclass
class ToolObservation:

    name: str

    data: Any


@dataclass
class AgentRunResult:

    reply: str

    tool_calls: list[
        dict[str, Any]
    ]

    tool_observations: list[
        ToolObservation
    ]


# ============================================================
# TOOL CONTENT PARSER
# ============================================================

def _parse_tool_content(
    content,
):
    """
    MCP ToolMessage content currently arrives
    as a Python-like list of text blocks.

    Convert those blocks into normal Python data.
    """

    if isinstance(
        content,
        str,
    ):

        # LangChain may stringify the MCP list.
        try:
            content = ast.literal_eval(
                content
            )

        except Exception:

            try:
                return json.loads(
                    content
                )

            except Exception:
                return content

    if not isinstance(
        content,
        list,
    ):
        return content

    parsed_items = []

    for item in content:

        if not isinstance(
            item,
            dict,
        ):
            continue

        if item.get(
            "type"
        ) != "text":
            continue

        text = item.get(
            "text",
            "",
        )

        try:

            parsed = json.loads(
                text
            )

        except Exception:

            parsed = text

        if isinstance(
            parsed,
            list,
        ):

            parsed_items.extend(
                parsed
            )

        else:

            parsed_items.append(
                parsed
            )

    if len(
        parsed_items
    ) == 1:

        return parsed_items[0]

    return parsed_items


# ============================================================
# AGENT
# ============================================================

class MedMindReadAgent:

    def __init__(
        self,
        *,
        model,
        tools,
    ) -> None:

        self.model = model
        self.tools = tools

    async def run(
        self,
        *,
        user_message: str,
        language: str,
        history: list[ChatMessage],
        state: SessionState,
    ) -> AgentRunResult:

        system_prompt = (
            build_system_prompt(
                language=language,
                state=state,
            )
        )

        agent = create_agent(
            model=self.model,
            tools=self.tools,
            system_prompt=
                system_prompt,
        )

        # ----------------------------------------------------
        # Conversation history
        # ----------------------------------------------------

        messages = []

        for message in history:

            messages.append(
                {
                    "role":
                        message.role,

                    "content":
                        message.content,
                }
            )

        messages.append(
            {
                "role":
                    "user",

                "content":
                    user_message,
            }
        )

        # ----------------------------------------------------
        # Execute
        # ----------------------------------------------------

        result = await agent.ainvoke(
            {
                "messages":
                    messages
            }
        )

        result_messages = (
            result.get(
                "messages",
                [],
            )
        )

        if not result_messages:

            raise RuntimeError(
                "Agent returned no messages."
            )

        # ----------------------------------------------------
        # Tool calls
        # ----------------------------------------------------

        tool_calls = []

        for message in result_messages:

            calls = getattr(
                message,
                "tool_calls",
                None,
            )

            if not calls:
                continue

            for call in calls:

                tool_calls.append(
                    {
                        "name":
                            call.get(
                                "name"
                            ),

                        "args":
                            call.get(
                                "args",
                                {},
                            ),
                    }
                )

        # ----------------------------------------------------
        # Tool observations
        # ----------------------------------------------------

        observations = []

        for message in result_messages:

            message_type = (
                type(message)
                .__name__
            )

            if (
                message_type
                != "ToolMessage"
            ):
                continue

            name = getattr(
                message,
                "name",
                None,
            )

            if not name:
                continue

            content = getattr(
                message,
                "content",
                None,
            )

            data = (
                _parse_tool_content(
                    content
                )
            )

            observations.append(
                ToolObservation(
                    name=name,
                    data=data,
                )
            )

        # ----------------------------------------------------
        # Final response
        # ----------------------------------------------------

        final_message = (
            result_messages[-1]
        )

        content = getattr(
            final_message,
            "content",
            "",
        )

        if isinstance(
            content,
            str,
        ):

            reply = content

        else:

            reply = str(
                content
            )

        return AgentRunResult(
            reply=reply,

            tool_calls=
                tool_calls,

            tool_observations=
                observations,
        )