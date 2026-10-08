from __future__ import annotations

import re
from collections.abc import Collection

from medmind.understanding.tool_planner import (
    ToolPlan,
)


_RADIOLOGY_CAPABILITY = (
    "diagnostics.radiology.analyze"
)


_ACTION_PATTERNS = (
    r"\banaly[sz]e\b",
    r"\binterpret\b",
    r"\breview\b",
    r"\bread\b",
    r"\bprocess\b",
    r"حلل",
    r"حلّل",
    r"حللي",
    r"فسر",
    r"فسّر",
    r"اقرأ",
    r"اقرا",
)


_NEGATIVE_PATTERNS = (
    r"\bdo\s+not\b",
    r"\bdon['’]?t\b",
    r"متعملش",
    r"ما\s*تحللش",
    r"مش\s+عايز",
)


_MODALITY_PATTERNS = {
    "brain_mri": (
        r"\bbrain[\s_-]*mri\b",
        r"\bmri[\s_-]*(?:of[\s_-]*)?"
        r"(?:the[\s_-]*)?brain\b",
        r"رنين(?:\s+مغناطيسي)?\s+"
        r"(?:على|ل)?\s*(?:المخ|الدماغ)",
    ),
    "chest_xray": (
        r"\bchest[\s_-]*x[\s-]?ray\b",
        r"\bx[\s-]?ray[\s_-]*chest\b",
        r"أشعة\s+(?:سينية\s+)?(?:على\s+)?الصدر",
        r"اشعة\s+(?:سينية\s+)?(?:على\s+)?الصدر",
    ),
    "kidney_ct": (
        r"\bkidney[\s_-]*ct\b",
        r"\brenal[\s_-]*ct\b",
        r"\bct[\s_-]*(?:scan[\s_-]*)?"
        r"(?:of[\s_-]*)?(?:the[\s_-]*)?"
        r"kidneys?\b",
        r"مقطعية\s+(?:على|ل)?\s*(?:الكلى|الكلي)",
    ),
}


def _matches_any(
    text: str,
    patterns: tuple[str, ...],
) -> bool:

    return any(
        re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )
        is not None
        for pattern in patterns
    )


def try_diagnostic_fast_lane(
    *,
    message: str,
    allowed_capabilities: (
        Collection[str]
        | None
    ) = None,
) -> ToolPlan | None:

    clean_message = message.strip()

    if not clean_message:
        return None

    if (
        allowed_capabilities is not None
        and _RADIOLOGY_CAPABILITY
        not in allowed_capabilities
    ):
        return None

    if _matches_any(
        clean_message,
        _NEGATIVE_PATTERNS,
    ):
        return None

    if not _matches_any(
        clean_message,
        _ACTION_PATTERNS,
    ):
        return None

    matched_modalities = [
        modality
        for modality, patterns
        in _MODALITY_PATTERNS.items()
        if _matches_any(
            clean_message,
            patterns,
        )
    ]

    # Never guess.
    #
    # Zero matches:
    # "Analyze this scan"
    #
    # Multiple matches:
    # "Analyze this brain MRI and kidney CT"
    #
    # Both must continue through normal understanding.
    if len(matched_modalities) != 1:
        return None

    modality = matched_modalities[0]

    return ToolPlan(
        status="selected",
        capability=_RADIOLOGY_CAPABILITY,
        arguments={
            "modality": modality,
        },
        confirmation="unknown",
        ambiguity_kind=None,
        correction_target=None,
        reason="diagnostic_radiology_fast_lane",
    )