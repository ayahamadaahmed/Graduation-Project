from __future__ import annotations

from dataclasses import dataclass
import re

from medmind.resolvers.date import (
    resolve_date,
)

from medmind.state.models import (
    SessionState,
)

from medmind.understanding.types import (
    NLUResult,
)


# ============================================================
# EFFECTIVE CONTEXT
# ============================================================

@dataclass(frozen=True)
class EffectiveConversationContext:

    specialty_id: str | None
    specialty_name: str | None

    doctor_id: str | None
    doctor_name: str | None

    service_id: str | None
    service_name: str | None

    date_text: str | None
    time_text: str | None


# ============================================================
# HELPERS
# ============================================================

def _clean_text(
    value: str | None,
) -> str | None:

    if value is None:
        return None

    cleaned = (
        value.strip()
    )

    if not cleaned:
        return None

    return cleaned


def _normalize_match_text(
    value: str | None,
) -> str | None:

    value = _clean_text(
        value
    )

    if value is None:
        return None

    normalized = (
        value
        .casefold()
        .replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ى", "ي")
        .replace("ة", "ه")
    )

    # Remove Arabic diacritics and tatweel.
    normalized = re.sub(
        r"[\u064B-\u065F\u0670\u0640]",
        "",
        normalized,
    )

    normalized = re.sub(
        r"[^\w\s]",
        " ",
        normalized,
        flags=re.UNICODE,
    )

    tokens = normalized.split()

    # Doctor titles are presentation details, not identity.
    doctor_titles = {
        "د",
        "دكتور",
        "دكتوره",
        "الدكتور",
        "الدكتوره",
        "dr",
        "doctor",
    }

    while (
        tokens
        and
        tokens[0] in doctor_titles
    ):
        tokens.pop(0)

    if not tokens:
        return None

    return " ".join(
        tokens
    )


def _same_text(
    first: str | None,
    second: str | None,
) -> bool:

    first_normalized = (
        _normalize_match_text(
            first
        )
    )

    second_normalized = (
        _normalize_match_text(
            second
        )
    )

    if (
        first_normalized is None
        or second_normalized is None
    ):
        return False

    return (
        first_normalized
        == second_normalized
    )

# ============================================================
# CURRENT-TURN SCHEDULING FIELDS
# ============================================================

SCHEDULING_FIELDS = (
    "specialty_name",
    "doctor_name",
    "date_text",
    "time_text",
    "service_name",
)


def current_turn_scheduling_fields(
    nlu: NLUResult,
) -> tuple[str, ...]:

    fields = []

    for field_name in (
        SCHEDULING_FIELDS
    ):

        value = getattr(
            nlu.entities,
            field_name,
            None,
        )

        if _clean_text(
            value
        ) is not None:

            fields.append(
                field_name
            )

    return tuple(
        fields
    )


# ============================================================
# RESCHEDULE DEPENDENCY INVALIDATION
# ============================================================

def invalidate_reschedule_from_field(
    *,
    state: SessionState,
    field_name: str,
) -> None:

    # --------------------------------------------------------
    # DATE changed
    #
    # Old target slot and old target time are no longer
    # trustworthy.
    #
    # IMPORTANT:
    # Do NOT clear state.slot_* here.
    # Those describe the CURRENT appointment.
    # --------------------------------------------------------

    if field_name == "date_text":

        state.new_slot_id = None
        state.new_slot_date = None
        state.new_slot_time = None

        state.recent_slots = []

        state.awaiting_confirmation = (
            False
        )

        state.pending_action = None

        return

    # --------------------------------------------------------
    # TIME changed
    #
    # Keep new_slot_date and recent_slots because we can
    # validate the replacement time against the same date.
    # --------------------------------------------------------

    if field_name == "time_text":

        state.new_slot_id = None
        state.new_slot_time = None

        state.awaiting_confirmation = (
            False
        )

        state.pending_action = None
# ============================================================
# CURRENT TURN RECONCILIATION
# ============================================================

BOOKING_SCHEDULING_FIELDS = (
    "specialty_name",
    "doctor_name",
    "date_text",
    "time_text",
    "service_name",
)


def current_turn_scheduling_fields(
    nlu: NLUResult,
) -> tuple[str, ...]:

    """
    Return only scheduling fields explicitly supplied
    in the CURRENT user turn.

    Important:
    This does not inherit anything from state/context.
    """

    entities = nlu.entities

    supplied = []

    for field_name in (
        BOOKING_SCHEDULING_FIELDS
    ):

        value = _clean_text(
            getattr(
                entities,
                field_name,
                None,
            )
        )

        if value is not None:

            supplied.append(
                field_name
            )

    return tuple(
        supplied
    )


def invalidate_booking_from_field(
    *,
    state: SessionState,
    field_name: str,
) -> None:

    """
    Invalidate only information that depends on the
    explicitly changed field.

    specialty
        -> doctor + service + slot

    doctor
        -> service + slot

    date
        -> slot

    time
        -> selected slot

    service
        -> selected service
    """

    # ========================================================
    # SPECIALTY
    # ========================================================

    if field_name == "specialty_name":

        state.specialty_id = None
        state.specialty_name = None

        state.doctor_id = None
        state.doctor_name = None

        state.service_id = None
        state.service_name = None

        state.slot_id = None
        state.slot_date = None
        state.slot_time = None

        state.recent_doctors = []
        state.recent_services = []
        state.recent_slots = []

        return

    # ========================================================
    # DOCTOR
    # ========================================================

    if field_name == "doctor_name":

        # Keep recent_doctors because the new doctor may be
        # one of the already trusted choices.

        state.doctor_id = None
        state.doctor_name = None

        state.service_id = None
        state.service_name = None

        state.slot_id = None
        state.slot_date = None
        state.slot_time = None

        state.recent_services = []
        state.recent_slots = []

        return

    # ========================================================
    # DATE
    # ========================================================

    if field_name == "date_text":

        state.slot_id = None
        state.slot_date = None
        state.slot_time = None

        state.recent_slots = []

        return

    # ========================================================
    # TIME
    # ========================================================

    if field_name == "time_text":

        state.slot_id = None
        state.slot_time = None

        # Do NOT clear recent_slots.
        # _handle_time() needs the trusted slots to validate
        # the newly requested time.

        return

    # ========================================================
    # SERVICE
    # ========================================================

    if field_name == "service_name":

        state.service_id = None
        state.service_name = None


def invalidate_reschedule_from_field(
    *,
    state: SessionState,
    field_name: str,
) -> None:

    """
    Reschedule must NEVER overwrite the current appointment.

    slot_date / slot_time
        = existing appointment

    new_slot_date / new_slot_time
        = requested replacement
    """

    if field_name == "date_text":

        state.new_slot_id = None
        state.new_slot_date = None
        state.new_slot_time = None

        state.recent_slots = []

        return

    if field_name == "time_text":

        state.new_slot_id = None
        state.new_slot_time = None

        # Keep recent_slots so the new time can be validated.

def remember_pending_operation_entities(
    *,
    state: SessionState,
    nlu: NLUResult,
) -> None:

    entities = (
        nlu.entities
    )

    current_specialty = (
        _clean_text(
            entities.specialty_name
        )
    )

    current_doctor = (
        _clean_text(
            entities.doctor_name
        )
    )

    current_service = (
        _clean_text(
            entities.service_name
        )
    )

    current_date = (
        _clean_text(
            entities.date_text
        )
    )

    current_time = (
        _clean_text(
            entities.time_text
        )
    )

    pending = (
        state.pending_operation_entities
    )

    # ========================================================
    # SPECIALTY
    #
    # If specialty changes, an older doctor/service may no
    # longer belong to the selected specialty.
    # ========================================================

    if current_specialty is not None:

        previous_specialty = (
            pending.get(
                "specialty_name"
            )
            or
            state.specialty_name
            or
            state.conversation_specialty_name
        )

        specialty_changed = (
            previous_specialty is not None
            and
            not _same_text(
                current_specialty,
                previous_specialty,
            )
        )

        if specialty_changed:

            if current_doctor is None:

                pending.pop(
                    "doctor_name",
                    None,
                )

            if current_service is None:

                pending.pop(
                    "service_name",
                    None,
                )

        pending[
            "specialty_name"
        ] = current_specialty

    # ========================================================
    # DOCTOR
    #
    # If doctor changes, an older service may not belong
    # to the newly selected doctor.
    # ========================================================

    if current_doctor is not None:

        previous_doctor = (
            pending.get(
                "doctor_name"
            )
            or
            state.doctor_name
            or
            state.conversation_doctor_name
        )

        doctor_changed = (
            previous_doctor is not None
            and
            not _same_text(
                current_doctor,
                previous_doctor,
            )
        )

        if (
            doctor_changed
            and
            current_service is None
        ):

            pending.pop(
                "service_name",
                None,
            )

        pending[
            "doctor_name"
        ] = current_doctor

    # ========================================================
    # SERVICE
    # ========================================================

    if current_service is not None:

        pending[
            "service_name"
        ] = current_service

    
    if current_date is not None:

        previous_date = (
            _clean_text(
                pending.get(
                    "date_text"
                )
            )
        )

        if previous_date is None:

            if (
                state.operation_type
                == "reschedule_appointment"
            ):

                previous_date = (
                    _clean_text(
                        state.new_slot_date
                    )
                )

            else:

                previous_date = (
                    _clean_text(
                        state.slot_date
                    )
                )

        date_changed = (
            previous_date is not None
            and
            not _same_text(
                current_date,
                previous_date,
            )
        )

        if (
            date_changed
            and
            current_time is None
        ):

            pending.pop(
                "time_text",
                None,
            )

        pending[
            "date_text"
        ] = current_date


    # ========================================================
    # TIME
    # ========================================================

    if current_time is not None:

        pending[
            "time_text"
        ] = current_time

def resolve_effective_context(
    *,
    state: SessionState,
    nlu: NLUResult,
) -> EffectiveConversationContext:

    # ========================================================
    # CURRENT TURN
    # ========================================================

    current_specialty = (
        _clean_text(
            nlu.entities.specialty_name
        )
    )

    current_doctor = (
        _clean_text(
            nlu.entities.doctor_name
        )
    )

    current_service = (
        _clean_text(
            nlu.entities.service_name
        )
    )

    current_date = (
        _clean_text(
            nlu.entities.date_text
        )
    )

    current_time = (
        _clean_text(
            nlu.entities.time_text
        )
    )

    # ========================================================
    # PENDING OPERATION CONTEXT
    # ========================================================

    pending = (
        state.pending_operation_entities
    )

    pending_specialty = (
        _clean_text(
            pending.get(
                "specialty_name"
            )
        )
    )

    pending_doctor = (
        _clean_text(
            pending.get(
                "doctor_name"
            )
        )
    )

    pending_service = (
        _clean_text(
            pending.get(
                "service_name"
            )
        )
    )

    pending_date = (
        _clean_text(
            pending.get(
                "date_text"
            )
        )
    )

    pending_time = (
        _clean_text(
            pending.get(
                "time_text"
            )
        )
    )

    requested_specialty = (
        current_specialty
        or
        pending_specialty
    )

    # --------------------------------------------------------
    # Can we inherit doctor from CURRENT WORKFLOW state?
    # --------------------------------------------------------

    can_inherit_state_doctor = (
        requested_specialty is None
        or
        state.specialty_name is None
        or
        _same_text(
            requested_specialty,
            state.specialty_name,
        )
    )

    # --------------------------------------------------------
    # Can we inherit doctor from PERSISTENT CONVERSATION?
    # --------------------------------------------------------

    can_inherit_conversation_doctor = (
        requested_specialty is None
        or
        state.conversation_specialty_name
        is None
        or
        _same_text(
            requested_specialty,
            state.conversation_specialty_name,
        )
    )

    requested_doctor = (
        current_doctor
        or
        pending_doctor
    )

    # --------------------------------------------------------
    # Can we inherit service from CURRENT WORKFLOW state?
    # --------------------------------------------------------

    can_inherit_state_service = (
        can_inherit_state_doctor
        and
        (
            requested_doctor is None
            or
            state.doctor_name is None
            or
            _same_text(
                requested_doctor,
                state.doctor_name,
            )
        )
    )

    # --------------------------------------------------------
    # Can we inherit service from PERSISTENT CONVERSATION?
    # --------------------------------------------------------

    can_inherit_conversation_service = (
        can_inherit_conversation_doctor
        and
        (
            requested_doctor is None
            or
            state.conversation_doctor_name
            is None
            or
            _same_text(
                requested_doctor,
                state.conversation_doctor_name,
            )
        )
    )

    if current_specialty is not None:

        specialty_name = (
            current_specialty
        )

        if _same_text(
            current_specialty,
            state.specialty_name,
        ):

            specialty_id = (
                state.specialty_id
            )

        elif _same_text(
            current_specialty,
            state.conversation_specialty_name,
        ):

            specialty_id = (
                state.conversation_specialty_id
            )

        else:

            specialty_id = None

    elif pending_specialty is not None:

        specialty_name = (
            pending_specialty
        )

        if _same_text(
            pending_specialty,
            state.specialty_name,
        ):

            specialty_id = (
                state.specialty_id
            )

        elif _same_text(
            pending_specialty,
            state.conversation_specialty_name,
        ):

            specialty_id = (
                state.conversation_specialty_id
            )

        else:

            specialty_id = None

    elif state.specialty_name:

        specialty_name = (
            state.specialty_name
        )

        specialty_id = (
            state.specialty_id
        )

    else:

        specialty_name = (
            state.conversation_specialty_name
        )

        specialty_id = (
            state.conversation_specialty_id
        )

    if current_doctor is not None:

        doctor_name = (
            current_doctor
        )

        if _same_text(
            current_doctor,
            state.doctor_name,
        ):

            doctor_id = (
                state.doctor_id
            )

        elif _same_text(
            current_doctor,
            state.conversation_doctor_name,
        ):

            doctor_id = (
                state.conversation_doctor_id
            )

        else:

            doctor_id = None

    elif pending_doctor is not None:

        doctor_name = (
            pending_doctor
        )

        if _same_text(
            pending_doctor,
            state.doctor_name,
        ):

            doctor_id = (
                state.doctor_id
            )

        elif _same_text(
            pending_doctor,
            state.conversation_doctor_name,
        ):

            doctor_id = (
                state.conversation_doctor_id
            )

        else:

            doctor_id = None

    elif (
        can_inherit_state_doctor
        and
        state.doctor_name
    ):

        doctor_name = (
            state.doctor_name
        )

        doctor_id = (
            state.doctor_id
        )

    elif (
        can_inherit_conversation_doctor
        and
        state.conversation_doctor_name
    ):

        doctor_name = (
            state.conversation_doctor_name
        )

        doctor_id = (
            state.conversation_doctor_id
        )

    else:

        doctor_name = None
        doctor_id = None

    if current_service is not None:

        service_name = (
            current_service
        )

        if _same_text(
            current_service,
            state.service_name,
        ):

            service_id = (
                state.service_id
            )

        elif _same_text(
            current_service,
            state.conversation_service_name,
        ):

            service_id = (
                state.conversation_service_id
            )

        else:

            service_id = None

    elif pending_service is not None:

        service_name = (
            pending_service
        )

        if _same_text(
            pending_service,
            state.service_name,
        ):

            service_id = (
                state.service_id
            )

        elif _same_text(
            pending_service,
            state.conversation_service_name,
        ):

            service_id = (
                state.conversation_service_id
            )

        else:

            service_id = None

    elif (
        can_inherit_state_service
        and
        state.service_name
    ):

        service_name = (
            state.service_name
        )

        service_id = (
            state.service_id
        )

    elif (
        can_inherit_conversation_service
        and
        state.conversation_service_name
    ):

        service_name = (
            state.conversation_service_name
        )

        service_id = (
            state.conversation_service_id
        )

    else:

        service_name = None
        service_id = None

    # ========================================================
    # WORKFLOW DATE / TIME
    #
    # Reschedule owns separate new-slot fields.
    # ========================================================

    if (
        state.operation_type
        == "reschedule_appointment"
    ):

        state_date = (
            state.new_slot_date
            or
            state.slot_date
        )

        state_time = (
            state.new_slot_time
            or
            state.slot_time
        )

    else:

        state_date = (
            state.slot_date
        )

        state_time = (
            state.slot_time
        )

    can_inherit_conversation_date = (
        state.conversation_focus_capability
        in {
            "provider.get_slots",
            "provider.get_working_hours",
        }
    )

    conversation_date = (
        state.conversation_date_text
        if can_inherit_conversation_date
        else None
    )

    date_text = (
        current_date
        or
        pending_date
        or
        state_date
        or
        conversation_date
    )

    # ========================================================
    # TIME
    #
    # current
    # → pending
    # → trusted workflow
    # ========================================================

    time_text = (
        current_time
        or
        pending_time
        or
        state_time
    )

    # ========================================================
    # RESULT
    # ========================================================

    return EffectiveConversationContext(
        specialty_id=(
            specialty_id
        ),

        specialty_name=(
            specialty_name
        ),

        doctor_id=(
            doctor_id
        ),

        doctor_name=(
            doctor_name
        ),

        service_id=(
            service_id
        ),

        service_name=(
            service_name
        ),

        date_text=(
            date_text
        ),

        time_text=(
            time_text
        ),
    )

def remember_conversation_focus(
    *,
    state: SessionState,
    nlu: NLUResult,
    capability: str | None = None,
) -> None:

    pending = (
        state.pending_operation_entities
    )

    # Save old focus before changing anything.
    previous_specialty = (
        state.conversation_specialty_name
    )

    previous_doctor = (
        state.conversation_doctor_name
    )

    previous_service = (
        state.conversation_service_name
    )

    previous_specialty_id = (
        state.conversation_specialty_id
    )

    previous_doctor_id = (
        state.conversation_doctor_id
    )

    previous_service_id = (
        state.conversation_service_id
    )

    # ========================================================
    # CURRENT / PENDING VALUES
    # ========================================================

    current_specialty = (
        _clean_text(
            nlu.entities.specialty_name
        )
    )

    current_doctor = (
        _clean_text(
            nlu.entities.doctor_name
        )
    )

    current_service = (
        _clean_text(
            nlu.entities.service_name
        )
    )

    current_date = (
        _clean_text(
            nlu.entities.date_text
        )
    )

    pending_specialty = (
        _clean_text(
            pending.get(
                "specialty_name"
            )
        )
    )

    pending_doctor = (
        _clean_text(
            pending.get(
                "doctor_name"
            )
        )
    )

    pending_service = (
        _clean_text(
            pending.get(
                "service_name"
            )
        )
    )

    pending_date = (
        _clean_text(
            pending.get(
                "date_text"
            )
        )
    )

    # ========================================================
    # SPECIALTY
    #
    # Explicit current turn wins.
    # Reuse trusted ID only when the name matches.
    # ========================================================

    if current_specialty is not None:

        state.conversation_specialty_name = (
            current_specialty
        )

        if _same_text(
            current_specialty,
            state.specialty_name,
        ):

            state.conversation_specialty_id = (
                state.specialty_id
            )

        elif _same_text(
            current_specialty,
            previous_specialty,
        ):

            state.conversation_specialty_id = (
                previous_specialty_id
            )

        else:

            state.conversation_specialty_id = (
                None
            )

    elif state.specialty_name:

        state.conversation_specialty_name = (
            state.specialty_name
        )

        state.conversation_specialty_id = (
            state.specialty_id
        )

    elif pending_specialty is not None:

        state.conversation_specialty_name = (
            pending_specialty
        )

        if _same_text(
            pending_specialty,
            previous_specialty,
        ):

            state.conversation_specialty_id = (
                previous_specialty_id
            )

        else:

            state.conversation_specialty_id = (
                None
            )

    specialty_changed = (
        previous_specialty is not None
        and
        state.conversation_specialty_name
        is not None
        and
        not _same_text(
            previous_specialty,
            state.conversation_specialty_name,
        )
    )

    # ========================================================
    # DOCTOR
    #
    # Current turn wins.
    #
    # If specialty changed and no valid new doctor exists,
    # old doctor focus must be removed.
    # ========================================================

    if current_doctor is not None:

        state.conversation_doctor_name = (
            current_doctor
        )

        if _same_text(
            current_doctor,
            state.doctor_name,
        ):

            state.conversation_doctor_id = (
                state.doctor_id
            )

        elif (
            not specialty_changed
            and
            _same_text(
                current_doctor,
                previous_doctor,
            )
        ):

            state.conversation_doctor_id = (
                previous_doctor_id
            )

        else:

            state.conversation_doctor_id = (
                None
            )

    elif (
        state.doctor_name
        and
        (
            not specialty_changed
            or
            (
                state.specialty_name
                and
                _same_text(
                    state.specialty_name,
                    state.conversation_specialty_name,
                )
            )
        )
    ):

        state.conversation_doctor_name = (
            state.doctor_name
        )

        state.conversation_doctor_id = (
            state.doctor_id
        )

    elif specialty_changed:

        state.conversation_doctor_name = (
            None
        )

        state.conversation_doctor_id = (
            None
        )

    elif pending_doctor is not None:

        state.conversation_doctor_name = (
            pending_doctor
        )

        if _same_text(
            pending_doctor,
            previous_doctor,
        ):

            state.conversation_doctor_id = (
                previous_doctor_id
            )

        else:

            state.conversation_doctor_id = (
                None
            )

    doctor_changed = (
        previous_doctor is not None
        and
        state.conversation_doctor_name
        is not None
        and
        not _same_text(
            previous_doctor,
            state.conversation_doctor_name,
        )
    )

    doctor_removed = (
        previous_doctor is not None
        and
        state.conversation_doctor_name
        is None
    )

    # ========================================================
    # SERVICE
    #
    # Doctor/specialty changes invalidate an older service
    # unless a valid replacement was supplied/resolved.
    # ========================================================

    if current_service is not None:

        state.conversation_service_name = (
            current_service
        )

        if _same_text(
            current_service,
            state.service_name,
        ):

            state.conversation_service_id = (
                state.service_id
            )

        elif (
            not specialty_changed
            and
            not doctor_changed
            and
            not doctor_removed
            and
            _same_text(
                current_service,
                previous_service,
            )
        ):

            state.conversation_service_id = (
                previous_service_id
            )

        else:

            state.conversation_service_id = (
                None
            )

    elif (
        state.service_name
        and
        (
            not specialty_changed
            and
            not doctor_changed
            and
            not doctor_removed
            or
            (
                state.doctor_name
                and
                _same_text(
                    state.doctor_name,
                    state.conversation_doctor_name,
                )
            )
        )
    ):

        state.conversation_service_name = (
            state.service_name
        )

        state.conversation_service_id = (
            state.service_id
        )

    elif (
        specialty_changed
        or
        doctor_changed
        or
        doctor_removed
    ):

        state.conversation_service_name = (
            None
        )

        state.conversation_service_id = (
            None
        )

    elif pending_service is not None:

        state.conversation_service_name = (
            pending_service
        )

        if _same_text(
            pending_service,
            previous_service,
        ):

            state.conversation_service_id = (
                previous_service_id
            )

        else:

            state.conversation_service_id = (
                None
            )

    # ========================================================
    # SCHEDULING DATE
    #
    # Persist only for scheduling-oriented read focus. The
    # capability gate in resolve_effective_context prevents an
    # old read date from leaking into unrelated conversations.
    # ========================================================

    if capability in {
        "provider.get_slots",
        "provider.get_working_hours",
    }:

        date_source = (
            current_date
            or
            pending_date
            or
            state.conversation_date_text
        )

        if date_source:

            resolved = resolve_date(
                date_source
            )

            if resolved is not None:

                state.conversation_date_text = (
                    resolved.isoformat()
                )

    # ========================================================
    # CAPABILITY
    # ========================================================

    if capability:

        state.conversation_focus_capability = (
            capability
        )