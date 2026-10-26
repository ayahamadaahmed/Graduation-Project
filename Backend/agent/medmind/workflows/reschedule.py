from __future__ import annotations

from typing import Any
from uuid import uuid4

from medmind.core.tool_executor import (
    MCPToolExecutor,
)

from medmind.resolvers.date import (
    resolve_date,
)

from medmind.resolvers.national_id import (
    resolve_national_id,
)

from medmind.resolvers.time import (
    resolve_time_candidates,
)

from medmind.state.context import (
    current_turn_scheduling_fields,
    invalidate_reschedule_from_field,
    remember_pending_operation_entities,
    resolve_effective_context,
)

from medmind.state.models import (
    AppointmentSnapshot,
    SessionState,
)

from medmind.state.updater import (
    apply_tool_observation,
)

from medmind.understanding.types import (
    NLUResult,
)

from medmind.workflows.appointment_selection import (
    build_selection_prompt,
    is_negative,
    resolve_appointment_selection,
    search_patient_appointments,
)

from medmind.workflows.types import (
    WorkflowResult,
)


# ============================================================
# HELPERS
# ============================================================

def ensure_list(
    value: Any,
) -> list:

    if value is None:
        return []

    if isinstance(
        value,
        list,
    ):
        return value

    return [
        value
    ]


# ============================================================
# RESCHEDULE WORKFLOW
# ============================================================

class RescheduleWorkflow:

    def __init__(
        self,
        *,
        tools: MCPToolExecutor,
    ) -> None:

        self.tools = tools

    # ========================================================
    # TEXT NORMALIZATION
    # ========================================================

    @staticmethod
    def _normalize_selection_text(
        value: str | None,
    ) -> str:

        if not value:
            return ""

        normalized = (
            value
            .strip()
            .casefold()
            .replace("أ", "ا")
            .replace("إ", "ا")
            .replace("آ", "ا")
            .replace("ى", "ي")
            .replace("ة", "ه")
        )

        tokens = normalized.split()

        doctor_titles = {
            "د",
            "د.",
            "دكتور",
            "دكتوره",
            "الدكتور",
            "الدكتوره",
            "dr",
            "dr.",
            "doctor",
        }

        while (
            tokens
            and
            tokens[0] in doctor_titles
        ):
            tokens.pop(0)

        return " ".join(
            tokens
        )

    # ========================================================
    # CONTEXTUAL BOOKING RESOLUTION
    # ========================================================

    @classmethod
    def _resolve_contextual_booking(
        cls,
        *,
        state: SessionState,
        appointments: list[
            AppointmentSnapshot
        ],
    ) -> AppointmentSnapshot | None:

        # ----------------------------------------------------
        # IMPORTANT
        #
        # In reschedule:
        #
        # date_text / time_text
        #
        # describe the NEW requested appointment.
        #
        # They must NOT be used to identify the CURRENT
        # appointment that will be rescheduled.
        # ----------------------------------------------------

        pending = (
            state.pending_operation_entities
        )

        doctor_name = pending.get(
            "doctor_name"
        )

        specialty_name = pending.get(
            "specialty_name"
        )

        service_name = pending.get(
            "service_name"
        )

        if not any(
            (
                doctor_name,
                specialty_name,
                service_name,
            )
        ):
            return None

        matches = list(
            appointments
        )

        for (
            requested,
            attribute,
        ) in (
            (
                doctor_name,
                "doctor_name",
            ),
            (
                specialty_name,
                "specialty_name",
            ),
            (
                service_name,
                "service_name",
            ),
        ):

            if not requested:
                continue

            query = (
                cls._normalize_selection_text(
                    requested
                )
            )

            narrowed = []

            for row in matches:

                candidate = getattr(
                    row,
                    attribute,
                    None,
                )

                candidate_normalized = (
                    cls._normalize_selection_text(
                        candidate
                    )
                )

                if (
                    candidate_normalized
                    and
                    (
                        query
                        == candidate_normalized

                        or

                        query
                        in candidate_normalized

                        or

                        candidate_normalized
                        in query
                    )
                ):

                    narrowed.append(
                        row
                    )

            if not narrowed:
                return None

            matches = narrowed

        if len(matches) == 1:

            return matches[0]

        return None

    # ========================================================
    # REQUESTED NEW DATE / TIME
    # ========================================================

    @staticmethod
    def _requested_new_date_text(
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> str | None:

        return (
            nlu.entities.date_text
            or
            state.pending_operation_entities.get(
                "date_text"
            )
        )

    @staticmethod
    def _requested_new_time_text(
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> str | None:

        return (
            nlu.entities.time_text
            or
            state.pending_operation_entities.get(
                "time_text"
            )
        )

    async def _reconcile_current_turn(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult | None:

        supplied_fields = (
            current_turn_scheduling_fields(
                nlu
            )
        )

        if not supplied_fields:

            return None

        # ========================================================
        # IDENTITY / APPOINTMENT SELECTION COMES FIRST
        #
        # Date/time supplied early are already stored in
        # pending_operation_entities.
        #
        # Do NOT skip identity or booking ownership checks.
        # ========================================================

        if state.stage in {
            "new",
            "awaiting_reschedule_national_id",
            "awaiting_reschedule_booking_selection",
            "awaiting_reschedule_reference",
        }:

            return None

        # ========================================================
        # DATE CORRECTION
        #
        # Higher dependency wins.
        # ========================================================

        if (
            "date_text"
            in supplied_fields
            and
            state.stage
            in {
                "awaiting_reschedule_date",
                "awaiting_reschedule_time",
                "awaiting_reschedule_confirmation",
            }
        ):

            invalidate_reschedule_from_field(
                state=state,
                field_name="date_text",
            )

            state.stage = (
                "awaiting_reschedule_date"
            )

            return await (
                self._handle_date(
                    state=state,
                    nlu=nlu,
                )
            )

        # ========================================================
        # TIME CORRECTION
        # ========================================================

        if (
            "time_text"
            in supplied_fields
            and
            state.stage
            in {
                "awaiting_reschedule_time",
                "awaiting_reschedule_confirmation",
            }
        ):

            invalidate_reschedule_from_field(
                state=state,
                field_name="time_text",
            )

            state.stage = (
                "awaiting_reschedule_time"
            )

            return await (
                self._handle_time(
                    state=state,
                    nlu=nlu,
                )
            )

        return None

    # ========================================================
    # PUBLIC ENTRY
    # ========================================================

    async def handle(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
        user_message: str = "",
    ) -> WorkflowResult:

        # ----------------------------------------------------
        # Detect explicit reschedule request
        # ----------------------------------------------------

        is_reschedule_request = (
            nlu.intent
            == "reschedule_appointment"

            or

            nlu.operation_type
            == "reschedule_appointment"
        )

        # ----------------------------------------------------
        # Start reschedule operation
        # ----------------------------------------------------

        if is_reschedule_request:

            # A finished reschedule followed by a new reschedule request
            # starts a new operation (and so needs a fresh national ID).
            if (
                state.operation_type
                != "reschedule_appointment"
                or state.stage == "reschedule_completed"
            ):

                previous_reference = (
                    nlu.entities
                    .appointment_reference
                    or
                    state.appointment_reference
                )

                state.reset_operation(
                    preserve_patient=True,
                )

                # Fresh identity per sensitive operation.
                state.forget_identity_proof()

                state.operation_type = (
                    "reschedule_appointment"
                )

                state.stage = "new"

                if previous_reference:

                    state.appointment_reference = (
                        previous_reference
                        .strip()
                        .upper()
                    )

        # ----------------------------------------------------
        # This workflow owns only reschedule
        # ----------------------------------------------------

        if (
            state.operation_type
            != "reschedule_appointment"
        ):

            return WorkflowResult(
                handled=False,
                reply="",
                response_type=(
                    "not_reschedule"
                ),
            )

        remember_pending_operation_entities(
            state=state,
            nlu=nlu,
        )

        reconciled_result = await (
            self._reconcile_current_turn(
                state=state,
                nlu=nlu,
            )
        )

        if reconciled_result is not None:

            return reconciled_result

        # ----------------------------------------------------
        # Stage routing
        # ----------------------------------------------------

        if state.stage == "new":

            return await (
                self._handle_new(
                    state=state,
                    nlu=nlu,
                )
            )

        if (
            state.stage
            == "awaiting_reschedule_national_id"
        ):

            return await (
                self._handle_national_id(
                    state=state,
                    nlu=nlu,
                )
            )

        if (
            state.stage
            == "awaiting_reschedule_booking_selection"
        ):

            return await (
                self._handle_booking_selection(
                    state=state,
                    nlu=nlu,
                    user_message=user_message,
                )
            )

        if (
            state.stage
            == "awaiting_reschedule_reference"
        ):

            return await (
                self._handle_reference(
                    state=state,
                    nlu=nlu,
                )
            )

        if (
            state.stage
            == "awaiting_reschedule_date"
        ):

            return await (
                self._handle_date(
                    state=state,
                    nlu=nlu,
                )
            )

        if (
            state.stage
            == "awaiting_reschedule_time"
        ):

            return await (
                self._handle_time(
                    state=state,
                    nlu=nlu,
                )
            )

        if (
            state.stage
            == "awaiting_reschedule_confirmation"
        ):

            return await (
                self._handle_confirmation(
                    state=state,
                    nlu=nlu,
                )
            )

        return WorkflowResult(
            reply=self._message(
                state.language,

                ar=(
                    "لسه بنجهز المرحلة دي "
                    "من تغيير الميعاد."
                ),

                en=(
                    "This reschedule stage "
                    "is still being implemented."
                ),
            ),

            response_type=(
                "reschedule_stage_not_implemented"
            ),
        )

    # ========================================================
    # CURRENT TURN RECONCILIATION
    # ========================================================

    async def _reconcile_current_turn(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult | None:

        """
        Reconcile schedule information explicitly supplied
        in the current user turn.

        The workflow stage represents what we currently need,
        not what the user is allowed to say.

        Examples:

            Agent:
                "Which new time?"

            User:
                "Actually Thursday."

        or:

            Agent:
                "Confirm the reschedule?"

            User:
                "Make it 5 PM instead."

        Both must update the requested target slot rather
        than being ignored.
        """

        relevant_stages = {
            "awaiting_reschedule_date",
            "awaiting_reschedule_time",
            "awaiting_reschedule_confirmation",
        }

        if (
            state.stage
            not in relevant_stages
        ):

            return None

        supplied_fields = (
            current_turn_scheduling_fields(
                nlu
            )
        )

        has_new_date = (
            "date_text"
            in supplied_fields
        )

        has_new_time = (
            "time_text"
            in supplied_fields
        )

        # ====================================================
        # DATE HAS HIGHER DEPENDENCY PRIORITY THAN TIME
        #
        # User:
        # "لا الخميس الساعة خمسة"
        #
        # We must:
        #
        # 1. load Thursday slots
        # 2. then validate 5 PM against those slots
        # ====================================================

        if has_new_date:

            invalidate_reschedule_from_field(
                state=state,
                field_name="date_text",
            )

            state.awaiting_confirmation = (
                False
            )

            state.pending_action = None

            state.stage = (
                "awaiting_reschedule_date"
            )

            return await (
                self._handle_date(
                    state=state,
                    nlu=nlu,
                )
            )

        # ====================================================
        # TIME CORRECTION
        # ====================================================

        if has_new_time:

            # ------------------------------------------------
            # A time cannot be selected until we know which
            # target date its slots belong to.
            # ------------------------------------------------

            if not (
                state.new_slot_date

                or

                state.pending_operation_entities.get(
                    "date_text"
                )
            ):

                return None

            invalidate_reschedule_from_field(
                state=state,
                field_name="time_text",
            )

            state.awaiting_confirmation = (
                False
            )

            state.pending_action = None

            state.stage = (
                "awaiting_reschedule_time"
            )

            return await (
                self._handle_time(
                    state=state,
                    nlu=nlu,
                )
            )

        return None

    # ========================================================
    # NEW
    # ========================================================

    async def _handle_new(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        # ----------------------------------------------------
        # National ID supplied in same message
        # ----------------------------------------------------

        if (
            not state.national_id
            and
            nlu.entities.national_id
        ):

            return await (
                self._handle_national_id(
                    state=state,
                    nlu=nlu,
                )
            )

        # ----------------------------------------------------
        # Patient identity unknown
        # ----------------------------------------------------

        if not state.national_id:

            state.stage = (
                "awaiting_reschedule_national_id"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "تمام. ممكن الرقم القومي "
                        "عشان أتأكد من الحجز؟"
                    ),

                    en=(
                        "Sure. Please provide the "
                        "national ID so I can verify "
                        "the booking."
                    ),
                ),

                response_type=(
                    "ask_reschedule_national_id"
                ),
            )

        # ----------------------------------------------------
        # Appointment reference
        # ----------------------------------------------------

        reference = (
            nlu.entities
            .appointment_reference
            or
            state.appointment_reference
        )

        if reference:

            state.appointment_reference = (
                reference
                .strip()
                .upper()
            )

            return await (
                self._lookup_current_booking(
                    state=state,
                    nlu=nlu,
                )
            )

        return await (
            self._load_booking_candidates(
                state=state,
                nlu=nlu,
            )
        )

    # ========================================================
    # NATIONAL ID
    # ========================================================

    async def _handle_national_id(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        national_id_text = (
            nlu.entities
            .national_id
        )

        if not national_id_text:

            state.stage = (
                "awaiting_reschedule_national_id"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "ممكن تديني الرقم القومي "
                        "المكوّن من 14 رقم؟"
                    ),

                    en=(
                        "Please provide the "
                        "14-digit national ID."
                    ),
                ),

                response_type=(
                    "ask_reschedule_national_id"
                ),
            )

        national_id = (
            resolve_national_id(
                national_id_text
            )
        )

        if national_id is None:

            state.stage = (
                "awaiting_reschedule_national_id"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "الرقم القومي لازم يكون "
                        "14 رقم. ممكن تراجعيه "
                        "وتبعتيه تاني؟"
                    ),

                    en=(
                        "The national ID must contain "
                        "14 digits. Please check it "
                        "and send it again."
                    ),
                ),

                response_type=(
                    "invalid_national_id"
                ),
            )

        state.national_id = (
            national_id
        )

        reference = (
            nlu.entities
            .appointment_reference
            or
            state.appointment_reference
        )

        if reference:

            state.appointment_reference = (
                reference
                .strip()
                .upper()
            )

            return await (
                self._lookup_current_booking(
                    state=state,
                    nlu=nlu,
                )
            )

        return await (
            self._load_booking_candidates(
                state=state,
                nlu=nlu,
            )
        )

    # ========================================================
    # LOAD BOOKING CANDIDATES
    # ========================================================

    async def _load_booking_candidates(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        if not state.national_id:

            state.stage = (
                "awaiting_reschedule_national_id"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "ممكن الرقم القومي "
                        "عشان أجيب حجوزاتك؟"
                    ),

                    en=(
                        "Please provide the national ID "
                        "so I can find your appointments."
                    ),
                ),

                response_type=(
                    "ask_reschedule_national_id"
                ),
            )

        # ----------------------------------------------------
        # Appointment reference is internal to the agent.
        #
        # Clear stale references before discovering current
        # confirmed bookings.
        # ----------------------------------------------------

        state.appointment_reference = None

        try:

            appointments = await (
                search_patient_appointments(
                    tools=self.tools,

                    national_id=(
                        state.national_id
                    ),

                    action="reschedule",

                    limit=5,
                )
            )

        except RuntimeError:

            state.candidate_appointments = []

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "مقدرتش أجيب حجوزاتك "
                        "دلوقتي. جربي تاني بعد شوية."
                    ),

                    en=(
                        "I couldn't retrieve your "
                        "appointments right now. "
                        "Please try again shortly."
                    ),
                ),

                response_type=(
                    "reschedule_search_failed"
                ),
            )

        state.candidate_appointments = (
            appointments
        )

        state.appointment_reference = None

        if not appointments:

            state.stage = (
                "reschedule_not_found"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "ملقتش عندك حجوزات مؤكدة "
                        "ينفع نغيّر ميعادها."
                    ),

                    en=(
                        "I couldn't find any confirmed "
                        "appointments to reschedule."
                    ),
                ),

                response_type=(
                    "reschedule_no_active_bookings"
                ),
            )

        # ----------------------------------------------------
        # Try to identify one booking from conversation
        # context such as doctor/specialty/service.
        # ----------------------------------------------------

        contextual_booking = (
            self._resolve_contextual_booking(
                state=state,
                appointments=appointments,
            )
        )

        if contextual_booking is not None:

            state.appointment_reference = (
                contextual_booking
                .appointment_reference
                .strip()
                .upper()
            )

            state.candidate_appointments = []

            return await (
                self._lookup_current_booking(
                    state=state,
                    nlu=nlu,
                )
            )

        state.stage = (
            "awaiting_reschedule_booking_selection"
        )

        return WorkflowResult(
            reply=build_selection_prompt(
                appointments,
                language=state.language,
                action="reschedule",
            ),

            response_type=(
                "ask_reschedule_booking_selection"
            ),

            data={
                "appointment_count":
                    len(
                        appointments
                    ),
            },
        )

    # ========================================================
    # BOOKING SELECTION
    # ========================================================

    async def _handle_booking_selection(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
        user_message: str,
    ) -> WorkflowResult:

        reference = (
            nlu.entities
            .appointment_reference
        )

        if reference:

            state.appointment_reference = (
                reference
                .strip()
                .upper()
            )

            state.candidate_appointments = []

            return await (
                self._lookup_current_booking(
                    state=state,
                    nlu=nlu,
                )
            )

        candidates: list[
            AppointmentSnapshot
        ] = list(
            state.candidate_appointments
        )

        if not candidates:

            return await (
                self._load_booking_candidates(
                    state=state,
                    nlu=nlu,
                )
            )

        denied = (
            nlu.intent
            == "deny_action"

            or

            nlu.confirmation
            == "no"

            or

            is_negative(
                user_message
            )
        )

        if denied:

            state.candidate_appointments = []
            state.appointment_reference = None

            state.awaiting_confirmation = (
                False
            )

            state.pending_action = None

            state.stage = (
                "reschedule_declined"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "تمام، مش هغيّر ميعاد أي حجز."
                    ),

                    en=(
                        "Okay, I won't reschedule "
                        "any appointment."
                    ),
                ),

                response_type=(
                    "reschedule_selection_declined"
                ),
            )

        if (
            len(candidates) == 1
            and
            (
                nlu.intent
                == "confirm_action"

                or

                nlu.confirmation
                == "yes"
            )
        ):

            selected_index = 0

        else:

            selected_index = (
                resolve_appointment_selection(
                    user_message,
                    candidates,
                )
            )

        if selected_index is None:

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "ممكن تقولي أنهي حجز؟ "
                        "مثلاً الأول أو التاني."
                    ),

                    en=(
                        "Please tell me which appointment "
                        "you mean, for example first "
                        "or second."
                    ),
                ),

                response_type=(
                    "ask_reschedule_booking_selection"
                ),
            )

        selected = (
            candidates[
                selected_index
            ]
        )

        state.appointment_reference = (
            selected
            .appointment_reference
            .strip()
            .upper()
        )

        state.candidate_appointments = []

        return await (
            self._lookup_current_booking(
                state=state,
                nlu=nlu,
            )
        )

    # ========================================================
    # APPOINTMENT REFERENCE
    # ========================================================

    async def _handle_reference(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        reference = (
            nlu.entities
            .appointment_reference
        )

        if not reference:

            # ------------------------------------------------
            # Legacy stage recovery.
            #
            # Do not ask a voice caller to pronounce APT-...
            # ------------------------------------------------

            return await (
                self._load_booking_candidates(
                    state=state,
                    nlu=nlu,
                )
            )

        state.appointment_reference = (
            reference
            .strip()
            .upper()
        )

        return await (
            self._lookup_current_booking(
                state=state,
                nlu=nlu,
            )
        )

    # ========================================================
    # LOOKUP CURRENT BOOKING
    # ========================================================

    async def _lookup_current_booking(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        if not state.national_id:

            state.appointment_reference = None
            state.candidate_appointments = []

            state.stage = (
                "awaiting_reschedule_national_id"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "ممكن الرقم القومي "
                        "عشان أجيب حجوزاتك؟"
                    ),

                    en=(
                        "Please provide the national ID "
                        "so I can find your appointments."
                    ),
                ),

                response_type=(
                    "ask_reschedule_national_id"
                ),
            )

        if not state.appointment_reference:

            return await (
                self._load_booking_candidates(
                    state=state,
                    nlu=nlu,
                )
            )

        result = await self.tools.call(
            "lookup_booking",

            national_id=(
                state.national_id
            ),

            appointment_reference=(
                state.appointment_reference
            ),
        )

        if not isinstance(
            result,
            dict,
        ):

            state.appointment_reference = None
            state.candidate_appointments = []

            return await (
                self._load_booking_candidates(
                    state=state,
                    nlu=nlu,
                )
            )

        backend_reference = (
            result.get(
                "appointment_reference"
            )
        )

        if not backend_reference:

            state.appointment_reference = None
            state.candidate_appointments = []

            return await (
                self._load_booking_candidates(
                    state=state,
                    nlu=nlu,
                )
            )

        # ----------------------------------------------------
        # Only confirmed bookings can be rescheduled
        # ----------------------------------------------------

        status = str(
            result.get(
                "status"
            )
            or ""
        ).strip().lower()

        if status != "confirmed":

            state.awaiting_confirmation = (
                False
            )

            state.pending_action = None

            state.stage = (
                "reschedule_not_allowed"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "الحجز ده مش في حالة تسمح "
                        "بتغيير الميعاد."
                    ),

                    en=(
                        "This booking is not in a "
                        "state that can be rescheduled."
                    ),
                ),

                response_type=(
                    "reschedule_not_allowed"
                ),

                data={
                    "booking_status":
                        status,
                },
            )

        # ----------------------------------------------------
        # Trusted identifiers from backend
        # ----------------------------------------------------

        doctor_id = (
            result.get(
                "doctor_id"
            )
        )

        slot_id = (
            result.get(
                "slot_id"
            )
        )

        service_id = (
            result.get(
                "service_id"
            )
        )

        if (
            not doctor_id
            or
            not slot_id
        ):

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "بيانات الحجز ناقصة "
                        "ومش قادر أحدد الميعاد الحالي."
                    ),

                    en=(
                        "The booking data is incomplete, "
                        "so I can't determine the current "
                        "appointment slot."
                    ),
                ),

                response_type=(
                    "reschedule_booking_data_incomplete"
                ),
            )

        # ----------------------------------------------------
        # Save CURRENT appointment
        # ----------------------------------------------------

        state.appointment_reference = (
            str(
                backend_reference
            )
            .strip()
            .upper()
        )

        state.candidate_appointments = []

        state.doctor_id = str(
            doctor_id
        )

        state.doctor_name = (
            result.get(
                "doctor_name"
            )
        )

        state.service_id = (
            str(
                service_id
            )
            if service_id
            else None
        )

        state.service_name = (
            result.get(
                "service_name"
            )
        )

        state.slot_id = str(
            slot_id
        )

        scheduled_date = (
            result.get(
                "scheduled_date"
            )
        )

        start_time = (
            result.get(
                "start_time"
            )
        )

        state.slot_date = (
            str(
                scheduled_date
            )
            if scheduled_date
            else None
        )

        state.slot_time = (
            str(
                start_time
            )[:5]
            if start_time
            else None
        )

        # ----------------------------------------------------
        # Clear previous target slot
        # ----------------------------------------------------

        state.new_slot_id = None
        state.new_slot_date = None
        state.new_slot_time = None

        state.recent_slots = []

        state.awaiting_confirmation = (
            False
        )

        state.pending_action = None

        # ====================================================
        # NEW-SLOT HANDOFF
        #
        # If the original request already included the target
        # date/time, continue automatically.
        #
        # Example:
        #
        # "غير حجز دكتور ماهر للخميس الساعة خمسة"
        # ====================================================

        requested_new_date = (
            self._requested_new_date_text(
                state=state,
                nlu=nlu,
            )
        )

        if requested_new_date:

            return await (
                self._handle_date(
                    state=state,
                    nlu=nlu,
                )
            )

        state.stage = (
            "awaiting_reschedule_date"
        )

        return WorkflowResult(
            reply=self._message(
                state.language,

                ar=(
                    f"ميعادك الحالي مع "
                    f"{state.doctor_name} يوم "
                    f"{state.slot_date} الساعة "
                    f"{state.slot_time}. "
                    "تحبي تغيريه ليوم إيه؟"
                ),

                en=(
                    f"Your current appointment with "
                    f"{state.doctor_name} is on "
                    f"{state.slot_date} at "
                    f"{state.slot_time}. "
                    "What new date would you like?"
                ),
            ),

            response_type=(
                "ask_reschedule_date"
            ),

            data={
                "appointment_reference":
                    state.appointment_reference,

                "doctor_id":
                    state.doctor_id,

                "old_slot_id":
                    state.slot_id,

                "old_date":
                    state.slot_date,

                "old_time":
                    state.slot_time,
            },
        )

    # ========================================================
    # NEW DATE
    # ========================================================

    async def _handle_date(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        date_text = (
            self._requested_new_date_text(
                state=state,
                nlu=nlu,
            )
        )

        if not date_text:

            state.stage = (
                "awaiting_reschedule_date"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "قولي اليوم أو التاريخ "
                        "الجديد اللي يناسبك."
                    ),

                    en=(
                        "Please tell me the new "
                        "date you prefer."
                    ),
                ),

                response_type=(
                    "ask_reschedule_date"
                ),
            )

        resolved_date = (
            resolve_date(
                date_text
            )
        )

        if resolved_date is None:

            state.stage = (
                "awaiting_reschedule_date"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "مش قادر أحدد التاريخ ده. "
                        "ممكن تقولي مثلاً بكرة، "
                        "بعد بكرة، أو تاريخ زي 20/8؟"
                    ),

                    en=(
                        "I couldn't understand that "
                        "date. You can say tomorrow, "
                        "the day after tomorrow, "
                        "or a date such as 20/8."
                    ),
                ),

                response_type=(
                    "invalid_reschedule_date"
                ),
            )

        if not state.doctor_id:

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "مش قادر أحدد الدكتور "
                        "المرتبط بالحجز."
                    ),

                    en=(
                        "I can't determine the doctor "
                        "associated with the booking."
                    ),
                ),

                response_type=(
                    "reschedule_doctor_missing"
                ),
            )

        resolved_date_text = (
            resolved_date
            .isoformat()
        )

        # ----------------------------------------------------
        # Load trusted available slots
        # ----------------------------------------------------

        slots = await self.tools.call(
            "list_available_slots",

            doctor_id=(
                state.doctor_id
            ),

            slot_date=(
                resolved_date_text
            ),

            limit=100,
        )

        apply_tool_observation(
            state=state,

            tool_name=(
                "list_available_slots"
            ),

            data=slots,
        )

        state.new_slot_date = (
            resolved_date_text
        )

        requested_time = (
            self._requested_new_time_text(
                state=state,
                nlu=nlu,
            )
        )

        if requested_time:

            return await (
                self._handle_time(
                    state=state,
                    nlu=nlu,
                )
            )

        state.new_slot_id = None
        state.new_slot_time = None

        # ----------------------------------------------------
        # No available slots
        # ----------------------------------------------------

        if not state.recent_slots:

            state.stage = (
                "awaiting_reschedule_date"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        f"مفيش مواعيد متاحة مع "
                        f"{state.doctor_name} يوم "
                        f"{resolved_date_text}. "
                        "تحبي يوم تاني؟"
                    ),

                    en=(
                        f"There are no available slots "
                        f"with {state.doctor_name} on "
                        f"{resolved_date_text}. "
                        "Would you like another date?"
                    ),
                ),

                response_type=(
                    "no_reschedule_slots"
                ),
            )

        available_times = [
            slot.start_time[:5]
            for slot
            in state.recent_slots
        ]

        state.stage = (
            "awaiting_reschedule_time"
        )

        # ====================================================
        # SAME-TURN / PENDING TIME HANDOFF
        #
        # User:
        # "الخميس الساعة خمسة"
        #
        # We already loaded Thursday.
        # Do NOT ask for the time again.
        # ====================================================

        requested_new_time = (
            self._requested_new_time_text(
                state=state,
                nlu=nlu,
            )
        )

        if requested_new_time:

            return await (
                self._handle_time(
                    state=state,
                    nlu=nlu,
                )
            )

        if state.language == "en":

            reply = (
                f"Available times on "
                f"{resolved_date_text}: "
                + ", ".join(
                    available_times
                )
                + ". Which time would you like?"
            )

        else:

            reply = (
                f"المواعيد المتاحة يوم "
                f"{resolved_date_text}: "
                + "، ".join(
                    available_times
                )
                + ". تحبي الساعة كام؟"
            )

        return WorkflowResult(
            reply=reply,

            response_type=(
                "ask_reschedule_time"
            ),

            data={
                "new_date":
                    resolved_date_text,

                "available_times":
                    available_times,
            },
        )

    # ========================================================
    # NEW TIME
    # ========================================================

    async def _handle_time(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        time_text = (
            self._requested_new_time_text(
                state=state,
                nlu=nlu,
            )
        )

        if not time_text:

            state.stage = (
                "awaiting_reschedule_time"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "اختاري ساعة من "
                        "المواعيد المتاحة."
                    ),

                    en=(
                        "Please choose one of "
                        "the available times."
                    ),
                ),

                response_type=(
                    "ask_reschedule_time"
                ),
            )

        if not state.recent_slots:

            state.stage = (
                "awaiting_reschedule_date"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "محتاجين نختار التاريخ "
                        "الجديد الأول."
                    ),

                    en=(
                        "We need to choose the new "
                        "date first."
                    ),
                ),

                response_type=(
                    "reschedule_date_required"
                ),
            )

        candidates = (
            resolve_time_candidates(
                time_text
            )
        )

        if not candidates:

            state.stage = (
                "awaiting_reschedule_time"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "مش قادر أحدد الساعة دي. "
                        "اختاري وقت من المواعيد المتاحة."
                    ),

                    en=(
                        "I couldn't understand that "
                        "time. Please choose one of "
                        "the available times."
                    ),
                ),

                response_type=(
                    "invalid_reschedule_time"
                ),
            )

        matches = []

        for slot in (
            state.recent_slots
        ):

            slot_time = (
                slot.start_time[:5]
            )

            if (
                slot_time
                in candidates
            ):

                matches.append(
                    slot
                )

        # ----------------------------------------------------
        # No match
        # ----------------------------------------------------

        if not matches:

            available_times = [
                slot.start_time[:5]
                for slot
                in state.recent_slots
            ]

            state.stage = (
                "awaiting_reschedule_time"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "الساعة دي مش متاحة. "
                        "المواعيد المتاحة هي: "
                        + "، ".join(
                            available_times
                        )
                        + ". تحبي أنهي ميعاد؟"
                    ),

                    en=(
                        "That time isn't available. "
                        "Available times are: "
                        + ", ".join(
                            available_times
                        )
                        + ". Which one would you like?"
                    ),
                ),

                response_type=(
                    "reschedule_time_not_available"
                ),
            )

        # ----------------------------------------------------
        # Ambiguous
        # ----------------------------------------------------

        if len(matches) > 1:

            matching_times = [
                slot.start_time[:5]
                for slot
                in matches
            ]

            state.stage = (
                "awaiting_reschedule_time"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "لقيت أكتر من ميعاد ممكن "
                        "يقصدهم الوقت ده: "
                        + "، ".join(
                            matching_times
                        )
                        + ". تقصدي أنهي واحد؟"
                    ),

                    en=(
                        "I found more than one matching "
                        "time: "
                        + ", ".join(
                            matching_times
                        )
                        + ". Which one do you mean?"
                    ),
                ),

                response_type=(
                    "ambiguous_reschedule_time"
                ),
            )

        # ----------------------------------------------------
        # Exactly one trusted target slot
        # ----------------------------------------------------

        selected_slot = (
            matches[0]
        )

        selected_slot_id = str(
            selected_slot.id
        )

        # ----------------------------------------------------
        # Defensive protection:
        #
        # Never "reschedule" to the same slot.
        # ----------------------------------------------------

        if (
            selected_slot_id
            == state.slot_id
        ):

            state.stage = (
                "awaiting_reschedule_time"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "ده نفس ميعاد الحجز الحالي. "
                        "اختاري ميعاد مختلف."
                    ),

                    en=(
                        "That is already your current "
                        "appointment time. Please choose "
                        "a different slot."
                    ),
                ),

                response_type=(
                    "same_reschedule_slot"
                ),
            )

        state.new_slot_id = (
            selected_slot_id
        )

        state.new_slot_date = (
            selected_slot.slot_date
        )

        state.new_slot_time = (
            selected_slot
            .start_time[:5]
        )

        state.pending_operation_entities.pop(
            "date_text",
            None,
        )

        state.pending_operation_entities.pop(
            "time_text",
            None,
        )

        return self._prepare_confirmation(
            state=state,
        )

    # ========================================================
    # PREPARE CONFIRMATION
    # ========================================================

    def _prepare_confirmation(
        self,
        *,
        state: SessionState,
    ) -> WorkflowResult:

        required = {
            "appointment_reference":
                state.appointment_reference,

            "national_id":
                state.national_id,

            "doctor_id":
                state.doctor_id,

            "old_slot_id":
                state.slot_id,

            "old_date":
                state.slot_date,

            "old_time":
                state.slot_time,

            "new_slot_id":
                state.new_slot_id,

            "new_date":
                state.new_slot_date,

            "new_time":
                state.new_slot_time,
        }

        missing = [
            key
            for key, value
            in required.items()
            if not value
        ]

        if missing:

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "فيه بيانات ناقصة قبل "
                        "تأكيد تغيير الميعاد."
                    ),

                    en=(
                        "Some information is missing "
                        "before confirming the reschedule."
                    ),
                ),

                response_type=(
                    "reschedule_data_incomplete"
                ),

                data={
                    "missing":
                        missing,
                },
            )

        state.stage = (
            "awaiting_reschedule_confirmation"
        )

        state.awaiting_confirmation = (
            True
        )

        state.pending_action = (
            "reschedule_booking"
        )

        if state.language == "en":

            reply = (
                "Please review the appointment change:\n\n"
                f"Doctor: {state.doctor_name}\n"
                f"Current date: {state.slot_date}\n"
                f"Current time: {state.slot_time}\n\n"
                f"New date: {state.new_slot_date}\n"
                f"New time: {state.new_slot_time}\n\n"
                "Would you like me to confirm the change?"
            )

        else:

            reply = (
                "راجعي تغيير الميعاد:\n\n"
                f"الدكتور: {state.doctor_name}\n"
                f"المعاد الحالي: "
                f"{state.slot_date} الساعة "
                f"{state.slot_time}\n\n"
                f"المعاد الجديد: "
                f"{state.new_slot_date} الساعة "
                f"{state.new_slot_time}\n\n"
                "أأكد تغيير الميعاد؟"
            )

        return WorkflowResult(
            reply=reply,

            response_type=(
                "reschedule_confirmation"
            ),

            data={
                "appointment_reference":
                    state.appointment_reference,

                "old_slot_id":
                    state.slot_id,

                "old_date":
                    state.slot_date,

                "old_time":
                    state.slot_time,

                "new_slot_id":
                    state.new_slot_id,

                "new_date":
                    state.new_slot_date,

                "new_time":
                    state.new_slot_time,
            },
        )

    # ========================================================
    # CONFIRM RESCHEDULE
    # ========================================================

    async def _handle_confirmation(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        # ----------------------------------------------------
        # NOTE
        #
        # Date/time corrections have already been intercepted
        # by _reconcile_current_turn() BEFORE this method.
        #
        # So:
        #
        # "لا، الخميس"
        #
        # changes the date.
        #
        # But:
        #
        # "لا"
        #
        # declines the operation.
        # ----------------------------------------------------

        # ----------------------------------------------------
        # DENY
        # ----------------------------------------------------

        if (
            nlu.intent
            == "deny_action"

            or

            nlu.confirmation
            == "no"
        ):

            state.awaiting_confirmation = (
                False
            )

            state.pending_action = None

            state.stage = (
                "reschedule_declined"
            )

            state.new_slot_id = None
            state.new_slot_date = None
            state.new_slot_time = None

            state.recent_slots = []

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "تمام، مش هغير ميعاد الحجز."
                    ),

                    en=(
                        "Okay, I won't change "
                        "the appointment time."
                    ),
                ),

                response_type=(
                    "reschedule_not_confirmed"
                ),
            )

        # ----------------------------------------------------
        # Not confirmation
        # ----------------------------------------------------

        if not (
            nlu.intent
            == "confirm_action"

            or

            nlu.confirmation
            == "yes"
        ):

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "أأكد تغيير الميعاد؟ "
                        "قولي أيوه أو لأ."
                    ),

                    en=(
                        "Would you like me to confirm "
                        "the reschedule? Please answer "
                        "yes or no."
                    ),
                ),

                response_type=(
                    "ask_reschedule_confirmation"
                ),
            )

        # ----------------------------------------------------
        # Safety gate
        # ----------------------------------------------------

        if (
            not state.awaiting_confirmation

            or

            state.pending_action
            != "reschedule_booking"
        ):

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "مفيش تغيير ميعاد جاهز "
                        "للتأكيد حالياً."
                    ),

                    en=(
                        "There is no reschedule "
                        "ready for confirmation."
                    ),
                ),

                response_type=(
                    "no_pending_reschedule"
                ),
            )

        required = {
            "national_id":
                state.national_id,

            "appointment_reference":
                state.appointment_reference,

            "new_slot_id":
                state.new_slot_id,
        }

        missing = [
            key
            for key, value
            in required.items()
            if not value
        ]

        if missing:

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "فيه بيانات ناقصة ومينفعش "
                        "أنفذ تغيير الميعاد."
                    ),

                    en=(
                        "Some required information is "
                        "missing, so the appointment "
                        "cannot be rescheduled."
                    ),
                ),

                response_type=(
                    "reschedule_data_incomplete"
                ),

                data={
                    "missing":
                        missing,
                },
            )

        # ----------------------------------------------------
        # Save old values before write
        # ----------------------------------------------------

        old_slot_id = (
            state.slot_id
        )

        old_date = (
            state.slot_date
        )

        old_time = (
            state.slot_time
        )

        requested_new_slot_id = (
            state.new_slot_id
        )

        # ----------------------------------------------------
        # Python-owned idempotency key
        # ----------------------------------------------------

        idempotency_key = str(
            uuid4()
        )

        # ----------------------------------------------------
        # Execute through MCP -> Backend
        # ----------------------------------------------------

        result = await self.tools.call(
            "reschedule_booking",

            national_id=(
                state.national_id
            ),

            appointment_reference=(
                state.appointment_reference
            ),

            new_slot_id=(
                requested_new_slot_id
            ),

            idempotency_key=(
                idempotency_key
            ),
        )

        if not isinstance(
            result,
            dict,
        ):

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "النظام مأكّدش تغيير الميعاد، "
                        "فمش هعتبره اتغير."
                    ),

                    en=(
                        "The system did not confirm "
                        "the reschedule, so I won't "
                        "mark it as completed."
                    ),
                ),

                response_type=(
                    "reschedule_unconfirmed"
                ),

                data={
                    "backend_result":
                        result,
                },
            )

        backend_reference = (
            result.get(
                "appointment_reference"
            )
        )

        backend_new_slot_id = (
            result.get(
                "new_slot_id"
            )
        )

        backend_status = (
            result.get(
                "status"
            )
        )

        # ----------------------------------------------------
        # Backend must clearly confirm the write
        # ----------------------------------------------------

        if (
            not backend_reference

            or

            not backend_new_slot_id

            or

            backend_status
            != "confirmed"
        ):

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "النظام مرجعش تأكيد واضح "
                        "لتغيير الميعاد، فمش هعتبره تم."
                    ),

                    en=(
                        "The backend did not return "
                        "a clear reschedule confirmation, "
                        "so I won't mark it as completed."
                    ),
                ),

                response_type=(
                    "reschedule_unconfirmed"
                ),

                data={
                    "backend_result":
                        result,
                },
            )

        if (
            str(
                backend_new_slot_id
            )
            !=
            str(
                requested_new_slot_id
            )
        ):

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "النظام رجع ميعاد مختلف "
                        "عن الميعاد المطلوب، "
                        "فمش هعتبر العملية مؤكدة."
                    ),

                    en=(
                        "The backend returned a different "
                        "slot than the requested one, "
                        "so I won't mark the operation "
                        "as confirmed."
                    ),
                ),

                response_type=(
                    "reschedule_slot_mismatch"
                ),

                data={
                    "backend_result":
                        result,
                },
            )

        # ====================================================
        # SUCCESS
        #
        # Current appointment now becomes the new slot.
        # ====================================================

        state.appointment_reference = (
            str(
                backend_reference
            )
        )

        state.slot_id = str(
            backend_new_slot_id
        )

        state.slot_date = str(
            result.get(
                "scheduled_date"
            )
            or
            state.new_slot_date
        )

        state.slot_time = str(
            result.get(
                "start_time"
            )
            or
            state.new_slot_time
            or
            ""
        )[:5]

        state.new_slot_id = None
        state.new_slot_date = None
        state.new_slot_time = None

        state.awaiting_confirmation = (
            False
        )

        state.pending_action = None
        state.candidate_appointments = []

        state.stage = (
            "reschedule_completed"
        )

        state.recent_slots = []

        return WorkflowResult(
            reply=self._message(
                state.language,

                ar=(
                    "تم تغيير ميعاد الحجز بنجاح. "
                    f"المعاد الجديد: "
                    f"{state.slot_date} الساعة "
                    f"{state.slot_time}."
                ),

                en=(
                    "The appointment was rescheduled "
                    "successfully. New appointment: "
                    f"{state.slot_date} at "
                    f"{state.slot_time}."
                ),
            ),

            response_type=(
                "booking_rescheduled"
            ),

            data={
                "appointment_reference":
                    state.appointment_reference,

                "old_slot_id":
                    old_slot_id,

                "old_date":
                    old_date,

                "old_time":
                    old_time,

                "new_slot_id":
                    state.slot_id,

                "new_date":
                    state.slot_date,

                "new_time":
                    state.slot_time,

                "backend_result":
                    result,
            },
        )

    # ========================================================
    # LANGUAGE
    # ========================================================

    @staticmethod
    def _message(
        language: str,
        *,
        ar: str,
        en: str,
    ) -> str:

        if language == "en":
            return en

        return ar