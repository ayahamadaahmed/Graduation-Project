from __future__ import annotations

import ast
import json
from typing import Any


def parse_mcp_result(
    result: Any,
) -> Any:
    """
    Convert MCP / LangChain tool content
    into normal Python objects.
    """

    if isinstance(
        result,
        str,
    ):
        try:
            result = ast.literal_eval(
                result
            )

        except Exception:
            try:
                return json.loads(
                    result
                )

            except Exception:
                return result

    if not isinstance(
        result,
        list,
    ):
        return result

    parsed_items = []

    for item in result:

        if not isinstance(
            item,
            dict,
        ):
            parsed_items.append(
                item
            )

            continue

        if item.get(
            "type"
        ) != "text":

            parsed_items.append(
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


class MCPToolExecutor:
    """
    Small wrapper around MCP tools.

    Workflow code never needs to know
    LangChain's tool message format.
    """

    def __init__(
        self,
        tools,
    ) -> None:

        self._tools = {
            tool.name: tool
            for tool in tools
        }

    def has(
        self,
        name: str,
    ) -> bool:

        return (
            name
            in self._tools
        )

    async def call(
        self,
        name: str,
        **kwargs,
    ) -> Any:

        tool = self._tools.get(
            name
        )

        if tool is None:

            raise RuntimeError(
                f"MCP tool not found: {name}"
            )

        result = await tool.ainvoke(
            kwargs
        )

        return parse_mcp_result(
            result
        )