from __future__ import annotations

from uuid import uuid4

from medmind.core.tool_executor import (
    MCPToolExecutor,
)

from medmind.resolvers.national_id import (
    resolve_national_id,
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

            if (
                state.operation_type
                != "cancel_appointment"
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