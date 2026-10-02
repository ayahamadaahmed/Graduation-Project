from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


PlannerProvider = Literal[
    "qwen",
    "gpt",
]

ComplexityLevel = Literal[
    "simple",
    "borderline",
    "complex",
]


# ============================================================
# RESULT
# ============================================================

@dataclass(frozen=True)
class PlannerPolicyDecision:
    provider: PlannerProvider
    reason: str

    complexity_score: int = 0
    complexity_level: ComplexityLevel = "simple"

    signals: tuple[str, ...] = ()

    # Measurement only for now.
    # Does NOT affect provider selection.
    semantic_margin: float | None = None


# ============================================================
# SIGNALS
# ============================================================

_OPERATION_SWITCH_SIGNALS = (
    "متلغهوش",
    "ما تلغهوش",
    "متلغيش",
    "ما تلغيش",
    "بدل ما",
    "مش عايز ألغي",
    "مش عايزة ألغي",
    "غيره بدل",
    "غيرها بدل",
    "don't cancel",
    "do not cancel",
    "instead",
)


_NEGATION_SIGNALS = (
    "لا ",
    "مش ",
    "ما ",
    "مت",
    "don't",
    "do not",
    "not ",
)


_CONDITION_SIGNALS = (
    "لو ",
    "لو مفيش",
    "لو مش موجود",
    "لو مش متاح",
    "بس ",
    "لكن",
    "وفي نفس الوقت",
    "بعد الساعة",
    "قبل الساعة",
    "if ",
    "but ",
    "after ",
    "before ",
    "otherwise",
)


_COMPLEX_REQUEST_SIGNALS = (
    "دكتورة تانية",
    "دكتور تاني",
    "نفس التخصص",
    "أقرب ميعاد",
    "أي دكتور",
    "أي دكتورة",
    "another doctor",
    "same specialty",
    "closest appointment",
)


_BOOK_SIGNALS = (
    "احجز",
    "أحجز",
    "حجز جديد",
    "book ",
    "new appointment",
)


_CANCEL_SIGNALS = (
    "الغي",
    "ألغي",
    "الغاء",
    "إلغاء",
    "cancel",
)


_RESCHEDULE_SIGNALS = (
    "غير الميعاد",
    "غيّر الميعاد",
    "غيره لل",
    "غيرها لل",
    "أجل",
    "أجّل",
    "reschedule",
    "move appointment",
    "change appointment",
)


# ============================================================
# HELPERS
# ============================================================

def _normalize_message(
    message: str,
) -> str:
    return " ".join(
        message
        .strip()
        .lower()
        .split()
    )


def _word_count(
    message: str,
) -> int:
    return len(
        message.split()
    )


def _contains_any(
    message: str,
    signals: tuple[str, ...],
) -> bool:
    return any(
        signal in message
        for signal in signals
    )


def _count_matches(
    message: str,
    signals: tuple[str, ...],
) -> int:
    return sum(
        1
        for signal in signals
        if signal in message
    )

def detect_operations(
    message: str,
) -> set[str]:
    operations: set[str] = set()

    if _contains_any(
        message,
        _BOOK_SIGNALS,
    ):
        operations.add(
            "appointment.create"
        )

    if _contains_any(
        message,
        _CANCEL_SIGNALS,
    ):
        operations.add(
            "appointment.cancel"
        )

    if _contains_any(
        message,
        _RESCHEDULE_SIGNALS,
    ):
        operations.add(
            "appointment.reschedule"
        )

    return operations


def _level_from_score(
    score: int,
) -> ComplexityLevel:
    if score >= 3:
        return "complex"

    if score >= 1:
        return "borderline"

    return "simple"


def _has_competing_appointment_candidates(
    candidates: list[Any] | None,
    semantic_margin: float | None,
) -> bool:
    """
    Detect semantic uncertainty between multiple
    appointment operations.

    Low semantic margin alone is NOT enough.
    We also require multiple appointment capabilities
    to compete near the top of the router results.
    """

    if (
        not candidates
        or semantic_margin is None
        or semantic_margin > 0.05
    ):
        return False

    top_candidates = sorted(
        candidates,
        key=lambda candidate: float(
            candidate.score
        ),
        reverse=True,
    )[:3]

    appointment_operations = {
        str(candidate.name)
        for candidate in top_candidates
        if str(candidate.name).startswith(
            "appointment."
        )
    }

    return (
        len(appointment_operations) >= 2
    )

# ============================================================
# MAIN POLICY
# ============================================================

def choose_planner_provider(
    *,
    message: str,
    context: dict[str, Any] | None = None,
    candidates: list[Any] | None = None,
) -> PlannerPolicyDecision:

    context = context or {}

    cleaned = _normalize_message(
        message
    )

    if not cleaned:
        return PlannerPolicyDecision(
            provider="qwen",
            reason="empty_or_whitespace",
            complexity_score=0,
            complexity_level="simple",
            signals=("empty_message",),
            semantic_margin=None,
        )

    words = _word_count(
        cleaned
    )

    active_capability = context.get(
        "active_capability"
    )

    stage = str(
        context.get(
            "stage",
            "",
        )
        or ""
    )

    score = 0
    detected_signals: list[str] = []

    operations = detect_operations(
        cleaned
    )

    semantic_margin: float | None = None

    if (
        candidates
        and len(candidates) >= 2
    ):
        top_scores = sorted(
            (
                float(candidate.score)
                for candidate in candidates
            ),
            reverse=True,
        )

        semantic_margin = (
            top_scores[0]
            - top_scores[1]
        )

    # ========================================================
    # 1. SHORT CONTEXTUAL ANSWER
    # ========================================================

    short_contextual = (
        bool(active_capability)
        and stage.startswith("awaiting_")
        and words <= 5
        and not operations
    )

    if short_contextual:
        score -= 3

        detected_signals.append(
            "short_contextual_turn"
        )

    # ========================================================
    # 2. OPERATION SWITCH
    # ========================================================

    operation_switch = _contains_any(
        cleaned,
        _OPERATION_SWITCH_SIGNALS,
    )

    if operation_switch:
        score += 4

        detected_signals.append(
            "operation_switch"
        )

    # ========================================================
    # 3. NEGATION
    # ========================================================

    has_negation = _contains_any(
        cleaned,
        _NEGATION_SIGNALS,
    )

    if has_negation:
        score += 1

        detected_signals.append(
            "negation"
        )

    # ========================================================
    # 4. CONDITIONS
    # ========================================================

    condition_count = _count_matches(
        cleaned,
        _CONDITION_SIGNALS,
    )

    if condition_count >= 2:
        score += 2

        detected_signals.append(
            "multiple_conditions"
        )

    elif condition_count == 1:
        score += 1

        detected_signals.append(
            "single_condition"
        )

    # ========================================================
    # 5. COMPLEX REQUEST SIGNAL
    # ========================================================

    if _contains_any(
        cleaned,
        _COMPLEX_REQUEST_SIGNALS,
    ):
        score += 1

        detected_signals.append(
            "complex_request_signal"
        )

    # ========================================================
    # 6. MULTIPLE OPERATIONS
    # ========================================================

    if len(operations) >= 2:
        score += 3

        detected_signals.append(
            "multiple_operations"
        )

    # ========================================================
    # 7. CONTEXT CONFLICT
    # ========================================================

    if (
        active_capability
        and operations
        and active_capability.startswith(
            "appointment."
        )
        and active_capability not in operations
    ):
        score += 1

        detected_signals.append(
            "context_conflict"
        )

    # ========================================================
    # 8. LONG MESSAGE
    # ========================================================

    if words >= 14:
        score += 1

        detected_signals.append(
            "long_message"
        )


    # ========================================================
    # 9. STRUCTURAL RISK OVERRIDES
    #
    # These are not keyword-specific intent rules.
    # They combine request structure with semantic
    # router evidence.
    # ========================================================

    # Multiple independent conditions are risky enough
    # to use the stronger planner even when the normal
    # score stops at borderline.
    if (
        condition_count >= 2
        and score < 3
    ):
        score = 3

        detected_signals.append(
            "multi_condition_risk_override"
        )


    # A conditional request becomes risky when the
    # semantic router is also uncertain between multiple
    # appointment operations.
    semantic_operation_competition = (
        condition_count >= 1
        and _has_competing_appointment_candidates(
            candidates,
            semantic_margin,
        )
    )

    if (
        semantic_operation_competition
        and score < 3
    ):
        score = 3

        detected_signals.append(
            "semantic_operation_competition"
        )
    # ========================================================
    # FINAL COMPLEXITY
    # ========================================================

    complexity_level = _level_from_score(
        score
    )

    # ========================================================
    # PROVIDER DECISION
    #
    # simple     -> Qwen
    # borderline -> Qwen
    # complex    -> GPT
    # ========================================================

    provider: PlannerProvider

    if complexity_level == "complex":
        provider = "gpt"
    else:
        provider = "qwen"

    # ========================================================
    # REASON
    # ========================================================

    if (
        provider == "gpt"
        and operation_switch
    ):
        reason = "operation_switch"

    elif (
        provider == "gpt"
        and "context_conflict"
        in detected_signals
    ):
        reason = "context_conflict"

    elif (
        provider == "gpt"
        and "multiple_conditions"
        in detected_signals
    ):
        reason = (
            "long_multi_condition_request"
        )

    elif (
        provider == "gpt"
        and "complex_request_signal"
        in detected_signals
    ):
        reason = "complex_request"

    elif (
        provider == "qwen"
        and short_contextual
    ):
        reason = "short_contextual_turn"

    else:
        reason = "default_fast_path"

    return PlannerPolicyDecision(
        provider=provider,
        reason=reason,
        complexity_score=score,
        complexity_level=complexity_level,
        signals=tuple(
            detected_signals
        ),
        semantic_margin=semantic_margin,
    )