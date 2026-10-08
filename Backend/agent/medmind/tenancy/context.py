from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .capabilities import (
    Capability,
    TenantCapabilitySet,
)


@dataclass(
    frozen=True,
    slots=True,
)
class TenantContext:
    """
    Runtime identity and capability context for one MedMind tenant.

    Business data does not belong here.

    This object only describes:
    - which tenant is active
    - which provider record owns the request
    - what provider type it represents
    - what capabilities are allowed
    - the provider-local timezone
    """

    tenant_id: str
    provider_id: UUID
    provider_name: str
    capabilities: TenantCapabilitySet
    timezone: str = "Africa/Cairo"

    @property
    def provider_type(self) -> str:
        return (
            self.capabilities
            .provider_type
            .value
        )

    def allows(
        self,
        capability: Capability | str,
    ) -> bool:
        return self.capabilities.allows(
            capability
        )