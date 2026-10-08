from __future__ import annotations

from typing import Any

from medmind.state.models import (
    SessionState,
)
from medmind.understanding.orchestrator import (
    UnderstandingResult,
)
from medmind.understanding.types import (
    Intent,
    NLUEntities,
    NLUResult,
    OperationType,
)


# ============================================================
# LEGACY COMPATIBILITY
# ============================================================

# NLUResult.confidence is currently required by the legacy
# schema, but it is not used by routing or workflows.
#
# This value represents successful deterministic adaptation
# from a selected UnderstandingResult. It is NOT a calibrated
# model probability.
COMPATIBILITY_CONFIDENCE = 1.0


# ============================================================
# OPERATION CAPABILITIES
# ============================================================

_OPERATION_CAPABILITIES: dict[
    str,
    OperationType,
] = {
    "appointment.create":
        "book_appointment",

    "appointment.cancel":
        "cancel_appointment",

    "appointment.reschedule":
        "reschedule_appointment",
}


# ============================================================
# INFORMATION CAPABILITIES
# ============================================================

_INFORMATION_CAPABILITIES: dict[
    str,
    Intent,
] = {
    "provider.search_doctors":
        "ask_doctor",

    "provider.get_services":
        "ask_service",

    "catalog.specialty.search":
        "ask_provider",

    "provider.get_slots":
        "ask_available_slots",

    "provider.get_policy":
        "ask_provider",
        
    "provider.get_working_hours":
        "ask_working_hours",

    "knowledge.search":
        "ask_provider",

    # There is no dedicated legacy human-support intent yet.
    # "help" keeps the request outside booking/cancel/
    # reschedule workflows and allows the current service
    # read path to handle it.
    "human_support.transfer":
        "help",
}


# ============================================================
# ARGUMENT -> LEGACY INTENT
# ============================================================

_ARGUMENT_INTENTS: dict[
    str,
    Intent,
] = {
    "specialty_name":
        "provide_specialty",

    "doctor_name":
        "provide_doctor",

    "service_name":
        "provide_service",

    "date_text":
        "provide_date",

    "time_text":
        "provide_time",

    "patient_name":
        "provide_patient_name",

    "phone":
        "provide_phone",

    "national_id":
        "provide_national_id",

    "appointment_reference":
        "provide_appointment_reference",
}


# ============================================================
# CORRECTION TARGET -> LEGACY INTENT
# ============================================================

_CORRECTION_TARGET_INTENTS: dict[
    str,
    Intent,
] = {
    "patient_name":
        "provide_patient_name",

    "phone":
        "provide_phone",

    "doctor":
        "provide_doctor",

    # The existing BookingWorkflow uses provide_date to
    # represent a general schedule/date correction request.
    "schedule":
        "provide_date",

    "time":
        "provide_time",

    "national_id":
        "provide_national_id",
}


# ============================================================
# STAGE HINTS
# ============================================================

# Used only when more than one new argument was provided in
# the current turn.
#
# All entities are preserved regardless of which single
# legacy intent is selected.
_STAGE_ARGUMENT_HINTS: tuple[
    tuple[str, str],
    ...,
] = (
    (
        "specialty",
        "specialty_name",
    ),
    (
        "doctor",
        "doctor_name",
    ),
    (
        "service",
        "service_name",
    ),
    (
        "date",
        "date_text",
    ),
    (
        "time",
        "time_text",
    ),
    (
        "patient_name",
        "patient_name",
    ),
    (
        "phone",
        "phone",
    ),
    (
        "national_id",
        "national_id",
    ),
    (
        "reference",
        "appointment_reference",
    ),
)


# ============================================================
# ENTITY BUILDING
# ============================================================

def _clean_argument(
    value: Any,
) -> str | None:

    if value is None:
        return None

    cleaned = str(
        value
    ).strip()

    if not cleaned:
        return None

    return cleaned


def _build_entities(
    arguments: dict[str, str],
) -> NLUEntities:

    return NLUEntities(
        specialty_name=_clean_argument(
            arguments.get(
                "specialty_name"
            )
        ),

        doctor_name=_clean_argument(
            arguments.get(
                "doctor_name"
            )
        ),

        service_name=_clean_argument(
            arguments.get(
                "service_name"
            )
        ),

        date_text=_clean_argument(
            arguments.get(
                "date_text"
            )
        ),

        time_text=_clean_argument(
            arguments.get(
                "time_text"
            )
        ),

        patient_name=_clean_argument(
            arguments.get(
                "patient_name"
            )
        ),

        phone=_clean_argument(
            arguments.get(
                "phone"
            )
        ),

        national_id=_clean_argument(
            arguments.get(
                "national_id"
            )
        ),

        appointment_reference=_clean_argument(
            arguments.get(
                "appointment_reference"
            )
        ),
    )


# ============================================================
# ACTIVE WORKFLOW
# ============================================================

def _is_active_operation(
    *,
    state: SessionState,
    operation_type: OperationType,
) -> bool:
    """
    True only when the same operation is currently in
    progress.

    Terminal stages must not trap a new request into the
    previous operation.
    """

    if (
        state.operation_type
        != operation_type
    ):
        return False

    if state.awaiting_confirmation:
        return True

    if state.stage == "new":
        return True

    return state.stage.startswith(
        "awaiting_"
    )


# ============================================================
# CONTEXTUAL INTENT
# ============================================================

def _intent_from_arguments(
    *,
    arguments: dict[str, str],
    state: SessionState,
) -> Intent:
    """
    Pick the single legacy contextual intent.

    NLUResult supports only one intent, but all current-turn
    arguments remain available inside NLUEntities.

    When multiple arguments are present, prefer the one
    matching the current workflow stage.
    """

    present_arguments = {
        key
        for key, value
        in arguments.items()
        if (
            key in _ARGUMENT_INTENTS
            and
            _clean_argument(
                value
            )
            is not None
        )
    }

    if not present_arguments:
        return "unknown"

    stage = (
        state.stage
        or ""
    ).lower()

    # --------------------------------------------------------
    # Prefer the value expected by the current stage.
    # --------------------------------------------------------

    for (
        stage_token,
        argument_name,
    ) in _STAGE_ARGUMENT_HINTS:

        if (
            stage_token in stage
            and
            argument_name
            in present_arguments
        ):
            return _ARGUMENT_INTENTS[
                argument_name
            ]

    # --------------------------------------------------------
    # Stable fallback priority.
    #
    # This chooses only the legacy intent.
    # It does NOT discard other entities.
    # --------------------------------------------------------

    priority = (
        "appointment_reference",
        "national_id",
        "patient_name",
        "phone",
        "specialty_name",
        "doctor_name",
        "service_name",
        "date_text",
        "time_text",
    )

    for argument_name in priority:

        if (
            argument_name
            in present_arguments
        ):
            return _ARGUMENT_INTENTS[
                argument_name
            ]

    return "unknown"


# ============================================================
# APPOINTMENT SEARCH COMPATIBILITY
# ============================================================

def _adapt_appointment_search(
    *,
    entities: NLUEntities,
) -> tuple[
    Intent,
    OperationType,
]:
    """
    Legacy NLU distinguishes exact appointment lookup from
    appointment search.

    The new capability registry currently exposes one
    appointment.search capability.

    An explicit appointment reference is treated as an exact
    lookup; otherwise it is a general appointment search.
    """

    if entities.appointment_reference:

        return (
            "lookup_appointment",
            "lookup_appointment",
        )

    return (
        "search_appointments",
        "search_appointments",
    )


# ============================================================
# MAIN ADAPTER
# ============================================================

def adapt_understanding_to_nlu(
    *,
    result: UnderstandingResult,
    state: SessionState,
) -> NLUResult:
    """
    Convert a selected new UnderstandingResult into the
    legacy NLUResult expected by the current MedMind service
    and deterministic workflows.

    Ambiguous/fallback results must be handled before this
    adapter is called.
    """

    if result.status != "selected":

        raise ValueError(
            "Legacy adapter requires "
            "status='selected'. "
            f"Received: {result.status!r}"
        )

    capability = result.capability

    if not capability:

        raise ValueError(
            "Selected UnderstandingResult "
            "must contain a capability."
        )

    arguments = dict(
        result.arguments
        or {}
    )

    entities = _build_entities(
        arguments
    )

    # ========================================================
    # 1. OPERATION CAPABILITIES
    # ========================================================

    operation_type = (
        _OPERATION_CAPABILITIES.get(
            capability
        )
    )

    if operation_type is not None:

        active_operation = (
            _is_active_operation(
                state=state,
                operation_type=operation_type,
            )
        )

        # ----------------------------------------------------
        # Same operation already in progress.
        #
        # This is a contextual turn, confirmation, or
        # correction — not a new operation.
        # ----------------------------------------------------

        if active_operation:

            # ------------------------------------------------
            # Correction request WITHOUT replacement value.
            #
            # Example:
            # "رقم الموبايل غلط"
            # ------------------------------------------------

            if result.correction_target:

                correction_intent = (
                    _CORRECTION_TARGET_INTENTS.get(
                        result.correction_target
                    )
                )

                if correction_intent:

                    return NLUResult(
                        intent=correction_intent,
                        operation_type=None,
                        entities=entities,
                        confirmation="unknown",
                        confidence=(
                            COMPATIBILITY_CONFIDENCE
                        ),
                    )

            # ------------------------------------------------
            # Correction/contextual value WITH value.
            #
            # Example:
            # "لا الاسم الصح آية محمد"
            #
            # Multiple entities are preserved.
            # ------------------------------------------------

            contextual_intent = (
                _intent_from_arguments(
                    arguments=arguments,
                    state=state,
                )
            )

            if (
                contextual_intent
                != "unknown"
            ):

                return NLUResult(
                    intent=contextual_intent,
                    operation_type=None,
                    entities=entities,
                    confirmation="unknown",
                    confidence=(
                        COMPATIBILITY_CONFIDENCE
                    ),
                )

            # ------------------------------------------------
            # Pure confirmation.
            # ------------------------------------------------

            if (
                result.confirmation
                == "yes"
            ):

                return NLUResult(
                    intent="confirm_action",
                    operation_type=None,
                    entities=entities,
                    confirmation="yes",
                    confidence=(
                        COMPATIBILITY_CONFIDENCE
                    ),
                )

            if (
                result.confirmation
                == "no"
            ):

                return NLUResult(
                    intent="deny_action",
                    operation_type=None,
                    entities=entities,
                    confirmation="no",
                    confidence=(
                        COMPATIBILITY_CONFIDENCE
                    ),
                )

            # ------------------------------------------------
            # Capability is known and operation is active,
            # but the current turn supplies no usable legacy
            # value.
            #
            # Keeping operation_type=None prevents falsely
            # restarting the workflow.
            # ------------------------------------------------

            return NLUResult(
                intent="unknown",
                operation_type=None,
                entities=entities,
                confirmation="unknown",
                confidence=(
                    COMPATIBILITY_CONFIDENCE
                ),
            )

        # ----------------------------------------------------
        # New operation OR explicit operation switch.
        #
        # Examples:
        #
        # new:
        # "احجزلي بكرة"
        #
        # switch:
        # cancel -> "متلغهوش، خليه السبت"
        # ----------------------------------------------------

        return NLUResult(
            intent=operation_type,
            operation_type=operation_type,
            entities=entities,
            confirmation="unknown",
            confidence=(
                COMPATIBILITY_CONFIDENCE
            ),
        )

    # ========================================================
    # 2. APPOINTMENT SEARCH
    # ========================================================

    if (
        capability
        == "appointment.search"
    ):

        (
            search_intent,
            search_operation,
        ) = _adapt_appointment_search(
            entities=entities
        )

        return NLUResult(
            intent=search_intent,
            operation_type=search_operation,
            entities=entities,
            confirmation="unknown",
            confidence=(
                COMPATIBILITY_CONFIDENCE
            ),
        )

    # ========================================================
    # 3. INFORMATION / READ CAPABILITIES
    # ========================================================

    information_intent = (
        _INFORMATION_CAPABILITIES.get(
            capability
        )
    )

    if information_intent is not None:

        return NLUResult(
            intent=information_intent,
            operation_type=None,
            entities=entities,
            confirmation="unknown",
            confidence=(
                COMPATIBILITY_CONFIDENCE
            ),
        )

    # ========================================================
    # 4. UNKNOWN CAPABILITY
    # ========================================================

    raise ValueError(
        "No legacy NLU mapping exists for "
        f"capability={capability!r}"
    )