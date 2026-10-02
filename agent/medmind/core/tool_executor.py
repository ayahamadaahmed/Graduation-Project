from __future__ import annotations

import re
from typing import Any
import logging
import time
import asyncio

from .tool_result_parser import (
    parse_mcp_result,
)

logger = logging.getLogger(
    "uvicorn.error"
)

class MCPToolTimeoutError(
    RuntimeError
):
    """
    Raised when an MCP tool invocation exceeds
    the MedMind outer safety timeout.
    """

    def __init__(
        self,
        *,
        tool_name: str,
        timeout_seconds: float,
    ) -> None:

        self.tool_name = tool_name
        self.timeout_seconds = timeout_seconds

        super().__init__(
            "MCP tool timed out: "
            f"{tool_name}"
        )

class MCPToolExecutor:
    """
    Small wrapper around MCP tools.

    Workflow code never needs to know
    LangChain's tool message format.
    """
    def __init__(
        self,
        tools,
        *,
        timeout_seconds: float = 35.0,
    ) -> None:

        if timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be greater than 0"
            )

        self._tools = {
            tool.name: tool
            for tool in tools
        }

        self._timeout_seconds = (
            float(
                timeout_seconds
            )
        )

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

        total_started_at = (
            time.perf_counter()
        )

        try:

            invoke_started_at = (
                time.perf_counter()
            )

            result = await asyncio.wait_for(
                tool.ainvoke(
                    kwargs
                ),
                timeout=
                    self._timeout_seconds,
            )
            logger.info(
                "mcp_raw_result_shape "
                "tool=%s "
                "result_type=%s "
                "list_len=%s "
                "item_types=%s "
                "item_keys=%s",
                name,
                type(result).__name__,
                (
                    len(result)
                    if isinstance(result, list)
                    else None
                ),
                (
                    [
                        type(item).__name__
                        for item in result
                    ]
                    if isinstance(result, list)
                    else None
                ),
                (
                    [
                        sorted(item.keys())
                        if isinstance(item, dict)
                        else None
                        for item in result
                    ]
                    if isinstance(result, list)
                    else None
                ),
            )

            first_item = (
                result[0]
                if (
                    isinstance(result, list)
                    and len(result) == 1
                    and isinstance(result[0], dict)
                )
                else None
            )

            raw_text = (
                first_item.get("text")
                if (
                    isinstance(first_item, dict)
                    and isinstance(
                        first_item.get("text"),
                        str,
                    )
                )
                else None
            )

            error_code = None
            http_status = None

            if raw_text is not None:

                code_match = re.search(
                    r"\b([A-Z][A-Z0-9_]{2,})\s*:",
                    raw_text,
                )

                if code_match:
                    error_code = code_match.group(1)

                status_match = re.search(
                    r"HTTP\s+(\d{3})",
                    raw_text,
                )

                if status_match:
                    http_status = int(
                        status_match.group(1)
                    )

            logger.info(
                "mcp_raw_error_metadata "
                "tool=%s "
                "error_code=%s "
                "http_status=%s",
                name,
                error_code,
                http_status,
            )

            logger.info(
                "mcp_raw_error_probe "
                "tool=%s "
                "block_type=%s "
                "text_len=%s "
                "starts_with_error=%s "
                "contains_http_409=%s",
                name,
                (
                    first_item.get("type")
                    if isinstance(first_item, dict)
                    else None
                ),
                (
                    len(raw_text)
                    if raw_text is not None
                    else None
                ),
                (
                    raw_text.lstrip().lower().startswith("error")
                    if raw_text is not None
                    else False
                ),
                (
                    "HTTP 409" in raw_text
                    if raw_text is not None
                    else False
                ),
            )
            
            invoke_ms = (
                (
                    time.perf_counter()
                    - invoke_started_at
                )
                * 1000
            )

            parse_started_at = (
                time.perf_counter()
            )

            parsed_result = (
                parse_mcp_result(
                    result
                )
            )

            parse_ms = (
                (
                    time.perf_counter()
                    - parse_started_at
                )
                * 1000
            )

            total_ms = (
                (
                    time.perf_counter()
                    - total_started_at
                )
                * 1000
            )

            logger.info(
                "mcp_tool_timing "
                "tool=%s "
                "invoke_ms=%.2f "
                "parse_ms=%.2f "
                "total_ms=%.2f "
                "status=success",
                name,
                invoke_ms,
                parse_ms,
                total_ms,
            )

            return parsed_result

        except asyncio.TimeoutError as exc:

            total_ms = (
                (
                    time.perf_counter()
                    - total_started_at
                )
                * 1000
            )

            logger.warning(
                "mcp_tool_timing "
                "tool=%s "
                "total_ms=%.2f "
                "status=timeout "
                "timeout_seconds=%.2f",
                name,
                total_ms,
                self._timeout_seconds,
            )

            raise MCPToolTimeoutError(
                tool_name=name,
                timeout_seconds=
                    self._timeout_seconds,
            ) from exc

        except Exception as exc:

            total_ms = (
                (
                    time.perf_counter()
                    - total_started_at
                )
                * 1000
            )

            logger.exception(
                "mcp_tool_timing "
                "tool=%s "
                "total_ms=%.2f "
                "status=error "
                "error_type=%s",
                name,
                total_ms,
                type(
                    exc
                ).__name__,
            )

            raise