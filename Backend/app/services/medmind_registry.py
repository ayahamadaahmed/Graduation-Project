from __future__ import annotations

import asyncio
import logging
import time

from medmind.service import (
    MedMindService,
)
from medmind.response_verbalizer import (
    QwenResponseVerbalizer,
)
from medmind.tenancy.context import (
    TenantContext,
)
from langchain_openai import (
    ChatOpenAI,
)

from medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)


# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger(
    "uvicorn.error"
)


# ============================================================
# SERVICE REGISTRY
# ============================================================

class MedMindServiceRegistry:
    """
    Keep one MedMindService instance per tenant.

    Tenant-specific components remain isolated:
    - ConversationMemory
    - SessionState store
    - MCP tenant header

    Heavy tenant-independent components may be shared:
    - SemanticCapabilityRouter
    """

    def __init__(
        self,
        *,
        shared_router: (
            SemanticCapabilityRouter
            | None
        ) = None,
        shared_model: (
            ChatOpenAI
            | None
        ) = None,
        shared_planner_model=None,
        shared_planner=None,
        shared_response_verbalizer: (
            QwenResponseVerbalizer
            | None
        ) = None,
        shared_diagnostic_agent_client=None,
    ) -> None:

        self._services: dict[
            str,
            MedMindService,
        ] = {}

        self._lock = asyncio.Lock()

        self._shared_router = shared_router
        self._shared_model = shared_model
        self._shared_planner_model = shared_planner_model
        self._shared_planner = shared_planner
        self._shared_response_verbalizer = (
            shared_response_verbalizer
        )
        self._shared_diagnostic_agent_client = (
            shared_diagnostic_agent_client
        )

    @staticmethod
    def _validate_cached_context(
        service: MedMindService,
        requested_context: TenantContext | None,
    ) -> None:

        # Legacy callers that do not supply a context
        # keep their current behavior.
        if requested_context is None:
            return

        cached_context = getattr(
            service,
            "tenant_context",
            None,
        )

        # A production request must never reuse a
        # legacy cached service with no tenant context.
        if cached_context is None:
            raise RuntimeError(
                "Cached MedMindService is missing "
                "tenant context."
            )

        # These fields define the security/business
        # identity of the tenant service.
        if (
            cached_context.tenant_id
            != requested_context.tenant_id
            or cached_context.provider_id
            != requested_context.provider_id
            or cached_context.provider_type
            != requested_context.provider_type
            or cached_context.capabilities.enabled
            != requested_context.capabilities.enabled
        ):
            raise RuntimeError(
                "Cached MedMindService tenant context "
                "does not match requested tenant context."
            )
    
    async def get(
        self,
        *,
        tenant_id: str,
        tenant_context: TenantContext | None = None,
    ) -> MedMindService:

        if (
            tenant_context is not None
            and tenant_context.tenant_id != tenant_id
        ):
            raise ValueError(
                "tenant_context tenant_id does not match "
                "registry tenant_id"
            )

        total_started = (
            time.perf_counter()
        )

        # ====================================================
        # FAST PATH
        # ====================================================

        existing = (
            self._services.get(
                tenant_id
            )
        )

        if existing is not None:

            self._validate_cached_context(
                existing,
                tenant_context,
            )

            total_ms = (
                time.perf_counter()
                - total_started
            ) * 1000

            logger.info(
                "medmind_registry_timing "
                "cached=True "
                "shared_router=%s "
                "lock_wait_ms=0.00 "
                "service_create_ms=0.00 "
                "total_ms=%.2f",
                (
                    self._shared_router
                    is not None
                ),
                total_ms,
            )

            return existing
        # ====================================================
        # REGISTRY LOCK
        # ====================================================

        lock_started = (
            time.perf_counter()
        )

        async with self._lock:

            lock_wait_ms = (
                time.perf_counter()
                - lock_started
            ) * 1000

            # ================================================
            # DOUBLE CHECK
            # ================================================

            existing = (
                self._services.get(
                    tenant_id
                )
            )

            if existing is not None:

                self._validate_cached_context(
                    existing,
                    tenant_context,
                )

                total_ms = (
                    time.perf_counter()
                    - total_started
                ) * 1000

                logger.info(
                    "medmind_registry_timing "
                    "cached=True "
                    "shared_router=%s "
                    "lock_wait_ms=%.2f "
                    "service_create_ms=0.00 "
                    "total_ms=%.2f",
                    (
                        self._shared_router
                        is not None
                    ),
                    lock_wait_ms,
                    total_ms,
                )

                return existing

            # ================================================
            # TENANT SERVICE CREATION
            #
            # The heavy semantic router is reused when the
            # application supplied a shared instance.
            # ================================================

            create_started = (
                time.perf_counter()
            )

            create_kwargs = {
                "tenant_id":
                    tenant_id,

                "tenant_context":
                    tenant_context,

                "capability_router":
                    self._shared_router,

                "model":
                    self._shared_model,

                "planner_model":
                    self._shared_planner_model,

                "planner":
                    self._shared_planner,

                "response_verbalizer":
                    self._shared_response_verbalizer,
            }

            if (
                self._shared_diagnostic_agent_client
                is not None
            ):
                create_kwargs[
                    "diagnostic_agent_client"
                ] = (
                    self._shared_diagnostic_agent_client
                )

            service = await (
                MedMindService.create(
                    **create_kwargs
                )
            )

            service_create_ms = (
                time.perf_counter()
                - create_started
            ) * 1000

            # ================================================
            # CACHE TENANT SERVICE
            # ================================================

            self._services[
                tenant_id
            ] = service

            total_ms = (
                time.perf_counter()
                - total_started
            ) * 1000

            logger.info(
                "medmind_registry_timing "
                "cached=False "
                "shared_router=%s "
                "lock_wait_ms=%.2f "
                "service_create_ms=%.2f "
                "total_ms=%.2f",
                (
                    self._shared_router
                    is not None
                ),
                lock_wait_ms,
                service_create_ms,
                total_ms,
            )

            return service

    async def clear_session_state(
        self,
        *,
        tenant_id: str,
        session_id: str,
    ) -> None:
        """Drop one session's conversation state (patient identity included).

        Never creates a tenant service just to clear it.
        """

        async with self._lock:
            service = self._services.get(tenant_id)

        if service is not None:
            await service.state_store.clear(session_id)

    async def close(
        self,
    ) -> None:

        async with self._lock:

            services = list(
                self._services.values()
            )

            self._services.clear()

        if not services:

            logger.info(
                "medmind_registry_closed "
                "service_count=0"
            )

            return

        results = await asyncio.gather(
            *(
                service.close()
                for service in services
            ),
            return_exceptions=True,
        )

        error_count = 0

        for result in results:

            if isinstance(
                result,
                Exception,
            ):

                error_count += 1

                logger.error(
                    "medmind_service_close_failed "
                    "error_type=%s",
                    type(
                        result
                    ).__name__,
                )

        logger.info(
            "medmind_registry_closed "
            "service_count=%s "
            "error_count=%s",
            len(
                services
            ),
            error_count,
        )    