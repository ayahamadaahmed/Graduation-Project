from __future__ import annotations

import asyncio

from medmind.state.models import (
    ConversationChannel,
    SessionState,
)


class InMemoryStateStore:
    """
    Development state store.

    Later this interface can be backed
    by Redis or SQL Server without
    changing the Agent service.
    """

    def __init__(
        self,
    ) -> None:

        self._states: dict[
            str,
            SessionState,
        ] = {}

        self._lock = (
            asyncio.Lock()
        )

    async def get_or_create(
    self,
    *,
    session_id: str,
    tenant_id: str,
    channel: ConversationChannel,
) -> SessionState:

        async with self._lock:

            existing = (
                self._states.get(
                    session_id
                )
            )

            if existing is not None:

                # Every new request is authoritative
                # about the current communication channel.
                existing.channel = channel

                return existing

            state = SessionState(
                session_id=
                    session_id,

                tenant_id=
                    tenant_id,

                channel=
                    channel,
            )

            self._states[
                session_id
            ] = state

            return state

    async def save(
        self,
        state: SessionState,
    ) -> None:

        async with self._lock:

            self._states[
                state.session_id
            ] = state

    async def get(
        self,
        session_id: str,
    ) -> SessionState | None:

        async with self._lock:

            return self._states.get(
                session_id
            )

    async def clear(
        self,
        session_id: str,
    ) -> None:

        async with self._lock:

            self._states.pop(
                session_id,
                None,
            )