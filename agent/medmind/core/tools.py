from __future__ import annotations

from collections.abc import Iterable

from medmind.tenancy.capabilities import (
    Capability,
)
from medmind.tenancy.context import (
    TenantContext,
)


# ============================================================
# READ TOOL POLICY
# ============================================================

READ_TOOL_CAPABILITIES: dict[
    str,
    Capability,
] = {
    "get_provider_info":
        Capability.PROVIDER_INFO,

    "list_specialties":
        Capability.SPECIALTY_SEARCH,

    "list_doctors":
        Capability.DOCTOR_SEARCH,

    "list_services":
        Capability.SERVICE_SEARCH,

    "list_available_slots":
        Capability.APPOINTMENT_AVAILABLE_SLOTS,
}


READ_TOOL_NAMES = frozenset(
    READ_TOOL_CAPABILITIES
)


# ============================================================
# TOOL SELECTION
# ============================================================

def select_read_tools(
    tools: Iterable,
    *,
    tenant_context: TenantContext | None = None,
):
    """
    Select read-only MCP tools exposed to the LLM.

    Legacy callers without TenantContext retain the
    previous behavior.

    Production callers with TenantContext only expose
    tools allowed by that tenant's capability policy.
    """

    available_tools = {
        tool.name: tool
        for tool in tools
    }

    # --------------------------------------------------------
    # Determine required/allowed tool names
    # --------------------------------------------------------

    if tenant_context is None:

        # Backward-compatible legacy behavior.
        allowed_names = set(
            READ_TOOL_NAMES
        )

    else:

        allowed_names = {
            tool_name
            for (
                tool_name,
                capability,
            ) in READ_TOOL_CAPABILITIES.items()
            if tenant_context.allows(
                capability
            )
        }

    # --------------------------------------------------------
    # Validate tools that SHOULD exist
    # --------------------------------------------------------

    missing = (
        allowed_names
        - available_tools.keys()
    )

    if missing:

        raise RuntimeError(
            "Missing MCP tools: "
            + ", ".join(
                sorted(
                    missing
                )
            )
        )

    # --------------------------------------------------------
    # Return only tenant-allowed read tools
    # --------------------------------------------------------

    return [
        available_tools[
            name
        ]
        for name in READ_TOOL_CAPABILITIES
        if name in allowed_names
    ]