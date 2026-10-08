from __future__ import annotations

from typing import Literal


# ============================================================
# READ ROUTES
# ============================================================

ReadRoute = Literal[
    "available_slots",
    "working_hours",
    "specialty",
    "doctor",
    "service",
    "knowledge",
]


# ============================================================
# CAPABILITY -> READ ROUTE
#
# New V2 path.
# Understanding capability is the preferred routing signal.
# ============================================================

CAPABILITY_READ_ROUTES: dict[
    str,
    ReadRoute,
] = {
    "provider.get_slots":
        "available_slots",

    "provider.get_working_hours":
        "working_hours",

    "catalog.specialty.search":
        "specialty",

    "provider.search_doctors":
        "doctor",

    "provider.get_services":
        "service",

    "provider.get_policy":
        "knowledge",

    "knowledge.search":
        "knowledge",

    # ========================================================
    # FUTURE DOMAIN EXTENSIONS
    #
    # Add only when the corresponding capability and domain
    # service are production-ready.
    # ========================================================
    #
    # "lab.result.lookup":
    #     "lab_result",
    #
    # "lab.test_preparation":
    #     "lab_preparation",
    #
    # "diagnostics.explain":
    #     "diagnostics",
}


# ============================================================
# LEGACY INTENT -> READ ROUTE
#
# Temporary compatibility path.
# This keeps existing callers/tests working while V2 moves
# toward capability-based routing.
# ============================================================

LEGACY_INTENT_READ_ROUTES: dict[
    str,
    ReadRoute,
] = {
    "ask_available_slots":
        "available_slots",

    "ask_working_hours":
        "working_hours",

    "ask_doctor":
        "doctor",

    "ask_service":
        "service",

    "ask_provider":
        "knowledge",
}


# ============================================================
# ROUTE RESOLUTION
# ============================================================

def resolve_read_route(
    *,
    selected_capability: str | None,
    intent: str | None,
) -> ReadRoute | None:
    """
    Resolve the current informational read route.

    Priority:

    1. V2 Understanding capability.
    2. Legacy NLU intent fallback.

    An unknown/unmapped capability does not break the old
    system during migration; legacy intent routing is still
    allowed temporarily.
    """

    if selected_capability:

        capability_route = (
            CAPABILITY_READ_ROUTES.get(
                selected_capability
            )
        )

        if capability_route is not None:
            return capability_route

    if intent:

        return (
            LEGACY_INTENT_READ_ROUTES.get(
                intent
            )
        )

    return None