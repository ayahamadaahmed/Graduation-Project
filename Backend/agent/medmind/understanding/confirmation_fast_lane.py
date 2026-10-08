from __future__ import annotations

import re
import unicodedata

from typing import Any

from .tool_planner import ToolPlan


def _strip_diacritics(
    text: str,
) -> str:

    return "".join(
        character
        for character in unicodedata.normalize(
            "NFKD",
            text,
        )
        if not unicodedata.combining(
            character
        )
    )


def _normalize(
    text: str,
) -> str:

    text = _strip_diacritics(
        text
    )

    text = (
        text
        .replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ى", "ي")
        .lower()
        .strip()
    )

    text = re.sub(
        r"[^\w\u0600-\u06ff]+",
        " ",
        text,
    )

    return " ".join(
        text.split()
    )


# Exact confirmations only.
# Do NOT add sentences or fuzzy phrases here.
YES_VALUES = {
    "ايوه",
    "ايوة",
    "نعم",
    "yes",
}

NO_VALUES = {
    "لا",
    "لاء",
    "no",
}


def try_confirmation_fast_lane(
    *,
    message: str,
    context: dict[str, Any] | None = None,
) -> ToolPlan | None:

    context = context or {}

    stage = str(
        context.get("stage")
        or ""
    )

    active_capability = (
        context.get("active_capability")
    )

    confirmation_stages = {
        "awaiting_confirmation",
        "awaiting_phone_confirmation",
    }

    if stage not in confirmation_stages:
        return None

    if not active_capability:
        return None

    normalized = _normalize(
        message
    )

    if normalized in YES_VALUES:

        return ToolPlan(
            status="selected",
            capability=str(
                active_capability
            ),
            arguments={},
            confirmation="yes",
            ambiguity_kind=None,
            correction_target=None,
            reason="confirmation_fast_lane",
        )

    if normalized in NO_VALUES:

        return ToolPlan(
            status="selected",
            capability=str(
                active_capability
            ),
            arguments={},
            confirmation="no",
            ambiguity_kind=None,
            correction_target=None,
            reason="confirmation_fast_lane",
        )

    return None