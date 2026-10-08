from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .capabilities import (
    READ_ONLY_SIDE_QUESTION_CAPABILITIES,
)
from .tool_planner import ToolPlan
from .planner_policy import (
    detect_operations,
)
from .tool_plan_normalizer import (
    SUPPORTED_RADIOLOGY_MODALITIES,
    normalize_radiology_modality,
)

@dataclass(frozen=True)
class ToolPlanValidationResult:
    valid: bool
    reason: str = ""


def _normalize_text(
    value: Any,
) -> str:

    text = str(value).strip().casefold()

    replacements = {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ى": "ي",
    }

    for old, new in replacements.items():
        text = text.replace(
            old,
            new,
        )

    return " ".join(
        text.split()
    )


def _value_mentioned_in_message(
    *,
    message: str,
    value: Any,
) -> bool:

    if value is None:
        return False

    normalized_message = (
        _normalize_text(
            message
        )
    )

    normalized_value = (
        _normalize_text(
            value
        )
    )

    if not normalized_value:
        return False

    # Exact phrase appears in the message.
    if normalized_value in normalized_message:
        return True

    # Allow natural shortened forms.
    #
    # Example:
    # context value = "الساعة ستة"
    # user says     = "خليها ستة"
    #
    # "ستة" is enough to prove that the value
    # came from the current message.
    ignored_tokens = {
        "الساعه",
        "الساعة",
        "يوم",
        "الدكتور",
        "دكتور",
        "الدكتوره",
        "دكتوره",
    }

    value_tokens = [
        token
        for token
        in normalized_value.split()
        if token
        not in ignored_tokens
    ]

    message_tokens = set(
        normalized_message.split()
    )

    return (
        bool(value_tokens)
        and all(
            token in message_tokens
            for token in value_tokens
        )
    )


def _leading_confirmation_signal(
    message: str,
) -> str | None:

    normalized = _normalize_text(
        message
    )

    if not normalized:
        return None

    first_token = (
        normalized
        .split()[0]
        .strip(
            ".,!?؟،:;"
        )
    )

    yes_values = {
        "ايوه",
        "ايوة",
        "نعم",
        "yes",
    }

    no_values = {
        "لا",
        "لاء",
        "no",
    }

    if first_token in yes_values:
        return "yes"

    if first_token in no_values:
        return "no"

    return None

def _message_supports_radiology_modality(
    *,
    message: str,
    modality: str,
) -> bool:

    normalized = (
        str(message)
        .strip()
        .casefold()
        .replace("\u0623", "\u0627")
        .replace("\u0625", "\u0627")
        .replace("\u0622", "\u0627")
        .replace("\u0649", "\u064a")
        .replace("-", " ")
        .replace("_", " ")
    )

    normalized = " ".join(
        normalized.split()
    )

    compact = normalized.replace(
        " ",
        "",
    )

    if modality == "chest_xray":

        english = (
            "chest" in normalized
            and "xray" in compact
        )

        arabic = (
            "\u0635\u062f\u0631"
            in normalized
            and
            "\u0627\u0634\u0639"
            in normalized
        )

        return english or arabic

    if modality == "brain_mri":

        has_mri = (
            "mri" in compact
            or
            "\u0631\u0646\u064a\u0646"
            in normalized
        )

        has_brain = any(
            token in normalized
            for token in (
                "brain",
                "\u0645\u062e",
                "\u062f\u0645\u0627\u063a",
                "\u0631\u0627\u0633",
            )
        )

        return (
            has_mri
            and has_brain
        )

    if modality == "kidney_ct":

        has_ct = (
            "ct" in normalized.split()
            or
            "\u0645\u0642\u0637\u0639\u064a"
            in normalized
        )

        has_kidney = any(
            token in normalized
            for token in (
                "kidney",
                "renal",
                "\u0643\u0644\u064a",
            )
        )

        return (
            has_ct
            and has_kidney
        )

    return False

class ToolPlanValidator:

    """
    Validate semantic consistency of a planner result.

    This validator is different from schema validation.

    Schema validation checks:
    - valid JSON
    - valid ToolPlan
    - allowed capability
    - allowed arguments

    This validator checks whether the result makes sense
    with the current conversation state.
    """

    @staticmethod
    def validate(
        *,
        message: str,
        result: ToolPlan,
        context: dict[str, Any] | None = None,
    ) -> ToolPlanValidationResult:

        context = context or {}

        # ----------------------------------------------------
        # Ambiguous results are valid planner outcomes.
        # The workflow/orchestrator decides what to do next.
        # ----------------------------------------------------

        if result.status == "ambiguous":
            return ToolPlanValidationResult(
                valid=True,
            )

        # ----------------------------------------------------
        # Selected result must contain a capability.
        # Normally caught earlier, but keep this guard here.
        # ----------------------------------------------------

        if not result.capability:
            return ToolPlanValidationResult(
                valid=False,
                reason="selected_without_capability",
            )

        # ----------------------------------------------------
        # RADIOLOGY MODALITY SAFETY
        #
        # The modality must be explicit and supported.
        # Never accept a modality guessed by either Qwen or GPT.
        # ----------------------------------------------------

        if (
            result.capability
            == "diagnostics.radiology.analyze"
        ):

            raw_modality = (
                (result.arguments or {}).get(
                    "modality"
                )
            )

            if not raw_modality:

                return ToolPlanValidationResult(
                    valid=False,
                    reason=(
                        "radiology_modality_required"
                    ),
                )

            modality = (
                normalize_radiology_modality(
                    raw_modality
                )
            )

            if (
                modality is None
                or modality
                not in SUPPORTED_RADIOLOGY_MODALITIES
            ):

                return ToolPlanValidationResult(
                    valid=False,
                    reason=(
                        "unsupported_radiology_modality"
                    ),
                )

            trusted_modality = (
                context.get(
                    "diagnostic_modality"
                )
            )

            trusted_modality = (
                normalize_radiology_modality(
                    trusted_modality
                )
            )

            modality_is_explicit = (
                _message_supports_radiology_modality(
                    message=message,
                    modality=modality,
                )
            )

            modality_is_trusted = (
                trusted_modality
                == modality
            )

            if not (
                modality_is_explicit
                or modality_is_trusted
            ):

                return ToolPlanValidationResult(
                    valid=False,
                    reason=(
                        "radiology_modality_not_explicit"
                    ),
                )    

        active_capability = context.get(
            "active_capability"
        )

        stage = context.get(
            "stage"
        )

        explicit_operations = (
            detect_operations(
                " ".join(
                    message
                    .strip()
                    .lower()
                    .split()
                )
            )
        )

        allowed_explicit_operation_switch = (
            result.capability
            in explicit_operations
        )

        is_contextual_stage = (
            isinstance(stage, str)
            and stage.startswith("awaiting_")
        )

        if (
            active_capability
            and is_contextual_stage
            and result.capability != active_capability
            and result.capability
            not in READ_ONLY_SIDE_QUESTION_CAPABILITIES
            and not allowed_explicit_operation_switch
        ):
            return ToolPlanValidationResult(
                valid=False,
                reason="contextual_capability_mismatch",
            )

        # ----------------------------------------------------
        # Confirmation / correction semantic guards
        # ----------------------------------------------------

        pending_confirmation = bool(
            context.get(
                "pending_confirmation"
            )
        )

        collected_arguments = (
            context.get(
                "collected_arguments"
            )
            or {}
        )

        result_arguments = (
            result.arguments
            or {}
        )

        if pending_confirmation:

            for (
                argument_name,
                argument_value,
            ) in result_arguments.items():

                if (
                    argument_name
                    not in collected_arguments
                ):
                    continue

                previous_value = (
                    collected_arguments[
                        argument_name
                    ]
                )

                if (
                    _normalize_text(
                        argument_value
                    )
                    != _normalize_text(
                        previous_value
                    )
                ):
                    continue

                if (
                    _value_mentioned_in_message(
                        message=message,
                        value=argument_value,
                    )
                ):
                    continue

                return ToolPlanValidationResult(
                    valid=False,
                    reason=(
                        "copied_context_argument"
                    ),
                )

        if (
            pending_confirmation
            and result_arguments
            and result.confirmation
            != "unknown"
        ):
            return ToolPlanValidationResult(
                valid=False,
                reason=(
                    "replacement_with_confirmation"
                ),
            )

        correction_argument_map = {
            "patient_name": {
                "patient_name",
            },
            "phone": {
                "phone",
            },
            "doctor": {
                "doctor_name",
            },
            "schedule": {
                "date_text",
                "time_text",
            },
            "time": {
                "time_text",
            },
            "national_id": {
                "national_id",
            },
        }

        correction_target = (
            result.correction_target
        )

        if correction_target:

            target_arguments = (
                correction_argument_map.get(
                    correction_target,
                    set(),
                )
            )

            has_replacement = any(
                argument_name
                in result_arguments
                and result_arguments[
                    argument_name
                ]
                not in {
                    None,
                    "",
                }
                for argument_name
                in target_arguments
            )

            if has_replacement:

                return ToolPlanValidationResult(
                    valid=False,
                    reason=(
                        "correction_target_has_replacement"
                    ),
                )

        if (
            pending_confirmation
            and result.confirmation
            in {
                "yes",
                "no",
            }
        ):

            message_signal = (
                _leading_confirmation_signal(
                    message
                )
            )

            if (
                message_signal
                and message_signal
                != result.confirmation
            ):
                return ToolPlanValidationResult(
                    valid=False,
                    reason=(
                        "confirmation_contradicts_message"
                    ),
                )        

        return ToolPlanValidationResult(
            valid=True,
        )