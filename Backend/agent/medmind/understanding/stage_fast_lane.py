from __future__ import annotations

import re

from typing import Any

from .tool_planner import ToolPlan


# ============================================================
# DIGIT NORMALIZATION
# ============================================================

_ARABIC_DIGIT_TRANSLATION = str.maketrans(
    {
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
    }
)


def _normalize_numeric_input(
    message: str,
) -> str | None:

    cleaned = message.strip()

    if not cleaned:
        return None

    # Very conservative.
    #
    # Allow ONLY:
    # - digits
    # - spaces
    # - hyphens
    #
    # Natural-language sentences must go to normal AI.
    if not re.fullmatch(
        r"[0-9٠-٩\s-]+",
        cleaned,
    ):
        return None

    normalized = (
        cleaned
        .translate(
            _ARABIC_DIGIT_TRANSLATION
        )
        .replace(" ", "")
        .replace("-", "")
    )

    if not normalized.isdigit():
        return None

    return normalized


# ============================================================
# PHONE
# ============================================================

def _try_phone(
    message: str,
) -> str | None:

    normalized = (
        _normalize_numeric_input(
            message
        )
    )

    if normalized is None:
        return None

    # Egyptian mobile:
    #
    # 010xxxxxxxx
    # 011xxxxxxxx
    # 012xxxxxxxx
    # 015xxxxxxxx
    if not re.fullmatch(
        r"01[0125]\d{8}",
        normalized,
    ):
        return None

    return normalized


# ============================================================
# NATIONAL ID
# ============================================================

def _try_national_id(
    message: str,
) -> str | None:

    normalized = (
        _normalize_numeric_input(
            message
        )
    )

    if normalized is None:
        return None

    if not re.fullmatch(
        r"\d{14}",
        normalized,
    ):
        return None

    return normalized


# ============================================================
# FAST LANE
# ============================================================

def try_stage_fast_lane(
    *,
    message: str,
    context: dict[str, Any] | None = None,
) -> ToolPlan | None:

    context = context or {}

    stage = str(
        context.get("stage")
        or ""
    )

    active_capability = str(
        context.get("active_capability")
        or ""
    )

    if not active_capability:
        return None

    # ========================================================
    # PHONE
    # ========================================================

    if (
        stage == "awaiting_phone"
        and active_capability
        == "appointment.create"
    ):

        phone = _try_phone(
            message
        )

        if phone is None:
            return None

        return ToolPlan(
            status="selected",
            capability=active_capability,
            arguments={
                "phone": phone,
            },
            confirmation="unknown",
            ambiguity_kind=None,
            correction_target=None,
            reason="stage_fast_lane_phone",
        )

    # ========================================================
    # NATIONAL ID
    # ========================================================

    if (
        stage == "awaiting_national_id"
        and active_capability.startswith(
            "appointment."
        )
    ):

        national_id = (
            _try_national_id(
                message
            )
        )

        if national_id is None:
            return None

        return ToolPlan(
            status="selected",
            capability=active_capability,
            arguments={
                "national_id":
                    national_id,
            },
            confirmation="unknown",
            ambiguity_kind=None,
            correction_target=None,
            reason=(
                "stage_fast_lane_national_id"
            ),
        )

    return None