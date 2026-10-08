from __future__ import annotations

import re
from typing import Any

from .tool_planner import ToolPlan


_WRITE_CAPABILITIES = frozenset(
    {
        "appointment.create",
        "appointment.cancel",
        "appointment.reschedule",
    }
)


_ARABIC_UNRESOLVED_REFERENCE_PATTERNS = (
    # change / edit "it"
    r"\b(?:أغيره|اغيره|غيّره|غيره)\b",
    r"\b(?:أعدلها|اعدلها|عدلها)\b",
    r"\b(?:أعدله|اعدله|عدله)\b",

    # generic deictic references
    r"\b(?:ده|دا|دي)\b",
)

_ENGLISH_UNRESOLVED_REFERENCE_PATTERNS = (
    r"\bchange\s+it\b",
    r"\bmodify\s+it\b",
    r"\bedit\s+it\b",
    r"\bcancel\s+it\b",
    r"\bmove\s+it\b",
)


def needs_reference_clarification(
    *,
    message: str,
    result: ToolPlan,
    context: dict[str, Any] | None,
) -> bool:
    """
    Return True only when the planner selected a write
    operation but the current message contains an unresolved
    reference and conversation context cannot resolve it.

    This is a safety guard, not an intent classifier.
    """

    if result.status != "selected":
        return False

    if result.capability not in _WRITE_CAPABILITIES:
        return False

    context = context or {}

    # Existing workflow context may resolve "it", "ده", etc.
    if context.get("active_capability"):
        return False

    cleaned = " ".join(
        message.strip().lower().split()
    )

    if not cleaned:
        return False
    
    if result.arguments:
        return False
    
    patterns = (
        _ARABIC_UNRESOLVED_REFERENCE_PATTERNS
        + _ENGLISH_UNRESOLVED_REFERENCE_PATTERNS
    )

    return any(
        re.search(
            pattern,
            cleaned,
            flags=re.IGNORECASE,
        )
        is not None
        for pattern in patterns
    )