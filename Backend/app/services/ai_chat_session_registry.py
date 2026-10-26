"""Server-issued AI chat sessions.

Callers can no longer invent a ``session_id``: the backend issues an
unpredictable id and binds it to the provider (tenant), the trusted service
that created it and the channel. A chat request is accepted only for a live
session owned by the same provider + service + channel; anything else looks
exactly like an unknown session.

In-memory, like the agent's conversation state store: sessions do not survive
a restart and are not shared between worker processes.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

SESSION_ID_PREFIX = "mms_"


@dataclass(slots=True)
class AIChatSession:
    session_id: str
    provider_id: UUID
    service_name: str
    channel: str
    created_at: float
    last_seen_at: float


class AIChatSessionRegistry:
    def __init__(
        self,
        *,
        idle_timeout_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if idle_timeout_seconds <= 0:
            raise ValueError("idle_timeout_seconds must be greater than zero")
        self._idle_timeout_seconds = idle_timeout_seconds
        self._clock = clock
        self._sessions: dict[str, AIChatSession] = {}
        self._lock = threading.Lock()

    @property
    def idle_timeout_seconds(self) -> float:
        return self._idle_timeout_seconds

    def create(self, *, provider_id: UUID, service_name: str, channel: str) -> AIChatSession:
        now = self._clock()
        with self._lock:
            self._purge_expired(now)
            while True:
                session_id = SESSION_ID_PREFIX + secrets.token_urlsafe(32)
                if session_id not in self._sessions:
                    break
            session = AIChatSession(
                session_id=session_id,
                provider_id=provider_id,
                service_name=service_name,
                channel=channel,
                created_at=now,
                last_seen_at=now,
            )
            self._sessions[session_id] = session
            return session

    def resolve(
        self,
        *,
        session_id: str,
        provider_id: UUID,
        service_name: str,
        channel: str | None,
    ) -> AIChatSession | None:
        """The live session if this caller owns it, else None (never says why).

        ``channel=None`` skips only the channel check (attachment uploads carry
        no channel); provider and service ownership are always enforced.
        """
        now = self._clock()
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if self._expired(session, now):
                del self._sessions[session_id]
                return None
            if (
                session.provider_id != provider_id
                or session.service_name != service_name
                or (channel is not None and session.channel != channel)
            ):
                return None
            session.last_seen_at = now
            return session

    def close(self, *, session_id: str, provider_id: UUID, service_name: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if (
                session is None
                or session.provider_id != provider_id
                or session.service_name != service_name
            ):
                return False
            del self._sessions[session_id]
            return True

    def _expired(self, session: AIChatSession, now: float) -> bool:
        return now - session.last_seen_at > self._idle_timeout_seconds

    def _purge_expired(self, now: float) -> None:
        for session_id in [s.session_id for s in self._sessions.values() if self._expired(s, now)]:
            del self._sessions[session_id]


def get_session_registry(app_state, *, idle_timeout_seconds: float) -> AIChatSessionRegistry:
    """The process-wide registry stored on ``app.state`` (shared by all routers)."""
    registry = getattr(app_state, "ai_chat_session_registry", None)
    if registry is None:
        registry = AIChatSessionRegistry(idle_timeout_seconds=idle_timeout_seconds)
        app_state.ai_chat_session_registry = registry
    return registry
