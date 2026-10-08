from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from langchain.agents import (
    create_agent,
)

from .tool_result_parser import (
    parse_mcp_result,
)

from .tool_result_parser import (
    parse_mcp_result,
)

from medmind.memory.models import (
    ChatMessage,
)

from medmind.tenancy.context import (
    TenantContext,
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
# AGENT
# ============================================================

class MedMindReadAgent:

    def __init__(
        self,
        *,
        model,
        tools,
        tenant_context: TenantContext | None = None,
    ) -> None:

        self.model = model
        self.tools = tools
        self.tenant_context = (
            tenant_context
        )

    async def verbalize_services(
        self,
        *,
        service_names: list[str],
        language: str,
        has_more: bool,
        timeout_seconds: float = 0.8,
    ) -> str | None:

        names = [
            name.strip()
            for name in service_names
            if isinstance(name, str)
            and name.strip()
        ]

        if not names:
            return None

        language_name = (
            "English"
            if language == "en"
            else "Egyptian Arabic"
        )

        services_text = "\n".join(
            f"- {name}"
            for name in names
        )

        prompt = f"""
You format MedMind responses for natural phone conversation.

Using ONLY the trusted service facts below, produce one short,
natural spoken sentence in {language_name}.

Rules:
- Do not use a fixed sentence template.
- Phrase the response naturally like a receptionist speaking.
- You may reword service labels when the medical meaning stays identical.
- Do not mechanically read the database labels one by one.
- Do not invent, remove, or change any service.
- Do not turn screening, examination, evaluation, or consultation into treatment.
- Do not diagnose or recommend medication or treatment.
- Mention all supplied services naturally.
- Other services exist: {"yes" if has_more else "no"}.
- If other services exist, mention that naturally.
- Keep it concise and suitable for voice.
- Return only the spoken response.

Trusted services:
{services_text}
""".strip()

        try:

            verbalizer_model = (
                self.model.bind(
                    temperature=0.35
                )
            )

            result = await asyncio.wait_for(
                verbalizer_model.ainvoke(
                    [
                        {
                            "role": "user",
                            "content": prompt,
                        }
                    ]
                ),
                timeout=timeout_seconds,
            )

        except Exception:
            return None

        content = getattr(
            result,
            "content",
            "",
        )

        if not isinstance(
            content,
            str,
        ):
            return None

        reply = " ".join(
            content.split()
        ).strip()

        if (
            not reply
            or len(reply) > 320
        ):
            return None

        return reply

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
                tenant_context=
                    self.tenant_context,
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
                parse_mcp_result(
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