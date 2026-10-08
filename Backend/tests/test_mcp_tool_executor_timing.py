import asyncio
import logging

import pytest

from agent.medmind.core.tool_executor import (
    MCPToolExecutor,
)


class FakeTool:

    name = "fake_tool"

    async def ainvoke(
        self,
        kwargs,
    ):
        return {
            "ok": True,
        }


class FailingTool:

    name = "failing_tool"

    async def ainvoke(
        self,
        kwargs,
    ):
        raise RuntimeError(
            "test failure"
        )


def test_mcp_tool_executor_returns_result_and_logs_timing(
    caplog,
):

    executor = MCPToolExecutor(
        [
            FakeTool(),
        ]
    )

    with caplog.at_level(
        logging.INFO,
        logger="uvicorn.error",
    ):
            result = asyncio.run(
            executor.call(
                "fake_tool"
            )
        )

    assert result == {
        "ok": True,
    }

    assert (
        "mcp_tool_timing "
        "tool=fake_tool"
        in caplog.text
    )

    assert (
        "status=success"
        in caplog.text
    )

    assert (
        "invoke_ms="
        in caplog.text
    )

    assert (
        "parse_ms="
        in caplog.text
    )

    assert (
        "total_ms="
        in caplog.text
    )


def test_mcp_tool_executor_logs_failure_and_reraises(
    caplog,
):

    executor = MCPToolExecutor(
        [
            FailingTool(),
        ]
    )

    with caplog.at_level(
        logging.ERROR,
        logger=(
            "agent.medmind.core."
            "tool_executor"
        ),
    ):

        with pytest.raises(
            RuntimeError,
            match="test failure",
        ):

            asyncio.run(
                executor.call(
                    "failing_tool"
                )
            )

    assert (
        "mcp_tool_timing "
        "tool=failing_tool"
        in caplog.text
    )

    assert (
        "status=error"
        in caplog.text
    )

    assert (
        "error_type=RuntimeError"
        in caplog.text
    )