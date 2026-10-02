from __future__ import annotations

from .tool_planner import ToolPlan
from typing import Any
from medmind.resolvers.date import (
    resolve_date,
)

from medmind.resolvers.time import (
    resolve_time_candidates,
)
_CORRECTION_ARGUMENTS: dict[
    str,
    set[str],
] = {
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

def normalize_tool_plan(
    result: ToolPlan,
    context: dict[str, Any] | None = None,
    message: str | None = None,
) -> ToolPlan:

    """
    Apply only deterministic, semantics-preserving fixes.

    Supported normalizations:

    1. If replacement data is provided while confirmation is
       pending, the turn is a correction rather than a plain
       yes/no confirmation. Therefore confirmation becomes
       "unknown".

    2. If correction_target identifies a field as needing
       correction, but the planner already extracted a
       replacement value for that same field, the correction
       request has already been satisfied and
       correction_target becomes None.

    This function must never guess intent or invent arguments.
    """

    context = context or {}

    arguments = (
        result.arguments
        or {}
    )

    collected_arguments = (
        context.get(
            "collected_arguments"
        )
        or {}
    )

    if (
        result.status == "selected"
        and message
        and arguments
        and collected_arguments
    ):

        normalized_message = (
            " ".join(
                str(message)
                .strip()
                .casefold()
                .split()
            )
        )

        repaired_arguments = dict(
            arguments
        )

        for (
            argument_name,
            argument_value,
        ) in arguments.items():

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

            normalized_argument = (
                " ".join(
                    str(argument_value)
                    .strip()
                    .casefold()
                    .split()
                )
            )

            normalized_previous = (
                " ".join(
                    str(previous_value)
                    .strip()
                    .casefold()
                    .split()
                )
            )

            if (
                normalized_argument
                != normalized_previous
            ):
                continue

            # If the value is explicitly present in the
            # current message, it belongs to this turn and
            # must be preserved.
            if (
                normalized_argument
                and normalized_argument
                in normalized_message
            ):
                continue

            repaired_arguments.pop(
                argument_name,
                None,
            )

        if (
            repaired_arguments
            != arguments
        ):

            result = result.model_copy(
                update={
                    "arguments":
                        repaired_arguments,
                }
            )

            arguments = (
                repaired_arguments
            )

    active_capability = context.get(
        "active_capability"
    )

    time_value = arguments.get(
        "time_text"
    )

    date_value = arguments.get(
        "date_text"
    )

    if (
        result.status == "selected"
        and context.get(
            "pending_confirmation"
        ) is True
        and active_capability
        in {
            "appointment.create",
            "appointment.reschedule",
        }
        and time_value
        and not date_value
    ):

        recognized_date = (
            resolve_date(
                str(time_value)
            )
        )

        recognized_times = (
            resolve_time_candidates(
                str(time_value)
            )
        )

        if (
            recognized_date is not None
            and not recognized_times
        ):

            repaired_arguments = dict(
                arguments
            )

            repaired_arguments.pop(
                "time_text",
                None,
            )

            repaired_arguments[
                "date_text"
            ] = str(
                time_value
            )

            result = result.model_copy(
                update={
                    "arguments": (
                        repaired_arguments
                    ),
                }
            )

            arguments = (
                repaired_arguments
            )

    # ========================================================
    # 1. REPLACEMENT DURING CONFIRMATION
    # ========================================================

    if (
        result.status == "selected"
        and context.get(
            "pending_confirmation"
        ) is True
        and bool(arguments)
        and result.confirmation != "unknown"
    ):
        result = result.model_copy(
            update={
                "confirmation": "unknown",
            }
        )

    # ========================================================
    # 2. CORRECTION TARGET ALREADY SATISFIED
    # ========================================================

    correction_target = (
        result.correction_target
    )

    if not correction_target:
        return result

    target_arguments = (
        _CORRECTION_ARGUMENTS.get(
            correction_target,
            set(),
        )
    )

    if not target_arguments:
        return result

    replacement_present = any(
        argument_name in arguments
        and arguments[
            argument_name
        ]
        not in {
            None,
            "",
        }
        for argument_name
        in target_arguments
    )

    if not replacement_present:
        return result

    return result.model_copy(
        update={
            "correction_target": None,
        }
    )