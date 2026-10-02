from __future__ import annotations

import asyncio

import pytest

from medmind.core.tool_executor import (
    MCPToolExecutor,
    MCPToolTimeoutError,
)


class FakeTool:

    name = "test_tool"

    def __init__(
        self,
        *,
        delay: float = 0.0,
        result=None,
    ) -> None:

        self.delay = delay
        self.result = (
            result
            if result is not None
            else {"ok": True}
        )

        self.calls = 0

    async def ainvoke(
        self,
        kwargs,
    ):

        self.calls += 1

        if self.delay:
            await asyncio.sleep(
                self.delay
            )

        return self.result


@pytest.mark.asyncio
async def test_tool_executor_returns_successful_result():

    tool = FakeTool(
        result={
            "ok": True,
        }
    )

    executor = MCPToolExecutor(
        [tool],
        timeout_seconds=1.0,
    )

    result = await executor.call(
        "test_tool",
        value="x",
    )

    assert result == {
        "ok": True,
    }

    assert tool.calls == 1


@pytest.mark.asyncio
async def test_tool_executor_times_out():

    tool = FakeTool(
        delay=0.2,
    )

    executor = MCPToolExecutor(
        [tool],
        timeout_seconds=0.01,
    )

    with pytest.raises(
        MCPToolTimeoutError,
    ) as exc_info:

        await executor.call(
            "test_tool"
        )

    assert (
        exc_info.value.tool_name
        == "test_tool"
    )

    assert tool.calls == 1


def test_tool_executor_rejects_invalid_timeout():

    tool = FakeTool()

    with pytest.raises(
        ValueError,
        match="timeout_seconds",
    ):
        MCPToolExecutor(
            [tool],
            timeout_seconds=0,
        )