from __future__ import annotations

import asyncio

from medmind.memory.models import (
    ChatMessage,
)


class ConversationMemory:
    """
    Stores conversation messages
    during development.

    Later we replace this store
    with SQL Server persistence.
    """

    def __init__(
        self,
        *,
        recent_message_limit: int = 12,
    ) -> None:

        self._messages: dict[
            str,
            list[ChatMessage],
        ] = {}

        self._limit = (
            recent_message_limit
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
            session_id=
                session_id,

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
            session_id=
                session_id,

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