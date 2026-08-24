from __future__ import annotations

import asyncio

from medmind.service import (
    MedMindService,
)


class MedMindServiceRegistry:
    """
    Keep one MedMindService instance per tenant.

    Each tenant therefore gets isolated:
    - ConversationMemory
    - SessionState store
    - MCP tenant header
    """

    def __init__(
        self,
    ) -> None:

        self._services: dict[
            str,
            MedMindService,
        ] = {}

        self._lock = (
            asyncio.Lock()
        )

    async def get(
        self,
        *,
        tenant_id: str,
    ) -> MedMindService:

        existing = (
            self._services.get(
                tenant_id
            )
        )

        if existing is not None:
            return existing

        async with self._lock:

            # Double-check after acquiring lock.
            existing = (
                self._services.get(
                    tenant_id
                )
            )

            if existing is not None:
                return existing

            service = await (
                MedMindService.create(
                    tenant_id=
                        tenant_id,
                )
            )

            self._services[
                tenant_id
            ] = service

            return service