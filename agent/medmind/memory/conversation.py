from __future__ import annotations

import asyncio

from medmind.memory.models import (
    ChatMessage,
)


class ConversationMemory:
    """
    In-memory conversation storage.

    recent_message_limit:
        Number of recent messages exposed
        to the AI conversation context.

    max_stored_messages:
        Maximum number of messages retained
        in RAM for one session.

    Full durable conversation history can
    later be persisted outside this store.
    """

    def __init__(
        self,
        *,
        recent_message_limit: int = 12,
        max_stored_messages: int = 100,
    ) -> None:

        if recent_message_limit <= 0:
            raise ValueError(
                "recent_message_limit "
                "must be greater than 0"
            )

        if max_stored_messages <= 0:
            raise ValueError(
                "max_stored_messages "
                "must be greater than 0"
            )

        if (
            max_stored_messages
            < recent_message_limit
        ):
            raise ValueError(
                "max_stored_messages must be "
                "greater than or equal to "
                "recent_message_limit"
            )

        self._messages: dict[
            str,
            list[ChatMessage],
        ] = {}

        self._limit = (
            recent_message_limit
        )

        self._max_stored_messages = (
            max_stored_messages
        )

        self._lock = (
            asyncio.Lock()
        )

    async def add_user_message(
        self,
        *,
        session_id: str,
        content: str,
    ) -> None:

        await self._append(
            session_id=session_id,
            message=ChatMessage(
                role="user",
                content=content,
            ),
        )

    async def add_assistant_message(
        self,
        *,
        session_id: str,
        content: str,
    ) -> None:

        await self._append(
            session_id=session_id,
            message=ChatMessage(
                role="assistant",
                content=content,
            ),
        )

    async def _append(
        self,
        *,
        session_id: str,
        message: ChatMessage,
    ) -> None:

        async with self._lock:

            messages = (
                self._messages.setdefault(
                    session_id,
                    [],
                )
            )

            messages.append(
                message
            )

            overflow = (
                len(messages)
                - self._max_stored_messages
            )

            if overflow > 0:
                del messages[
                    :overflow
                ]

    async def get_recent(
        self,
        session_id: str,
    ) -> list[ChatMessage]:

        async with self._lock:

            messages = (
                self._messages.get(
                    session_id,
                    [],
                )
            )

            return list(
                messages[
                    -self._limit:
                ]
            )

    async def get_all(
        self,
        session_id: str,
    ) -> list[ChatMessage]:

        async with self._lock:

            return list(
                self._messages.get(
                    session_id,
                    [],
                )
            )

    async def clear(
        self,
        session_id: str,
    ) -> None:

        async with self._lock:

            self._messages.pop(
                session_id,
                None,
            )