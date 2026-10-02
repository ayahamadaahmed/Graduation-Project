from __future__ import annotations

import pytest

from medmind.memory.conversation import (
    ConversationMemory,
)


@pytest.mark.asyncio
async def test_recent_history_is_limited():

    memory = ConversationMemory(
        recent_message_limit=3,
        max_stored_messages=5,
    )

    for index in range(6):
        await memory.add_user_message(
            session_id="session-1",
            content=f"message-{index}",
        )

    recent = await memory.get_recent(
        "session-1"
    )

    assert [
        message.content
        for message in recent
    ] == [
        "message-3",
        "message-4",
        "message-5",
    ]


@pytest.mark.asyncio
async def test_stored_history_is_bounded():

    memory = ConversationMemory(
        recent_message_limit=3,
        max_stored_messages=5,
    )

    for index in range(10):
        await memory.add_user_message(
            session_id="session-1",
            content=f"message-{index}",
        )

    all_messages = await memory.get_all(
        "session-1"
    )

    assert len(all_messages) == 5

    assert [
        message.content
        for message in all_messages
    ] == [
        "message-5",
        "message-6",
        "message-7",
        "message-8",
        "message-9",
    ]


@pytest.mark.asyncio
async def test_sessions_are_isolated():

    memory = ConversationMemory(
        recent_message_limit=3,
        max_stored_messages=5,
    )

    await memory.add_user_message(
        session_id="session-a",
        content="A",
    )

    await memory.add_user_message(
        session_id="session-b",
        content="B",
    )

    session_a = await memory.get_all(
        "session-a"
    )

    session_b = await memory.get_all(
        "session-b"
    )

    assert [
        message.content
        for message in session_a
    ] == ["A"]

    assert [
        message.content
        for message in session_b
    ] == ["B"]


@pytest.mark.asyncio
async def test_clear_removes_session_history():

    memory = ConversationMemory(
        recent_message_limit=3,
        max_stored_messages=5,
    )

    await memory.add_user_message(
        session_id="session-1",
        content="hello",
    )

    await memory.clear(
        "session-1"
    )

    assert (
        await memory.get_all(
            "session-1"
        )
        == []
    )


def test_invalid_limits_are_rejected():

    with pytest.raises(
        ValueError,
        match="recent_message_limit",
    ):
        ConversationMemory(
            recent_message_limit=0,
        )

    with pytest.raises(
        ValueError,
        match="max_stored_messages",
    ):
        ConversationMemory(
            max_stored_messages=0,
        )

    with pytest.raises(
        ValueError,
        match="max_stored_messages",
    ):
        ConversationMemory(
            recent_message_limit=12,
            max_stored_messages=5,
        )