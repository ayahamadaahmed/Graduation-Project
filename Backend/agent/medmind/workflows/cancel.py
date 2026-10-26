from __future__ import annotations

from uuid import uuid4

from medmind.core.tool_executor import (
    MCPToolExecutor,
)

from medmind.resolvers.date import (
    resolve_date,
)
from medmind.resolvers.date import (
    resolve_date,
)

from medmind.state.context import (
    remember_pending_operation_entities,
)
from medmind.resolvers.national_id import (
    resolve_national_id,
)

from medmind.resolvers.time import (
    resolve_time_candidates,
)

from medmind.state.context import (
    remember_pending_operation_entities,
)

from medmind.state.models import (
    AppointmentSnapshot,
    SessionState,
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
# CANCEL WORKFLOW
# ============================================================


class CancelWorkflow:

    def __init__(
        self,
        *,
        tools: MCPToolExecutor,
    ) -> None:

        self.tools = tools

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

    @classmethod
    def _filter_contextual_bookings(
        cls,
        *,
        state: SessionState,
        appointments: list[
            AppointmentSnapshot
        ],
    ) -> list[AppointmentSnapshot] | None:

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

        date_text = pending.get(
            "date_text"
        )

        time_text = pending.get(
            "time_text"
        )

        # None means:
        # user did not provide any booking-selection clue.
        if not any(
            (
                doctor_name,
                specialty_name,
                service_name,
                date_text,
                time_text,
            )
        ):
            return None

        matches = list(
            appointments
        )

        def narrow_by_name(
            rows,
            *,
            requested,
            attribute,
        ):

            if not requested:
                return rows

            query = cls._normalize_selection_text(
                requested
            )

            narrowed = []

            for row in rows:

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
                        query == candidate_normalized
                        or
                        query in candidate_normalized
                        or
                        candidate_normalized in query
                    )
                ):
                    narrowed.append(
                        row
                    )

            return narrowed

        matches = narrow_by_name(
            matches,
            requested=doctor_name,
            attribute="doctor_name",
        )

        if not matches:
            return []

        matches = narrow_by_name(
            matches,
            requested=specialty_name,
            attribute="specialty_name",
        )

        if not matches:
            return []

        matches = narrow_by_name(
            matches,
            requested=service_name,
            attribute="service_name",
        )

        if not matches:
            return []

        if date_text:

            resolved = resolve_date(
                date_text
            )

            if resolved is not None:

                requested_date = (
                    resolved.isoformat()
                )

                matches = [
                    row
                    for row in matches
                    if str(
                        row.scheduled_date
                        or ""
                    )[:10]
                    == requested_date
                ]

                if not matches:
                    return []

        if time_text:

            time_candidates = (
                resolve_time_candidates(
                    time_text
                )
            )

            if time_candidates:

                matches = [
                    row
                    for row in matches
                    if str(
                        row.start_time
                        or ""
                    )[:5]
                    in time_candidates
                ]

                if not matches:
                    return []

        return matches


    @classmethod
    def _resolve_contextual_booking(
        cls,
        *,
        state: SessionState,
        appointments: list[
            AppointmentSnapshot
        ],
    ) -> AppointmentSnapshot | None:

        matches = (
            cls._filter_contextual_bookings(
                state=state,
                appointments=appointments,
            )
        )

        if (
            matches is not None
            and len(matches) == 1
        ):
            return matches[0]

        return None

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

        for prefix in (
            "الدكتور ",
            "دكتور ",
            "د. ",
            "dr. ",
            "dr ",
        ):

            if normalized.startswith(
                prefix
            ):

                normalized = (
                    normalized[
                        len(prefix):
                    ]
                    .strip()
                )

        return normalized


    @classmethod
    def _selection_text_matches(
        cls,
        query: str | None,
        candidate: str | None,
    ) -> bool:

        query_value = (
            cls._normalize_selection_text(
                query
            )
        )

        candidate_value = (
            cls._normalize_selection_text(
                candidate
            )
        )

        if (
            not query_value
            or
            not candidate_value
        ):

            return False

        return (
            query_value
            == candidate_value
            or
            query_value
            in candidate_value
            or
            candidate_value
            in query_value
        )


    @classmethod
    def _filter_booking_candidates(
        cls,
        *,
        candidates: list[
            AppointmentSnapshot
        ],
        nlu: NLUResult,
    ) -> list[
        AppointmentSnapshot
    ]:

        entities = (
            nlu.entities
        )

        filtered = list(
            candidates
        )

        # ========================================================
        # DOCTOR
        # ========================================================

        if entities.doctor_name:

            filtered = [
                item
                for item
                in filtered
                if cls._selection_text_matches(
                    entities.doctor_name,
                    item.doctor_name,
                )
            ]

        # ========================================================
        # SPECIALTY
        # ========================================================

        if entities.specialty_name:

            filtered = [
                item
                for item
                in filtered
                if cls._selection_text_matches(
                    entities.specialty_name,
                    item.specialty_name,
                )
            ]

        # ========================================================
        # SERVICE
        # ========================================================

        if entities.service_name:

            filtered = [
                item
                for item
                in filtered
                if cls._selection_text_matches(
                    entities.service_name,
                    item.service_name,
                )
            ]

        # ========================================================
        # DATE
        # ========================================================

        if entities.date_text:

            requested_date = (
                resolve_date(
                    entities.date_text
                )
            )

            if requested_date is not None:

                requested_iso = (
                    requested_date.isoformat()
                )

                filtered = [
                    item
                    for item
                    in filtered
                    if (
                        item.scheduled_date
                        == requested_iso
                    )
                ]

        # ========================================================
        # TIME
        # ========================================================

        if entities.time_text:

            requested_times = (
                resolve_time_candidates(
                    entities.time_text
                )
            )

            if requested_times:

                filtered = [
                    item
                    for item
                    in filtered
                    if (
                        str(
                            item.start_time
                            or ""
                        )[:5]
                        in requested_times
                    )
                ]

        return filtered


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

        is_cancel_request = (
            nlu.intent == "cancel_appointment"
            or
            nlu.operation_type == "cancel_appointment"
        )

        # ----------------------------------------------------
        # Start cancel operation
        # ----------------------------------------------------

        if is_cancel_request:

            # A finished cancellation followed by a new cancel request
            # starts a new operation (and so needs a fresh national ID).
            if (
                state.operation_type
                != "cancel_appointment"
                or state.stage == "cancel_completed"
            ):

                # Keep an existing internal reference when
                # available.
                #
                # This can be useful for chat or an operation
                # transition, but the voice user never needs
                # to pronounce the reference.
                previous_reference = (
                    nlu.entities.appointment_reference
                    or state.appointment_reference
                )

                state.reset_operation(
                    preserve_patient=True,
                )

                # Fresh identity per sensitive operation.
                state.forget_identity_proof()

                state.operation_type = (
                    "cancel_appointment"
                )

                state.stage = "new"

                if previous_reference:

                    state.appointment_reference = (
                        previous_reference
                        .strip()
                        .upper()
                    )

        # ----------------------------------------------------
        # Preserve non-sensitive operation entities.
        #
        # Example:
        # "الغي حجز دكتور ماهر بكرة"
        # -> doctor/date survive the national-ID turn.
        # ----------------------------------------------------

        if (
            state.operation_type
            == "cancel_appointment"
        ):

            remember_pending_operation_entities(
                state=state,
                nlu=nlu,
            )

        remember_pending_operation_entities(
            state=state,
            nlu=nlu,
        )    

        # ----------------------------------------------------
        # This workflow owns cancellation only
        # ----------------------------------------------------

        if (
            state.operation_type
            != "cancel_appointment"
        ):

            return WorkflowResult(
                handled=False,
                reply="",
                response_type="not_cancel",
            )

        # ----------------------------------------------------
        # Stage routing
        # ----------------------------------------------------

        if state.stage == "new":

            return await self._handle_new(
                state=state,
                nlu=nlu,
            )

        if (
            state.stage
            == "awaiting_cancel_national_id"
        ):

            return await self._handle_national_id(
                state=state,
                nlu=nlu,
            )

        if (
            state.stage
            == "awaiting_cancel_booking_selection"
        ):

            return await self._handle_booking_selection(
                state=state,
                nlu=nlu,
                user_message=user_message,
            )

        # Compatibility fallback for text/chat channels.
        #
        # Normal voice flow should NOT enter this stage.
        if (
            state.stage
            == "awaiting_appointment_reference"
        ):

            return await self._handle_reference(
                state=state,
                nlu=nlu,
            )

        if (
            state.stage
            == "awaiting_cancel_confirmation"
        ):

            return await self._handle_confirmation(
                state=state,
                nlu=nlu,
            )

        return WorkflowResult(
            reply=self._message(
                state.language,
                ar=(
                    "لسه بنجهز المرحلة دي "
                    "من إلغاء الحجز."
                ),
                en=(
                    "This cancellation stage "
                    "is still being implemented."
                ),
            ),
            response_type=(
                "cancel_stage_not_implemented"
            ),
        )

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
        # Use National ID from current turn if provided
        # ----------------------------------------------------

        national_id_text = (
            nlu.entities.national_id
        )

        if (
            not state.national_id
            and national_id_text
        ):

            return await self._handle_national_id(
                state=state,
                nlu=nlu,
            )

        # ----------------------------------------------------
        # Identity not known
        # ----------------------------------------------------

        if not state.national_id:

            state.stage = (
                "awaiting_cancel_national_id"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,
                    ar=(
                        "تمام. ممكن الرقم القومي "
                        "عشان أجيب حجوزاتك؟"
                    ),
                    en=(
                        "Sure. Please provide the "
                        "national ID so I can find "
                        "your appointments."
                    ),
                ),
                response_type=(
                    "ask_cancel_national_id"
                ),
            )

        # ----------------------------------------------------
        # Optional internal/text reference
        # ----------------------------------------------------

        reference = (
            nlu.entities.appointment_reference
            or state.appointment_reference
        )

        if reference:

            state.appointment_reference = (
                reference
                .strip()
                .upper()
            )

            return await self._lookup_booking(
                state=state,
            )

        # ----------------------------------------------------
        # Voice-friendly flow
        #
        # National ID
        # -> Search patient's bookings
        # -> Let user choose naturally
        # ----------------------------------------------------

        return await self._load_booking_candidates(
            state=state,
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
            nlu.entities.national_id
        )

        if not national_id_text:

            state.stage = (
                "awaiting_cancel_national_id"
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
                    "ask_cancel_national_id"
                ),
            )

        national_id = (
            resolve_national_id(
                national_id_text
            )
        )

        if national_id is None:

            state.stage = (
                "awaiting_cancel_national_id"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,
                    ar=(
                        "الرقم القومي لازم يكون "
                        "14 رقم. ممكن تقوله تاني؟"
                    ),
                    en=(
                        "The national ID must contain "
                        "14 digits. Please say it again."
                    ),
                ),
                response_type=(
                    "invalid_national_id"
                ),
            )

        state.national_id = (
            national_id
        )

        # ----------------------------------------------------
        # Optional internal/text reference
        # ----------------------------------------------------

        reference = (
            nlu.entities.appointment_reference
            or state.appointment_reference
        )

        if reference:

            state.appointment_reference = (
                reference
                .strip()
                .upper()
            )

            return await self._lookup_booking(
                state=state,
            )

        # ----------------------------------------------------
        # Voice-friendly booking discovery
        # ----------------------------------------------------

        return await self._load_booking_candidates(
            state=state,
        )

    # ========================================================
    # APPOINTMENT REFERENCE
    #
    # Compatibility fallback only.
    # Normal voice flow should not need this.
    # ========================================================

    async def _handle_reference(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        reference = (
            nlu.entities.appointment_reference
        )

        if not reference:

            return WorkflowResult(
                reply=self._message(
                    state.language,
                    ar=(
                        "ممكن تبعتي رقم الحجز؟"
                    ),
                    en=(
                        "Please provide the booking "
                        "reference."
                    ),
                ),
                response_type=(
                    "ask_appointment_reference"
                ),
            )

        state.appointment_reference = (
            reference
            .strip()
            .upper()
        )

        return await self._lookup_booking(
            state=state,
        )

    # ========================================================
    # LOAD PATIENT BOOKINGS
    # ========================================================

    async def _load_booking_candidates(
        self,
        *,
        state: SessionState,
    ) -> WorkflowResult:

        if not state.national_id:

            state.stage = (
                "awaiting_cancel_national_id"
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
                    "ask_cancel_national_id"
                ),
            )

        # Clear any stale internal reference before
        # searching the patient's current bookings.
        state.appointment_reference = None

        try:

            appointments = await (
                search_patient_appointments(
                    tools=self.tools,
                    national_id=(
                        state.national_id
                    ),
                    action="cancel",
                    limit=5,
                )
            )

        except RuntimeError:

            state.candidate_appointments = []

            # Keep the operation alive.
            # Caller can try again without restarting.
            state.stage = (
                "awaiting_cancel_booking_selection"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,
                    ar=(
                        "مقدرتش أجيب حجوزاتك "
                        "دلوقتي. ممكن نجرب تاني؟"
                    ),
                    en=(
                        "I couldn't retrieve your "
                        "appointments right now. "
                        "Would you like to try again?"
                    ),
                ),
                response_type=(
                    "cancel_search_failed"
                ),
            )

        state.candidate_appointments = (
            appointments
        )

        # ----------------------------------------------------
        # No active appointments
        # ----------------------------------------------------

        if not appointments:

            state.stage = (
                "cancel_not_found"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,
                    ar=(
                        "ملقتش عندك حجوزات حالية "
                        "ينفع تتلغي."
                    ),
                    en=(
                        "I couldn't find any active "
                        "appointments to cancel."
                    ),
                ),
                response_type=(
                    "cancel_no_active_bookings"
                ),
            )

        contextual_matches = (
            self._filter_contextual_bookings(
                state=state,
                appointments=appointments,
            )
        )

        if contextual_matches is not None:

            # User supplied a doctor/date/time clue,
            # but it matched no future booking.
            if not contextual_matches:

                state.stage = (
                    "awaiting_cancel_booking_selection"
                )

                # Keep the original future candidates
                # available for a later selection.
                state.candidate_appointments = (
                    appointments
                )

                return WorkflowResult(
                    reply=self._message(
                        state.language,
                        ar=(
                            "ملقتش حجز مطابق "
                            "للتفاصيل دي. "
                            "ممكن تقولي اليوم أو "
                            "الدكتور تاني؟"
                        ),
                        en=(
                            "I couldn't find an appointment "
                            "matching those details. "
                            "Please tell me the day or "
                            "doctor again."
                        ),
                    ),
                    response_type=(
                        "cancel_context_no_match"
                    ),
                )

            # Important:
            # from here onward we only expose the
            # bookings matching the user's clue.
            appointments = (
                contextual_matches
            )

            state.candidate_appointments = (
                appointments
            )

        # ----------------------------------------------------
        # Contextual appointment selection
        #
        # Only auto-select when the supplied doctor/service/date
        # context resolves to exactly ONE trusted appointment.
        # Explicit cancellation confirmation is still required
        # before the write.
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

            return await self._lookup_booking(
                state=state,
            )

        # ----------------------------------------------------
        # Ask user to select appointment
        # ----------------------------------------------------

        state.stage = (
            "awaiting_cancel_booking_selection"
        )

        return WorkflowResult(
            reply=build_selection_prompt(
                appointments,
                language=state.language,
                action="cancel",
            ),
            response_type=(
                "ask_cancel_booking_selection"
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

        # ----------------------------------------------------
        # Optional explicit reference for text/chat
        # ----------------------------------------------------

        reference = (
            nlu.entities.appointment_reference
        )

        if reference:

            state.appointment_reference = (
                reference
                .strip()
                .upper()
            )

            state.candidate_appointments = []

            return await self._lookup_booking(
                state=state,
            )

        candidates: list[
            AppointmentSnapshot
        ] = list(
            state.candidate_appointments
        )

        # ----------------------------------------------------
        # Candidate list disappeared/stale
        # ----------------------------------------------------

        if not candidates:

            return await self._load_booking_candidates(
                state=state,
            )

        # ========================================================
        # STRUCTURED CONTEXTUAL SELECTION
        # ========================================================

        has_selection_entities = any(
            (
                nlu.entities.doctor_name,
                nlu.entities.specialty_name,
                nlu.entities.service_name,
                nlu.entities.date_text,
                nlu.entities.time_text,
            )
        )

        if has_selection_entities:

            filtered_candidates = (
                self._filter_booking_candidates(
                    candidates=candidates,
                    nlu=nlu,
                )
            )

            # Exactly one booking identified.
            if len(
                filtered_candidates
            ) == 1:

                selected = (
                    filtered_candidates[0]
                )

                state.appointment_reference = (
                    selected
                    .appointment_reference
                    .strip()
                    .upper()
                )

                state.candidate_appointments = []

                return await (
                    self._lookup_booking(
                        state=state,
                    )
                )

            # More than one still matches:
            # narrow the candidate list instead of throwing away
            # the information the user supplied.
            if len(
                filtered_candidates
            ) > 1:

                state.candidate_appointments = (
                    filtered_candidates
                )

                return WorkflowResult(
                    reply=build_selection_prompt(
                        filtered_candidates,
                        language=
                            state.language,
                        action=
                            "cancel",
                    ),
                    response_type=(
                        "ask_cancel_booking_selection"
                    ),
                    data={
                        "appointment_count":
                            len(
                                filtered_candidates
                            ),
                    },
                )
        # ----------------------------------------------------
        # User declines the selection
        # ----------------------------------------------------

        denied = (
            nlu.intent == "deny_action"
            or
            nlu.confirmation == "no"
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
                "cancel_declined"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,
                    ar=(
                        "تمام، مش هلغي أي حجز."
                    ),
                    en=(
                        "Okay, I won't cancel "
                        "any appointment."
                    ),
                ),
                response_type=(
                    "cancel_selection_declined"
                ),
            )

        # ----------------------------------------------------
        # One booking + explicit confirmation
        # ----------------------------------------------------

        if (
            len(candidates) == 1
            and (
                nlu.intent == "confirm_action"
                or
                nlu.confirmation == "yes"
            )
        ):

            selected_index = 0

        else:

            # Handles:
            #
            # "الأول"
            # "التاني"
            # "حجز الجلدية"
            # "بتاع دكتور ماهر"
            selected_index = (
                resolve_appointment_selection(
                    user_message,
                    candidates,
                )
            )

        # ----------------------------------------------------
        # Couldn't determine booking
        # ----------------------------------------------------

        if selected_index is None:

            state.stage = (
                "awaiting_cancel_booking_selection"
            )

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
                    "ask_cancel_booking_selection"
                ),
            )

        # ----------------------------------------------------
        # Store INTERNAL appointment reference
        # ----------------------------------------------------

        selected = (
            candidates[
                selected_index
            ]
        )

        state.appointment_reference = (
            selected.appointment_reference
            .strip()
            .upper()
        )

        state.candidate_appointments = []

        return await self._lookup_booking(
            state=state,
        )

    # ========================================================
    # LOOKUP BOOKING
    # ========================================================

    async def _lookup_booking(
        self,
        *,
        state: SessionState,
    ) -> WorkflowResult:

        # ----------------------------------------------------
        # National ID missing
        # ----------------------------------------------------

        if not state.national_id:

            state.appointment_reference = None
            state.candidate_appointments = []

            state.stage = (
                "awaiting_cancel_national_id"
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
                    "ask_cancel_national_id"
                ),
            )

        # ----------------------------------------------------
        # Internal reference missing
        #
        # Reload bookings. Do NOT ask voice user for APT-...
        # ----------------------------------------------------

        if not state.appointment_reference:

            return await self._load_booking_candidates(
                state=state,
            )

        # ----------------------------------------------------
        # Backend lookup
        # ----------------------------------------------------

        result = await self.tools.call(
            "lookup_booking",
            national_id=(
                state.national_id
            ),
            appointment_reference=(
                state.appointment_reference
            ),
        )

        # ----------------------------------------------------
        # Lookup failed
        #
        # IMPORTANT:
        # appointment_reference is internal.
        # Never ask the caller to pronounce it.
        # ----------------------------------------------------

        if not isinstance(
            result,
            dict,
        ):

            state.appointment_reference = None
            state.candidate_appointments = []

            return await self._load_booking_candidates(
                state=state,
            )

        backend_reference = (
            result.get(
                "appointment_reference"
            )
        )

        if not backend_reference:

            state.appointment_reference = None
            state.candidate_appointments = []

            return await self._load_booking_candidates(
                state=state,
            )

        # ----------------------------------------------------
        # Verified booking
        # ----------------------------------------------------

        state.appointment_reference = (
            str(
                backend_reference
            )
            .strip()
            .upper()
        )

        state.candidate_appointments = []

        status = str(
            result.get(
                "status"
            )
            or ""
        ).strip().lower()

        # ----------------------------------------------------
        # Already cancelled
        # ----------------------------------------------------

        if status == "cancelled":

            state.awaiting_confirmation = (
                False
            )

            state.pending_action = None

            state.stage = (
                "cancel_already_completed"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,
                    ar=(
                        "الحجز ده ملغي بالفعل."
                    ),
                    en=(
                        "This booking is already "
                        "cancelled."
                    ),
                ),
                response_type=(
                    "booking_already_cancelled"
                ),
                data={
                    "booking":
                        result,
                },
            )

        # ----------------------------------------------------
        # Prepare explicit cancellation confirmation
        # ----------------------------------------------------

        state.stage = (
            "awaiting_cancel_confirmation"
        )

        state.awaiting_confirmation = (
            True
        )

        state.pending_action = (
            "cancel_booking"
        )

        doctor_name = (
            result.get(
                "doctor_name"
            )
            or "-"
        )

        service_name = (
            result.get(
                "service_name"
            )
            or "-"
        )

        scheduled_date = (
            result.get(
                "scheduled_date"
            )
            or "-"
        )

        start_time = (
            result.get(
                "start_time"
            )
            or "-"
        )

        start_time = str(
            start_time
        )[:5]

        # ----------------------------------------------------
        # Do NOT read booking reference aloud.
        # ----------------------------------------------------

        if state.language == "en":

            reply = (
                "Please review the appointment "
                "before cancellation:\n\n"
                f"Doctor: {doctor_name}\n"
                f"Service: {service_name}\n"
                f"Date: {scheduled_date}\n"
                f"Time: {start_time}\n\n"
                "Would you like me to cancel it?"
            )

        else:

            reply = (
                "راجعي بيانات الحجز قبل الإلغاء:\n\n"
                f"الدكتور: {doctor_name}\n"
                f"الخدمة: {service_name}\n"
                f"التاريخ: {scheduled_date}\n"
                f"الساعة: {start_time}\n\n"
                "أأكد إلغاء الحجز؟"
            )

        return WorkflowResult(
            reply=reply,
            response_type=(
                "cancel_confirmation"
            ),
            data={
                "booking":
                    result,
            },
        )

    # ========================================================
    # CONFIRM CANCELLATION
    # ========================================================

    async def _handle_confirmation(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        # ----------------------------------------------------
        # DENY
        # ----------------------------------------------------

        if (
            nlu.intent == "deny_action"
            or
            nlu.confirmation == "no"
        ):

            state.awaiting_confirmation = (
                False
            )

            state.pending_action = None

            state.candidate_appointments = []

            state.stage = (
                "cancel_declined"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,
                    ar=(
                        "تمام، مش هلغي الحجز."
                    ),
                    en=(
                        "Okay, I won't cancel "
                        "the booking."
                    ),
                ),
                response_type=(
                    "cancel_not_confirmed"
                ),
            )

        # ----------------------------------------------------
        # NOT A CONFIRMATION
        # ----------------------------------------------------

        if not (
            nlu.intent == "confirm_action"
            or
            nlu.confirmation == "yes"
        ):

            return WorkflowResult(
                reply=self._message(
                    state.language,
                    ar=(
                        "أأكد إلغاء الحجز؟ "
                        "قولي أيوه أو لأ."
                    ),
                    en=(
                        "Would you like me to cancel "
                        "the booking? Please answer "
                        "yes or no."
                    ),
                ),
                response_type=(
                    "ask_cancel_confirmation"
                ),
            )

        # ----------------------------------------------------
        # SAFETY GATE
        # ----------------------------------------------------

        if (
            not state.awaiting_confirmation
            or
            state.pending_action
            != "cancel_booking"
        ):

            return WorkflowResult(
                reply=self._message(
                    state.language,
                    ar=(
                        "مفيش إلغاء حجز جاهز "
                        "للتأكيد حالياً."
                    ),
                    en=(
                        "There is no cancellation "
                        "ready for confirmation."
                    ),
                ),
                response_type=(
                    "no_pending_cancellation"
                ),
            )

        if (
            not state.national_id
            or
            not state.appointment_reference
        ):

            return WorkflowResult(
                reply=self._message(
                    state.language,
                    ar=(
                        "فيه بيانات ناقصة "
                        "ومينفعش أنفذ الإلغاء."
                    ),
                    en=(
                        "Some required information "
                        "is missing, so cancellation "
                        "cannot be executed."
                    ),
                ),
                response_type=(
                    "cancel_data_incomplete"
                ),
            )

        # ----------------------------------------------------
        # Python-owned idempotency key
        # ----------------------------------------------------

        idempotency_key = str(
            uuid4()
        )

        # ----------------------------------------------------
        # Actual backend write
        # ----------------------------------------------------

        result = await self.tools.call(
            "cancel_booking",

            national_id=(
                state.national_id
            ),

            appointment_reference=(
                state.appointment_reference
            ),

            idempotency_key=(
                idempotency_key
            ),

            session_reference=(
                state.session_id
            ),
        )

        # ----------------------------------------------------
        # Backend response must be valid
        # ----------------------------------------------------

        if not isinstance(
            result,
            dict,
        ):

            return WorkflowResult(
                reply=self._message(
                    state.language,
                    ar=(
                        "النظام مأكّدش إلغاء الحجز، "
                        "فمش هعتبره اتلغى."
                    ),
                    en=(
                        "The system did not confirm "
                        "the cancellation, so I won't "
                        "mark it as cancelled."
                    ),
                ),
                response_type=(
                    "cancel_unconfirmed"
                ),
                data={
                    "backend_result":
                        result,
                },
            )

        status = str(
            result.get(
                "status"
            )
            or ""
        ).strip().lower()

        # ----------------------------------------------------
        # Only claim success when backend says cancelled
        # ----------------------------------------------------

        if status != "cancelled":

            return WorkflowResult(
                reply=self._message(
                    state.language,
                    ar=(
                        "النظام مرجعش تأكيد "
                        "إن الحجز اتلغى، "
                        "فمش هعتبره ملغي."
                    ),
                    en=(
                        "The backend did not confirm "
                        "that the booking was cancelled, "
                        "so I won't mark it as cancelled."
                    ),
                ),
                response_type=(
                    "cancel_unconfirmed"
                ),
                data={
                    "backend_result":
                        result,
                },
            )

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        state.awaiting_confirmation = (
            False
        )

        state.pending_action = None

        state.candidate_appointments = []

        state.stage = (
            "cancel_completed"
        )

        # IMPORTANT:
        # Keep appointment_reference in internal state/data.
        # Do NOT force the voice caller to hear the long code.
        return WorkflowResult(
            reply=self._message(
                state.language,
                ar=(
                    "تم إلغاء الحجز بنجاح."
                ),
                en=(
                    "The booking was cancelled "
                    "successfully."
                ),
            ),
            response_type=(
                "booking_cancelled"
            ),
            data={
                "appointment_reference":
                    state.appointment_reference,

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