from __future__ import annotations

from medmind.tenancy.capabilities import (
    Capability,
)
from medmind.tenancy.context import (
    TenantContext,
)


# ============================================================
# UNDERSTANDING CAPABILITY -> TENANT CAPABILITY
# ============================================================

UNDERSTANDING_CAPABILITY_REQUIREMENTS: dict[
    str,
    Capability,
] = {
    "appointment.create":
        Capability.APPOINTMENT_BOOK,

    "appointment.search":
        Capability.APPOINTMENT_GET,

    "appointment.cancel":
        Capability.APPOINTMENT_CANCEL,

    "appointment.reschedule":
        Capability.APPOINTMENT_RESCHEDULE,
        
    "catalog.specialty.search":
        Capability.SPECIALTY_SEARCH,

    "provider.search_doctors":
        Capability.DOCTOR_SEARCH,

    "provider.get_services":
        Capability.SERVICE_SEARCH,

    "provider.get_slots":
        Capability.APPOINTMENT_AVAILABLE_SLOTS,

    "provider.get_policy":
        Capability.PROVIDER_POLICY,

    "provider.get_working_hours":
        Capability.WORKING_HOURS,

    "knowledge.search":
        Capability.KNOWLEDGE_SEARCH,

    "human_support.transfer":
        Capability.HUMAN_SUPPORT,
}


# ============================================================
# TENANT FILTER
# ============================================================

def allowed_understanding_capabilities(
    tenant_context: TenantContext | None,
) -> frozenset[str] | None:
    """
    Return the Understanding capabilities allowed
    for the active tenant.

    None means legacy mode:
    no tenant filtering is applied.

    Production requests with TenantContext are filtered
    according to the tenant capability policy.
    """

    if tenant_context is None:
        return None

    return frozenset(
        capability_name
        for (
            capability_name,
            required_capability,
        )
        in (
            UNDERSTANDING_CAPABILITY_REQUIREMENTS
            .items()
        )
        if tenant_context.allows(
            required_capability
        )
    )