from __future__ import annotations

from typing import Any

from medmind.understanding.capabilities import (
    get_capability,
)

from medmind.understanding.capability_router import (
    CapabilityMatch,
    SemanticCapabilityRouter,
)


def select_capability_candidates(
    *,
    router: SemanticCapabilityRouter,
    message: str,
    context: dict[str, Any] | None = None,
    top_k: int = 8,
    allowed_capabilities: (
        set[str]
        | frozenset[str]
        | None
    ) = None,
) -> list[CapabilityMatch]:

    context = context or {}

    # ========================================================
    # 1. NORMAL SEMANTIC RETRIEVAL
    # ========================================================

    matches = router.route(
        message,
        top_k=top_k,
        allowed_capabilities=(
            allowed_capabilities
        ),
    )

    # ========================================================
    # 2. ACTIVE CAPABILITY FROM CONVERSATION STATE
    # ========================================================

    active_capability = context.get(
        "active_capability"
    )

    if not active_capability:
        return matches

    if (
        allowed_capabilities is not None
        and active_capability
        not in allowed_capabilities
    ):
        return matches

    # --------------------------------------------------------
    # Validate that the capability really exists.
    # --------------------------------------------------------
    capability = get_capability(
        active_capability
    )

    if capability is None:
        return matches

    # --------------------------------------------------------
    # Avoid duplicating the active capability when the
    # semantic router already retrieved it.
    # --------------------------------------------------------

    existing_names = {
        match.name
        for match in matches
    }

    if active_capability in existing_names:
        return matches

    # --------------------------------------------------------
    # Short contextual messages may have almost no semantic
    # meaning when viewed alone.
    #
    # Therefore keep the active workflow available even when
    # the semantic router did not retrieve it.
    # --------------------------------------------------------

    matches.append(
        CapabilityMatch(
            name=capability.name,
            domain=capability.domain,
            score=0.0,
            matched_text=(
                "active_capability_from_context"
            ),
        )
    )

    return matches