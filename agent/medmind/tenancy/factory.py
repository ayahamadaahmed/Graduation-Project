from __future__ import annotations

from typing import Protocol
from uuid import UUID

from .capabilities import (
    build_tenant_capabilities,
)
from .context import (
    TenantContext,
)


class ProviderLike(Protocol):
    id: UUID
    tenant_key: str
    name: str
    org_type: str
    timezone: str

def build_tenant_context(
    provider: ProviderLike,
) -> TenantContext:
    """
    Build MedMind runtime tenant context
    from the provider record loaded from the database.

    The database remains the source of truth.
    """

    capabilities = (
        build_tenant_capabilities(
            tenant_id=provider.tenant_key,
            provider_type=provider.org_type,
        )
    )

    return TenantContext(
        tenant_id=provider.tenant_key,
        provider_id=provider.id,
        provider_name=provider.name,
        capabilities=capabilities,
        timezone=provider.timezone,
    )