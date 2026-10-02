from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from agent.medmind.resolvers.time import (
    resolve_time_candidates,
)

# ============================================================
# SCORE RESULT
# ============================================================

@dataclass(frozen=True, slots=True)
class CaseScore:
    status_correct: bool
    capability_correct: bool
    arguments_correct: bool
    confirmation_correct: bool
    correction_target_correct: bool
    ambiguity_correct: bool

    missing_arguments: tuple[str, ...] = ()
    wrong_arguments: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return (
            self.status_correct
            and self.capability_correct
            and self.arguments_correct
            and self.confirmation_correct
            and self.correction_target_correct
            and self.ambiguity_correct
        )

# ============================================================
# SAFE TEXT NORMALIZATION
#
# Evaluation-only normalization.
# Do NOT reuse this to mutate stored patient/domain data.
# ============================================================

def _normalize_text(value: Any) -> Any:

    if not isinstance(value, str):
        return value

    normalized = (
        value
        .strip()
        .lower()
        .replace("ـ", "")
    )

    # Normalize whitespace only.
    normalized = " ".join(
        normalized.split()
    )

    return normalized

def _argument_values_match(
    *,
    argument_name: str,
    expected: Any,
    actual: Any,
) -> bool:

    # ========================================================
    # EXACT / TEXTUAL MATCH
    # ========================================================

    if (
        isinstance(expected, str)
        and isinstance(actual, str)
    ):

        expected_text = (
            _normalize_text(
                expected
            )
        )

        actual_text = (
            _normalize_text(
                actual
            )
        )

        if (
            expected_text
            == actual_text
        ):
            return True

        if (
            argument_name
            == "query"
        ):

            punctuation = (
                "?!؟.,،؛;:"
            )

            expected_query = (
                expected_text
                .rstrip(
                    punctuation
                )
                .strip()
            )

            actual_query = (
                actual_text
                .rstrip(
                    punctuation
                )
                .strip()
            )

            if (
                expected_query
                == actual_query
            ):
                return True

        if (
            argument_name
            == "time_text"
        ):

            expected_candidates = (
                resolve_time_candidates(
                    expected
                )
            )

            actual_candidates = (
                resolve_time_candidates(
                    actual
                )
            )

            if (
                expected_candidates
                and actual_candidates
            ):

                return (
                    set(
                        expected_candidates
                    )
                    ==
                    set(
                        actual_candidates
                    )
                )

        # ====================================================
        # LIMITED ARABIC DEFINITE ARTICLE TOLERANCE
        # ====================================================

        if expected_text.startswith(
            "ال"
        ):

            if (
                expected_text[2:]
                == actual_text
            ):
                return True

        if actual_text.startswith(
            "ال"
        ):

            if (
                actual_text[2:]
                == expected_text
            ):
                return True

        return False

    return expected == actual

# ============================================================
# CASE SCORING
# ============================================================

def score_understanding_result(
    *,
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> CaseScore:

    expected_status = expected.get("status")
    actual_status = actual.get("status")

    status_correct = (
        expected_status == actual_status
    )

    expected_capability = expected.get(
        "capability"
    )

    actual_capability = actual.get(
        "capability"
    )

    capability_correct = (
        expected_capability
        == actual_capability
    )

    expected_confirmation = expected.get(
        "confirmation",
        "unknown",
    )

    actual_confirmation = actual.get(
        "confirmation",
        "unknown",
    )

    confirmation_correct = (
        expected_confirmation
        == actual_confirmation
    )

    expected_correction_target = (
        expected.get(
            "correction_target"
        )
    )

    actual_correction_target = (
        actual.get(
            "correction_target"
        )
    )

    correction_target_correct = (
        expected_correction_target
        == actual_correction_target
    )

    expected_ambiguity = expected.get(
        "ambiguity_kind"
    )

    actual_ambiguity = actual.get(
        "ambiguity_kind"
    )

    ambiguity_correct = (
        expected_ambiguity
        == actual_ambiguity
    )

    expected_arguments = (
        expected.get("arguments")
        or {}
    )

    actual_arguments = (
        actual.get("arguments")
        or {}
    )

    missing_arguments: list[str] = []
    wrong_arguments: list[str] = []

    # ========================================================
    # EXPECTED ARGUMENTS MUST EXIST AND MATCH
    # ========================================================

    for key, expected_value in (
        expected_arguments.items()
    ):

        if key not in actual_arguments:

            missing_arguments.append(
                key
            )

            continue

        actual_value = actual_arguments[
            key
        ]

        if not _argument_values_match(
            argument_name=key,
            expected=expected_value,
            actual=actual_value,
        ):

            wrong_arguments.append(
                key
            )

    # ========================================================
    # NO UNEXPECTED SEMANTIC ARGUMENTS
    #
    # Prevent hallucinated entities from receiving a pass.
    # ========================================================

    unexpected_arguments = (
        set(actual_arguments)
        - set(expected_arguments)
    )

    for key in sorted(
        unexpected_arguments
    ):

        value = actual_arguments.get(
            key
        )

        if value not in (
            None,
            "",
            [],
            {},
        ):

            wrong_arguments.append(
                key
            )

    arguments_correct = (
        not missing_arguments
        and not wrong_arguments
    )

    return CaseScore(
        status_correct=status_correct,
        capability_correct=capability_correct,
        arguments_correct=arguments_correct,
        confirmation_correct=confirmation_correct,
        correction_target_correct=(
            correction_target_correct
        ),
        ambiguity_correct=ambiguity_correct,
        missing_arguments=tuple(
            missing_arguments
        ),
        wrong_arguments=tuple(
            wrong_arguments
        ),
    )