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

    Parsing is intentionally lossless:
    unknown or non-text content blocks are
    preserved rather than silently discarded.
    """

    # LangChain / MCP may stringify the
    # complete result structure.
    if isinstance(
        result,
        str,
    ):
        try:
            result = ast.literal_eval(
                result
            )

        except (
            ValueError,
            SyntaxError,
        ):
            try:
                return json.loads(
                    result
                )

            except (
                json.JSONDecodeError,
                TypeError,
            ):
                return result

    # Already-structured objects pass through.
    if not isinstance(
        result,
        list,
    ):
        return result

    parsed_items: list[Any] = []

    for item in result:

        # Preserve unknown/non-dict values.
        if not isinstance(
            item,
            dict,
        ):
            parsed_items.append(
                item
            )
            continue

        # Preserve MCP blocks that are not text.
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

        except (
            json.JSONDecodeError,
            TypeError,
        ):
            parsed = text

        # MCP text may itself contain a JSON list.
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