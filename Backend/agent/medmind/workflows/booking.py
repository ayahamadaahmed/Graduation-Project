from __future__ import annotations
from datetime import date
from typing import Any
from uuid import uuid4

import re
import unicodedata


from medmind.core.tool_executor import (
    MCPToolExecutor,
)

from medmind.state.models import (
    SessionState,
)

from medmind.state.context import (
    current_turn_scheduling_fields,
    invalidate_booking_from_field,
    remember_pending_operation_entities,
    resolve_effective_context,
)

from medmind.state.updater import (
    apply_tool_observation,
)

from medmind.understanding.types import (
    NLUResult,
)

from medmind.workflows.types import (
    WorkflowResult,
)

from medmind.resolvers.date import (
    resolve_date,
)

from medmind.resolvers.time import (
    resolve_time_candidates,
)

from medmind.resolvers.national_id import (
    resolve_national_id,
)


# ============================================================
# TEXT NORMALIZATION
# ============================================================

ARABIC_DIACRITICS = re.compile(
    r"[\u0617-\u061A"
    r"\u064B-\u0652"
    r"\u0670"
    r"\u06D6-\u06ED]"
)


def normalize_text(
    value: str | None,
) -> str:

    if not value:
        return ""

    value = unicodedata.normalize(
        "NFKC",
        value,
    )

    value = ARABIC_DIACRITICS.sub(
        "",
        value,
    )

    value = (
        value
        .lower()
        .strip()
    )

    # Arabic normalization
    value = (
        value
        .replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ى", "ي")
        .replace("ة", "ه")
    )

    # Remove simple punctuation
    value = re.sub(
        r"[^\w\u0600-\u06FF\s]",
        " ",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


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

    return [value]


def text_matches(
    query: str,
    candidate: str | None,
) -> bool:

    query_norm = normalize_text(
        query
    )

    candidate_norm = normalize_text(
        candidate
    )

    if (
        not query_norm
        or not candidate_norm
    ):
        return False

    if (
        query_norm
        == candidate_norm
    ):
        return True

    if (
        query_norm
        in candidate_norm
    ):
        return True

    if (
        candidate_norm
        in query_norm
    ):
        return True

    return False


DOCTOR_TITLE_TOKENS = {
    "د",
    "دكتور",
    "دكتوره",
    "الدكتور",
    "الدكتوره",
    "dr",
    "doctor",
}


def normalize_doctor_name(
    value: str | None,
) -> str:

    normalized = normalize_text(value)

    if not normalized:
        return ""

    tokens = normalized.split()

    while (
        tokens
        and tokens[0] in DOCTOR_TITLE_TOKENS
    ):
        tokens.pop(0)

    return " ".join(tokens)

# ============================================================
# BOOKING WORKFLOW
# ============================================================

class BookingWorkflow:

    def __init__(
        self,
        *,
        tools: MCPToolExecutor,
        provider_type: str | None = None,
    ) -> None:

        self.tools = tools

        # Diagnostic labs book by branch + test, without a doctor.
        self.is_lab = (
            (provider_type or "").lower()
            in {"lab", "diagnostic_lab"}
        )

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
        # Detect booking request
        # ----------------------------------------------------

        is_booking_request = (
            nlu.intent == "book_appointment"
            or
            nlu.operation_type == "book_appointment"
        )

        # ----------------------------------------------------
        # Start / restart booking operation
        # ----------------------------------------------------

        if is_booking_request:

            # Booking finished before,
            # and user wants another booking.
            if state.stage in {
                "booking_completed",
                "booking_cancelled_before_create",
            }:

                state.reset_operation(
                    preserve_patient=True,
                )

                state.operation_type = (
                    "book_appointment"
                )

                state.stage = "new"

            # User is starting booking while another
            # operation is active, or there is no operation yet.
            elif (
                state.operation_type
                != "book_appointment"
            ):

                state.reset_operation(
                    preserve_patient=True,
                )

                state.operation_type = (
                    "book_appointment"
                )

                state.stage = "new"
                
        if (
            state.operation_type
            == "book_appointment"
        ):

            remember_pending_operation_entities(
                state=state,
                nlu=nlu,
            )
        # ----------------------------------------------------
        # This workflow owns only booking
        # ----------------------------------------------------

        if (
            state.operation_type
            != "book_appointment"
        ):

            return WorkflowResult(
                handled=False,
                reply="",
                response_type="not_booking",
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
            == "awaiting_confirmation"
        ):

            return await (
                self._handle_confirmation(
                    state=state,
                    nlu=nlu,
                    user_message=user_message,
                )
            )

        if (
            state.stage
            == "awaiting_specialty"
        ):

            return await (
                self._handle_specialty(
                    state=state,
                    nlu=nlu,
                )
            )

        if (
            state.stage
            == "awaiting_doctor"
        ):

            return await (
                self._handle_doctor(
                    state=state,
                    nlu=nlu,
                )
            )

        if (
            state.stage
            == "awaiting_date"
        ):

            return await (
                self._handle_date(
                    state=state,
                    nlu=nlu,
                )
            )

        if (
            state.stage
            == "awaiting_branch"
        ):

            return await (
                self._handle_branch(
                    state=state,
                    nlu=nlu,
                    user_message=user_message,
                )
            )

        if (
            state.stage
            == "awaiting_time"
        ):

            return await (
                self._handle_time(
                    state=state,
                    nlu=nlu,
                )
            )

        if (
            state.stage
            == "awaiting_service"
        ):

            return await (
                self._handle_service(
                    state=state,
                    nlu=nlu,
                )
            )

        if (
            state.stage
            == "awaiting_national_id"
        ):

            return await (
                self._handle_national_id(
                    state=state,
                    nlu=nlu,
                )
            )

        if (
            state.stage
            == "awaiting_patient_name"
        ):

            return await (
                self._handle_patient_name(
                    state=state,
                    nlu=nlu,
                )
            )

        if (
            state.stage
            == "awaiting_patient_name_correction"
        ):

            return await (
                self._handle_patient_name_correction(
                    state=state,
                    nlu=nlu,
                )
            )    

        if (
            state.stage
            == "awaiting_phone"
        ):

            return await (
                self._handle_phone(
                    state=state,
                    nlu=nlu,
                )
            )

        if (
            state.stage
            == "awaiting_phone_confirmation"
        ):

            return await (
                self._handle_phone_confirmation(
                    state=state,
                    nlu=nlu,
                )
            )

        return WorkflowResult(
            reply=self._message(
                state.language,

                ar=(
                    "لسه بنجهز المرحلة دي "
                    "من الحجز."
                ),

                en=(
                    "This booking stage is "
                    "still being implemented."
                ),
            ),

            response_type=
                "stage_not_implemented",
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
        Current user information must never be ignored just
        because the workflow was waiting for another field.

        Dependency order:

            specialty
            doctor
            date
            time
            service

        We may move BACK to an earlier dependency,
        but we never skip a currently missing earlier one.
        """

        stage_rank = {
            "awaiting_specialty":
                1,

            "awaiting_doctor":
                2,

            "awaiting_date":
                3,

            # Lab only: chosen between date and time.
            "awaiting_branch":
                3.5,

            "awaiting_time":
                4,

            "awaiting_service":
                5,
        }

        field_rank = {
            "specialty_name":
                1,

            "doctor_name":
                2,

            "date_text":
                3,

            "time_text":
                4,

            "service_name":
                5,
        }

        current_stage_rank = (
            stage_rank.get(
                state.stage
            )
        )

        # new / identity / phone stages continue through their
        # normal dedicated routing.
        if current_stage_rank is None:

            return None

        supplied_fields = (
            current_turn_scheduling_fields(
                nlu
            )
        )

        if not supplied_fields:

            return None

        eligible_fields = [
            field_name
            for field_name
            in supplied_fields
            if (
                field_rank[
                    field_name
                ]
                <= current_stage_rank
            )
            # Labs have no specialty / doctor step.
            and not (
                self.is_lab
                and field_name in {
                    "specialty_name",
                    "doctor_name",
                }
            )
        ]

        if not eligible_fields:

            return None

        field_name = min(
            eligible_fields,
            key=lambda name: (
                field_rank[
                    name
                ]
            ),
        )

        invalidate_booking_from_field(
            state=state,
            field_name=field_name,
        )

        # ========================================================
        # REROUTE TO THE CORRECT DEPENDENCY
        # ========================================================

        if field_name == "specialty_name":

            state.stage = (
                "awaiting_specialty"
            )

            return await (
                self._handle_specialty(
                    state=state,
                    nlu=nlu,
                )
            )

        if field_name == "doctor_name":

            state.stage = (
                "awaiting_doctor"
            )

            return await (
                self._handle_doctor(
                    state=state,
                    nlu=nlu,
                )
            )

        if field_name == "date_text":

            state.stage = (
                "awaiting_date"
            )

            return await (
                self._handle_date(
                    state=state,
                    nlu=nlu,
                )
            )

        if field_name == "time_text":

            state.stage = (
                "awaiting_time"
            )

            return await (
                self._handle_time(
                    state=state,
                    nlu=nlu,
                )
            )

        if field_name == "service_name":

            state.stage = (
                "awaiting_service"
            )

            return await (
                self._handle_service(
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

        # Labs: no specialty / doctor. Date -> branch -> time -> test.
        if self.is_lab:

            state.stage = (
                "awaiting_date"
            )

            return await (
                self._handle_date(
                    state=state,
                    nlu=nlu,
                )
            )

        context = resolve_effective_context(
            state=state,
            nlu=nlu,
        )

        specialty_name = context.specialty_name
        doctor_name = context.doctor_name

        # ========================================================
        # DOCTOR-FIRST BOOKING
        # ========================================================

        if not specialty_name and doctor_name:

            doctors = await self.tools.call(
                "list_doctors",
            )

            apply_tool_observation(
                state=state,
                tool_name="list_doctors",
                data=doctors,
            )

            doctor = self._find_doctor(
                query=doctor_name,
                state=state,
            )

            if doctor is not None:

                return await (
                    self._select_doctor_and_continue(
                        state=state,
                        doctor=doctor,
                        nlu=nlu,
                    )
                )

        # ========================================================
        # SPECIALTY STILL UNKNOWN
        # ========================================================

        if not specialty_name:

            state.stage = (
                "awaiting_specialty"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "تمام، تحبي تحجزي "
                        "في تخصص إيه؟"
                    ),

                    en=(
                        "Sure. Which specialty "
                        "would you like to book?"
                    ),
                ),

                response_type=
                    "ask_specialty",
            )

        return await (
            self._resolve_specialty(
                state=state,
                specialty_name=
                    specialty_name,
                nlu=nlu,
            )
        )

    # ========================================================
    # SPECIALTY
    # ========================================================

    async def _handle_specialty(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        context = (
            resolve_effective_context(
                state=state,
                nlu=nlu,
            )
        )

        specialty_name = (
            context.specialty_name
        )

        if not specialty_name:

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "ممكن تقولي اسم "
                        "التخصص اللي عايزاه؟"
                    ),

                    en=(
                        "Please tell me the "
                        "specialty you need."
                    ),
                ),

                response_type=
                    "ask_specialty",
            )

        return await (
            self._resolve_specialty(
                state=state,
                specialty_name=
                    specialty_name,
                nlu=nlu,
            )
        )

    # ========================================================
    # RESOLVE SPECIALTY
    # ========================================================

    async def _resolve_specialty(
        self,
        *,
        state: SessionState,
        specialty_name: str,
        nlu: NLUResult,
    ) -> WorkflowResult:

        specialties = await (
            self.tools.call(
                "list_specialties"
            )
        )

        apply_tool_observation(
            state=state,
            tool_name=
                "list_specialties",
            data=specialties,
        )

        specialty = (
            self._find_specialty(
                query=
                    specialty_name,

                specialties=
                    ensure_list(
                        specialties
                    ),
            )
        )

        if specialty is None:

            state.stage = (
                "awaiting_specialty"
            )

            names = []

            for item in ensure_list(
                specialties
            ):

                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                if (
                    state.language
                    == "en"
                ):

                    name = (
                        item.get(
                            "name_en"
                        )
                        or
                        item.get(
                            "name_ar"
                        )
                    )

                else:

                    name = (
                        item.get(
                            "name_ar"
                        )
                        or
                        item.get(
                            "name_en"
                        )
                    )

                if name:

                    names.append(
                        name
                    )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "مش لاقي التخصص ده. "
                        "التخصصات المتاحة: "
                        + "، ".join(
                            names
                        )
                    ),

                    en=(
                        "I couldn't find that "
                        "specialty. Available "
                        "specialties: "
                        + ", ".join(
                            names
                        )
                    ),
                ),

                response_type=
                    "specialty_not_found",

                data={
                    "available_specialties":
                        names,
                },
            )

        # ----------------------------------------------------
        # Save selected specialty
        # ----------------------------------------------------

        state.specialty_id = (
            specialty["id"]
        )

        state.specialty_name = (
            specialty.get(
                "name_ar"
            )
            if state.language != "en"
            else specialty.get(
                "name_en"
            )
        )

        if not state.specialty_name:

            state.specialty_name = (
                specialty.get(
                    "name_en"
                )
                or
                specialty.get(
                    "name_ar"
                )
            )

        # ----------------------------------------------------
        # Load doctors
        # ----------------------------------------------------

        doctors = await (
            self.tools.call(
                "list_doctors",

                specialty_id=
                    state.specialty_id,
            )
        )

        apply_tool_observation(
            state=state,
            tool_name=
                "list_doctors",
            data=doctors,
        )

        doctor_items = (
            ensure_list(
                doctors
            )
        )

        if not doctor_items:

            state.stage = (
                "awaiting_specialty"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "مفيش دكاترة متاحين "
                        "للتخصص ده حالياً. "
                        "تحبي تخصص تاني؟"
                    ),

                    en=(
                        "There are currently no "
                        "doctors available for this "
                        "specialty. Would you like "
                        "another specialty?"
                    ),
                ),

                response_type=
                    "no_doctors",
            )

        context = (
            resolve_effective_context(
                state=state,
                nlu=nlu,
            )
        )

        if context.doctor_name:

            state.stage = (
                "awaiting_doctor"
            )

            return await (
                self._handle_doctor(
                    state=state,
                    nlu=nlu,
                )
            )

        if len(
            state.recent_doctors
        ) == 1:

            return await (
                self._select_doctor_and_continue(
                    state=state,
                    doctor=(
                        state.recent_doctors[0]
                    ),
                    nlu=nlu,
                )
            )

        state.stage = (
            "awaiting_doctor"
        )

        doctor_names = []

        for doctor in (
            state.recent_doctors
        ):

            if (
                state.language
                == "en"
            ):

                name = (
                    doctor.full_name_en
                    or
                    doctor.full_name_ar
                )

            else:

                name = (
                    doctor.full_name_ar
                    or
                    doctor.full_name_en
                )

            if name:

                doctor_names.append(
                    name
                )

        return WorkflowResult(
            reply=self._message(
                state.language,

                ar=(
                    "متاح "
                    + "، ".join(
                        doctor_names
                    )
                    + ". تحبي تحجزي "
                    "مع مين؟"
                ),

                en=(
                    "Available doctors are "
                    + ", ".join(
                        doctor_names
                    )
                    + ". Which doctor would "
                    "you like?"
                ),
            ),

            response_type=
                "ask_doctor",

            data={
                "doctors":
                    doctor_names,
            },
        )

    # ========================================================
    # DOCTOR
    # ========================================================

    async def _handle_doctor(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        context = (
            resolve_effective_context(
                state=state,
                nlu=nlu,
            )
        )

        doctor_name = (
            context.doctor_name
        )

        if not doctor_name:

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "اختاري دكتور من "
                        "الدكاترة المتاحين."
                    ),

                    en=(
                        "Please choose one of "
                        "the available doctors."
                    ),
                ),

                response_type=
                    "ask_doctor",
            )

        doctor = self._find_doctor(
            query=
                doctor_name,

            state=
                state,
        )

        if doctor is None:

            doctor_names = []

            for item in (
                state.recent_doctors
            ):

                if (
                    state.language
                    == "en"
                ):

                    name = (
                        item.full_name_en
                        or
                        item.full_name_ar
                    )

                else:

                    name = (
                        item.full_name_ar
                        or
                        item.full_name_en
                    )

                if name:

                    doctor_names.append(
                        name
                    )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "مش لاقي الدكتور ده "
                        "ضمن الاختيارات. "
                        "المتاح: "
                        + "، ".join(
                            doctor_names
                        )
                    ),

                    en=(
                        "I couldn't match that "
                        "doctor. Available doctors: "
                        + ", ".join(
                            doctor_names
                        )
                    ),
                ),

                response_type=
                    "doctor_not_found",
            )

        return await (
            self._select_doctor_and_continue(
                state=state,
                doctor=doctor,
                nlu=nlu,
            )
        )

    async def _select_doctor_and_continue(
        self,
        *,
        state: SessionState,
        doctor,
        nlu: NLUResult,
    ) -> WorkflowResult:

        # ========================================================
        # SAVE TRUSTED DOCTOR
        # ========================================================

        state.doctor_id = (
            doctor.id
        )

        # ========================================================
        # DERIVE SPECIALTY FROM TRUSTED DOCTOR
        # ========================================================

        if not state.specialty_id:

            state.specialty_id = doctor.specialty_id

            if state.language == "en":

                state.specialty_name = (
                    doctor.specialty_name_en
                    or doctor.specialty_name_ar
                )

            else:

                state.specialty_name = (
                    doctor.specialty_name_ar
                    or doctor.specialty_name_en
                )

        if (
            state.language
            == "en"
        ):

            state.doctor_name = (
                doctor.full_name_en
                or
                doctor.full_name_ar
            )

        else:

            state.doctor_name = (
                doctor.full_name_ar
                or
                doctor.full_name_en
            )

        # ========================================================
        # DATE ALREADY KNOWN?
        #
        # If the user said:
        #
        # "عايز أحجز جلدية مع دكتور أحمد بكرة"
        #
        # do NOT ask for the date again.
        # ========================================================

        context = (
            resolve_effective_context(
                state=state,
                nlu=nlu,
            )
        )

        if context.date_text:

            return await (
                self._handle_date(
                    state=state,
                    nlu=nlu,
                )
            )

        # ========================================================
        # DATE REALLY MISSING
        # ========================================================

        state.stage = (
            "awaiting_date"
        )

        return WorkflowResult(
            reply=self._message(
                state.language,

                ar=(
                    f"تمام، اخترتي "
                    f"{state.doctor_name}. "
                    "تحبي الحجز يوم إيه؟"
                ),

                en=(
                    f"Great, you selected "
                    f"{state.doctor_name}. "
                    "What date would you like?"
                ),
            ),

            response_type=
                "ask_date",

            data={
                "doctor_id":
                    state.doctor_id,

                "doctor_name":
                    state.doctor_name,
            },
        )

    # ========================================================
    # DATE
    # ========================================================

    async def _handle_date(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        context = (
            resolve_effective_context(
                state=state,
                nlu=nlu,
            )
        )

        date_text = (
            context.date_text
        )

        # ----------------------------------------------------
        # Missing date
        # ----------------------------------------------------

        if not date_text:

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "قولي اليوم أو التاريخ "
                        "اللي يناسبك."
                    ),

                    en=(
                        "Please tell me the date "
                        "you prefer."
                    ),
                ),

                response_type=
                    "ask_date",
            )

        # ----------------------------------------------------
        # Resolve natural date
        # ----------------------------------------------------

        resolved_date = resolve_date(
            date_text
        )

        if resolved_date is None:

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "مش قادر أحدد التاريخ ده. "
                        "ممكن تقولي مثلاً "
                        "بكرة، بعد بكرة، "
                        "أو تاريخ زي 20/8؟"
                    ),

                    en=(
                        "I couldn't understand that "
                        "date. You can say tomorrow, "
                        "the day after tomorrow, "
                        "or a date such as 20/8."
                    ),
                ),

                response_type=
                    "invalid_date",
            )

        # Labs book branch-level slots (no doctor).
        if self.is_lab:

            return await (
                self._load_lab_slots(
                    state=state,
                    nlu=nlu,
                    slot_date=(
                        resolved_date.isoformat()
                    ),
                )
            )

        # ----------------------------------------------------
        # Defensive check
        # ----------------------------------------------------

        if not state.doctor_id:

            state.stage = (
                "awaiting_doctor"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "لازم نحدد الدكتور "
                        "الأول قبل اختيار الميعاد."
                    ),

                    en=(
                        "We need to select a doctor "
                        "before choosing a date."
                    ),
                ),

                response_type=
                    "doctor_required",
            )

        resolved_date_text = (
            resolved_date
            .isoformat()
        )

        # ----------------------------------------------------
        # Call real backend slots
        # ----------------------------------------------------

        slots = await (
            self.tools.call(
                "list_available_slots",

                doctor_id=
                    state.doctor_id,

                slot_date=
                    resolved_date_text,

                limit=100,
            )
        )

        # ----------------------------------------------------
        # Save trusted slot data
        # ----------------------------------------------------

        apply_tool_observation(
            state=state,

            tool_name=
                "list_available_slots",

            data=
                slots,
        )

        state.slot_date = (
            resolved_date_text
        )

        state.slot_id = None
        state.slot_time = None

        # ----------------------------------------------------
        # No available slots
        # ----------------------------------------------------

        if not state.recent_slots:

            state.stage = (
                "awaiting_date"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        f"مفيش مواعيد متاحة "
                        f"لـ{state.doctor_name} "
                        f"يوم {resolved_date_text}. "
                        "تحبي يوم تاني؟"
                    ),

                    en=(
                        f"There are no available slots "
                        f"for {state.doctor_name} "
                        f"on {resolved_date_text}. "
                        "Would you like another date?"
                    ),
                ),

                response_type=
                    "no_slots",

                data={
                    "date":
                        resolved_date_text,

                    "doctor_id":
                        state.doctor_id,
                },
            )

        # ----------------------------------------------------
        # Extract available times
        # ----------------------------------------------------

        available_times = []

        for slot in (
            state.recent_slots
        ):

            display_time = (
                slot.start_time[:5]
            )

            available_times.append(
                display_time
            )

        context = (
            resolve_effective_context(
                state=state,
                nlu=nlu,
            )
        )

        if context.time_text:

            state.stage = (
                "awaiting_time"
            )

            return await (
                self._handle_time(
                    state=state,
                    nlu=nlu,
                )
            )   

        state.stage = (
            "awaiting_time"
        )

        # ----------------------------------------------------
        # Response
        # ----------------------------------------------------

        if state.language == "en":

            time_text = ", ".join(
                available_times
            )

            reply = (
                f"Available times for "
                f"{state.doctor_name} on "
                f"{resolved_date_text} are: "
                f"{time_text}. "
                "Which time would you like?"
            )

        else:

            time_text = "، ".join(
                available_times
            )

            reply = (
                f"المواعيد المتاحة مع "
                f"{state.doctor_name} يوم "
                f"{resolved_date_text}: "
                f"{time_text}. "
                "تحبي الساعة كام؟"
            )

        return WorkflowResult(
            reply=reply,

            response_type=
                "ask_time",

            data={
                "date":
                    resolved_date_text,

                "available_times":
                    available_times,

                "slot_count":
                    len(
                        state.recent_slots
                    ),
            },
        )

    # ========================================================
    # TIME
    # ========================================================

    # ========================================================
    # LAB: BRANCH-LEVEL SLOTS (no doctor)
    # ========================================================

    @staticmethod
    def _slot_branch_name(
        slot,
        language: str,
    ) -> str:

        if language == "en":
            return (
                slot.branch_name_en
                or slot.branch_name_ar
                or slot.branch_id
            )

        return (
            slot.branch_name_ar
            or slot.branch_name_en
            or slot.branch_id
        )

    @staticmethod
    def _lab_branches(
        state: SessionState,
    ) -> list:
        """One representative slot per branch, in trusted order."""

        branches = {}

        for slot in state.recent_slots:
            branches.setdefault(
                slot.branch_id,
                slot,
            )

        return list(
            branches.values()
        )

    def _service_filter(
        self,
        state: SessionState,
    ) -> dict[str, Any]:

        if self.is_lab:
            return {
                "service_type": "diagnostic",
            }

        return {
            "doctor_id": state.doctor_id,
        }

    @staticmethod
    def _selected_slot(
        state: SessionState,
    ):

        for slot in state.recent_slots:
            if slot.id == state.slot_id:
                return slot

        return None

    def _branch_choice_reply(
        self,
        *,
        state: SessionState,
        branches: list,
        intro_ar: str,
        intro_en: str,
    ) -> WorkflowResult:

        names = [
            self._slot_branch_name(
                slot,
                state.language,
            )
            for slot in branches
        ]

        numbered = "\n".join(
            f"{index}. {name}"
            for index, name
            in enumerate(names, start=1)
        )

        return WorkflowResult(
            reply=self._message(
                state.language,
                ar=(
                    f"{intro_ar}\n{numbered}\n"
                    "تحبي أنهي فرع؟"
                ),
                en=(
                    f"{intro_en}\n{numbered}\n"
                    "Which branch would you like?"
                ),
            ),
            response_type=
                "ask_branch",
            data={
                "date":
                    state.slot_date,
                "branches":
                    names,
            },
        )

    async def _load_lab_slots(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
        slot_date: str,
    ) -> WorkflowResult:

        slots = await (
            self.tools.call(
                "list_available_slots",
                slot_date=slot_date,
                limit=100,
            )
        )

        apply_tool_observation(
            state=state,
            tool_name=
                "list_available_slots",
            data=
                slots,
        )

        # A lab books only branch-level (doctor-less) slots.
        state.recent_slots = [
            slot
            for slot in state.recent_slots
            if slot.doctor_id is None
        ]

        state.slot_date = slot_date
        state.slot_id = None
        state.slot_time = None

        if not state.recent_slots:

            state.stage = (
                "awaiting_date"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,
                    ar=(
                        f"مفيش مواعيد متاحة يوم "
                        f"{slot_date}. تحبي يوم تاني؟"
                    ),
                    en=(
                        f"There are no available slots "
                        f"on {slot_date}. "
                        "Would you like another date?"
                    ),
                ),
                response_type=
                    "no_slots",
                data={
                    "date":
                        slot_date,
                },
            )

        branches = self._lab_branches(
            state
        )

        # The same time can exist at several branches:
        # the branch must be chosen before the time.
        if len(branches) > 1:

            state.stage = (
                "awaiting_branch"
            )

            return self._branch_choice_reply(
                state=state,
                branches=branches,
                intro_ar=(
                    f"فيه مواعيد يوم {slot_date} "
                    "في الفروع دي:"
                ),
                intro_en=(
                    f"There are slots on {slot_date} "
                    "at these branches:"
                ),
            )

        return await (
            self._present_lab_times(
                state=state,
                nlu=nlu,
            )
        )

    async def _present_lab_times(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        state.stage = (
            "awaiting_time"
        )

        context = (
            resolve_effective_context(
                state=state,
                nlu=nlu,
            )
        )

        if context.time_text:
            return await (
                self._handle_time(
                    state=state,
                    nlu=nlu,
                )
            )

        available_times = [
            slot.start_time[:5]
            for slot in state.recent_slots
        ]

        branch_name = self._slot_branch_name(
            state.recent_slots[0],
            state.language,
        )

        return WorkflowResult(
            reply=self._message(
                state.language,
                ar=(
                    f"المواعيد المتاحة في "
                    f"{branch_name} يوم "
                    f"{state.slot_date}: "
                    + "، ".join(available_times)
                    + ". أنهي ميعاد يناسبك؟"
                ),
                en=(
                    f"Available times at "
                    f"{branch_name} on "
                    f"{state.slot_date} are: "
                    + ", ".join(available_times)
                    + ". Which time suits you?"
                ),
            ),
            response_type=
                "ask_time",
            data={
                "date":
                    state.slot_date,
                "branch_id":
                    state.recent_slots[0].branch_id,
                "available_times":
                    available_times,
                "slot_count":
                    len(state.recent_slots),
            },
        )

    @staticmethod
    def _match_branch(
        text: str,
        branches: list,
    ):

        digits = str.maketrans(
            "٠١٢٣٤٥٦٧٨٩",
            "0123456789",
        )

        normalized = normalize_text(
            (text or "").translate(digits)
        )

        if not normalized:
            return None

        if normalized.isdigit():

            index = int(normalized)

            if 1 <= index <= len(branches):
                return branches[index - 1]

            return None

        matches = []

        for slot in branches:

            labels = set()

            for name in (
                slot.branch_name_ar,
                slot.branch_name_en,
            ):
                if not name:
                    continue

                labels.add(
                    normalize_text(name)
                )

                # "Alfa Labs - Maadi" -> "maadi"
                for part in name.split("-"):

                    part = normalize_text(part)

                    if len(part) >= 3:
                        labels.add(part)

            if any(
                label
                and (
                    label in normalized
                    or (
                        len(normalized) >= 3
                        and normalized in label
                    )
                )
                for label in labels
            ):
                matches.append(slot)

        # Parts shared by every branch (e.g. the lab name)
        # match all of them: only a unique match counts.
        if len(matches) == 1:
            return matches[0]

        return None

    async def _handle_branch(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
        user_message: str = "",
    ) -> WorkflowResult:

        branches = self._lab_branches(
            state
        )

        if not branches:

            state.stage = (
                "awaiting_date"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,
                    ar=(
                        "قولي اليوم أو التاريخ "
                        "اللي يناسبك."
                    ),
                    en=(
                        "Please tell me the date "
                        "you prefer."
                    ),
                ),
                response_type=
                    "date_required",
            )

        chosen = self._match_branch(
            user_message,
            branches,
        )

        if chosen is None:

            return self._branch_choice_reply(
                state=state,
                branches=branches,
                intro_ar=(
                    "مش متأكد أنهي فرع. "
                    "اختاري واحد من دول:"
                ),
                intro_en=(
                    "I'm not sure which branch. "
                    "Please choose one of these:"
                ),
            )

        state.recent_slots = [
            slot
            for slot in state.recent_slots
            if slot.branch_id
            == chosen.branch_id
        ]

        return await (
            self._present_lab_times(
                state=state,
                nlu=nlu,
            )
        )

    async def _handle_time(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        context = (
            resolve_effective_context(
                state=state,
                nlu=nlu,
            )
        )

        time_text = (
            context.time_text
        )

        # ----------------------------------------------------
        # Missing time
        # ----------------------------------------------------

        if not time_text:

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "قولي الساعة اللي "
                        "تناسبك من المواعيد "
                        "المتاحة."
                    ),

                    en=(
                        "Please choose a time "
                        "from the available slots."
                    ),
                ),

                response_type=
                    "ask_time",
            )

        # ----------------------------------------------------
        # Defensive check
        # ----------------------------------------------------

        if not state.recent_slots:

            state.stage = (
                "awaiting_date"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "محتاجين نختار التاريخ "
                        "الأول عشان أجيب "
                        "المواعيد المتاحة."
                    ),

                    en=(
                        "We need to choose a date "
                        "first so I can load the "
                        "available times."
                    ),
                ),

                response_type=
                    "date_required",
            )

        # ----------------------------------------------------
        # Resolve possible times
        # ----------------------------------------------------

        candidates = (
            resolve_time_candidates(
                time_text
            )
        )

        if not candidates:

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "مش قادر أحدد الساعة دي. "
                        "ممكن تقولي مثلاً "
                        "12، 1 ونص، أو 14:00؟"
                    ),

                    en=(
                        "I couldn't understand that "
                        "time. You can say 12, "
                        "1:30, or 14:00."
                    ),
                ),

                response_type=
                    "invalid_time",
            )

        # ----------------------------------------------------
        # Match against trusted slots
        # ----------------------------------------------------

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
        # No slot matched
        # ----------------------------------------------------

        if not matches:

            available_times = [
                slot.start_time[:5]
                for slot
                in state.recent_slots
            ]

            if (
                state.language
                == "en"
            ):

                times_text = ", ".join(
                    available_times
                )

                reply = (
                    "That time isn't available. "
                    f"The available times are: "
                    f"{times_text}. "
                    "Which one would you like?"
                )

            else:

                times_text = "، ".join(
                    available_times
                )

                reply = (
                    "الساعة دي مش متاحة. "
                    f"المواعيد المتاحة هي: "
                    f"{times_text}. "
                    "تحبي تختاري أنهي ميعاد؟"
                )

            return WorkflowResult(
                reply=reply,

                response_type=
                    "time_not_available",

                data={
                    "requested_time":
                        time_text,

                    "available_times":
                        available_times,
                },
            )

        # ----------------------------------------------------
        # Ambiguous time
        # ----------------------------------------------------

        if len(matches) > 1:

            matching_times = [
                slot.start_time[:5]
                for slot
                in matches
            ]

            if (
                state.language
                == "en"
            ):

                reply = (
                    "I found more than one matching "
                    "time: "
                    + ", ".join(
                        matching_times
                    )
                    + ". Which one do you mean?"
                )

            else:

                reply = (
                    "لقيت أكتر من ميعاد ممكن "
                    "يقصدهم الوقت ده: "
                    + "، ".join(
                        matching_times
                    )
                    + ". تقصدي أنهي واحد؟"
                )

            return WorkflowResult(
                reply=reply,

                response_type=
                    "ambiguous_time",

                data={
                    "matching_times":
                        matching_times,
                },
            )

        # ----------------------------------------------------
        # Exactly one real slot matched
        # ----------------------------------------------------

        selected_slot = (
            matches[0]
        )

        state.slot_id = (
            selected_slot.id
        )

        state.slot_date = (
            selected_slot.slot_date
        )

        state.slot_time = (
            selected_slot
            .start_time[:5]
        )

        return await (
            self._load_doctor_services(
                state=state,
                nlu=nlu,
            )
        )

    # ========================================================
    # LOAD DOCTOR SERVICES
    # ========================================================

    async def _load_doctor_services(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        # ----------------------------------------------------
        # Doctor required (labs have none)
        # ----------------------------------------------------

        if not state.doctor_id and not self.is_lab:

            state.stage = (
                "awaiting_doctor"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "لازم نحدد الدكتور "
                        "الأول."
                    ),

                    en=(
                        "We need to select "
                        "a doctor first."
                    ),
                ),

                response_type=
                    "doctor_required",
            )

        # ----------------------------------------------------
        # Load trusted services
        # ----------------------------------------------------

        services = await (
            self.tools.call(
                "list_services",

                **self._service_filter(state),

                limit=100,
            )
        )

        apply_tool_observation(
            state=state,

            tool_name=
                "list_services",

            data=
                services,
        )

        # ----------------------------------------------------
        # No services
        # ----------------------------------------------------

        if not state.recent_services:

            state.stage = (
                "awaiting_service"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "مش لاقي تحليل متاح "
                        "حالياً."
                        if self.is_lab
                        else
                        "مش لاقي خدمة متاحة "
                        "للدكتور ده حالياً."
                    ),

                    en=(
                        "I couldn't find an "
                        "available test."
                        if self.is_lab
                        else
                        "I couldn't find an "
                        "available service for "
                        "this doctor."
                    ),
                ),

                response_type=
                    "no_services",
            )

        context = (
            resolve_effective_context(
                state=state,
                nlu=nlu,
            )
        )

        requested_service_name = (
            context.service_name
        )

        if requested_service_name:

            service = (
                self._find_service(
                    query=
                        requested_service_name,

                    state=
                        state,
                )
            )

            if service is None:

                service_names = []

                for item in (
                    state.recent_services
                ):

                    if state.language == "en":

                        name = (
                            item.name_en
                            or
                            item.name_ar
                        )

                    else:

                        name = (
                            item.name_ar
                            or
                            item.name_en
                        )

                    if name:

                        service_names.append(
                            name
                        )

                state.stage = (
                    "awaiting_service"
                )

                return WorkflowResult(
                    reply=self._message(
                        state.language,

                        ar=(
                            "الخدمة دي مش متاحة "
                            "مع الدكتور ده. "
                            "الخدمات المتاحة: "
                            + "، ".join(
                                service_names
                            )
                            + ". تحبي أنهي خدمة؟"
                        ),

                        en=(
                            "That service isn't available "
                            "with this doctor. "
                            "Available services are: "
                            + ", ".join(
                                service_names
                            )
                            + ". Which service would you like?"
                        ),
                    ),

                    response_type=
                        "service_not_found",

                    data={
                        "services":
                            service_names,
                    },
                )

            state.service_id = (
                service.id
            )

            if state.language == "en":

                state.service_name = (
                    service.name_en
                    or
                    service.name_ar
                )

            else:

                state.service_name = (
                    service.name_ar
                    or
                    service.name_en
                )

            return (
                self._continue_after_service_selection(
                    state=state,
                )
            )

        # ----------------------------------------------------
        # Exactly one service
        # ----------------------------------------------------

        if (
            len(
                state.recent_services
            )
            == 1
        ):

            service = (
                state.recent_services[0]
            )

            state.service_id = (
                service.id
            )

            if state.language == "en":

                state.service_name = (
                    service.name_en
                    or
                    service.name_ar
                )

            else:

                state.service_name = (
                    service.name_ar
                    or
                    service.name_en
                )

            return (
                self._continue_after_service_selection(
                    state=state,
                )
            )        

        # ----------------------------------------------------
        # Multiple services
        # ----------------------------------------------------

        state.stage = (
            "awaiting_service"
        )

        if state.channel == "voice":

            return WorkflowResult(
                reply=self._message(
                    state.language,
                    ar=(
                        "حضرتك عايز خدمة معينة، "
                        "ولا أحجزلك كشف جلدية عادي؟"
                    ),
                    en=(
                        "Would you like a specific service, "
                        "or should I book a standard "
                        "dermatology consultation?"
                    ),
                ),
                response_type="ask_service_preference",
            )

        service_names = []

        for service in (
            state.recent_services
        ):

            if state.language == "en":

                name = (
                    service.name_en
                    or
                    service.name_ar
                )

            else:

                name = (
                    service.name_ar
                    or
                    service.name_en
                )

            if name:

                service_names.append(
                    name
                )

        if state.language == "en":

            reply = (
                "This doctor provides more than "
                "one service: "
                + ", ".join(
                    service_names
                )
                + ". Which service would you like?"
            )

        else:

            reply = (
                "الدكتور بيقدم أكتر من خدمة: "
                + "، ".join(
                    service_names
                )
                + ". تحبي أنهي خدمة؟"
            )

        return WorkflowResult(
            reply=reply,

            response_type=
                "ask_service",

            data={
                "services":
                    service_names,
            },
        )

    
    def _continue_after_service_selection(
        self,
        *,
        state: SessionState,
    ) -> WorkflowResult:

        # ========================================================
        # EXISTING PATIENT ALREADY KNOWN
        # ========================================================

        if (
            state.patient_id
            and
            state.national_id
        ):

            return (
                self._prepare_confirmation(
                    state=state,
                )
            )

        # ========================================================
        # PATIENT IDENTITY STILL REQUIRED
        # ========================================================

        state.stage = (
            "awaiting_national_id"
        )

        return WorkflowResult(
            reply=self._message(
                state.language,

                ar=(
                    f"تمام، الخدمة هي "
                    f"{state.service_name}. "
                    "ممكن الرقم القومي "
                    "عشان نكمل الحجز؟"
                ),

                en=(
                    f"Great. The service is "
                    f"{state.service_name}. "
                    "Please provide the national "
                    "ID so we can continue."
                ),
            ),

            response_type=
                "ask_national_id",

            data={
                "service_id":
                    state.service_id,

                "service_name":
                    state.service_name,

                "slot_id":
                    state.slot_id,

                "slot_date":
                    state.slot_date,

                "slot_time":
                    state.slot_time,
            },
        )

    # ========================================================
    # SERVICE
    # ========================================================

    async def _handle_service(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        context = (
            resolve_effective_context(
                state=state,
                nlu=nlu,
            )
        )

        service_name = (
            context.service_name
        )

        # ----------------------------------------------------
        # Voice service preference
        # ----------------------------------------------------

        if state.channel == "voice":

            default_service_aliases = {
                normalize_text(value)
                for value in (
                    "عادي",
                    "كشف عادي",
                    "كشف جلدية",
                    "كشف جلدية عادي",
                    "جلدية",
                    "regular consultation",
                    "standard consultation",
                    "dermatology consultation",
                )
            }

            default_service_requested = (
                nlu.intent == "deny_action"
                or nlu.confirmation == "no"
                or (
                    service_name
                    and normalize_text(
                        service_name
                    )
                    in default_service_aliases
                )
            )

            if default_service_requested:

                service = self._find_service(
                    query="SKIN_CONSULT",
                    state=state,
                )

                if service is None:

                    return WorkflowResult(
                        reply=self._message(
                            state.language,
                            ar=(
                                "مش لاقي كشف جلدية عادي "
                                "متاح مع الدكتور حاليًا."
                            ),
                            en=(
                                "I couldn't find a standard "
                                "dermatology consultation "
                                "for this doctor."
                            ),
                        ),
                        response_type=
                            "default_service_not_found",
                    )

                state.service_id = (
                    service.id
                )

                if state.language == "en":
                    state.service_name = (
                        service.name_en
                        or service.name_ar
                    )
                else:
                    state.service_name = (
                        service.name_ar
                        or service.name_en
                    )

                return (
                    self._continue_after_service_selection(
                        state=state,
                    )
                )

            wants_specific_service = (
                nlu.intent == "confirm_action"
                or nlu.confirmation == "yes"
            )

            if (
                not service_name
                and wants_specific_service
            ):

                return WorkflowResult(
                    reply=self._message(
                        state.language,
                        ar="تمام، قولي اسم الخدمة.",
                        en=(
                            "Sure. Tell me "
                            "the service name."
                        ),
                    ),
                    response_type="ask_service",
                )
            
        if not service_name:

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "قولي اسم الخدمة "
                        "اللي عايزاها."
                    ),

                    en=(
                        "Please tell me which "
                        "service you would like."
                    ),
                ),

                response_type=
                    "ask_service",
            )

        service = self._find_service(
            query=
                service_name,

            state=
                state,
        )

        if service is None:

            service_names = []

            for item in (
                state.recent_services
            ):

                if (
                    state.language
                    == "en"
                ):

                    name = (
                        item.name_en
                        or
                        item.name_ar
                    )

                else:

                    name = (
                        item.name_ar
                        or
                        item.name_en
                    )

                if name:

                    service_names.append(
                        name
                    )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "مش لاقي الخدمة دي "
                        "ضمن الاختيارات. "
                        "المتاح: "
                        + "، ".join(
                            service_names
                        )
                    ),

                    en=(
                        "I couldn't match that "
                        "service. Available services: "
                        + ", ".join(
                            service_names
                        )
                    ),
                ),

                response_type=
                    "service_not_found",
            )

        # ----------------------------------------------------
        # Save trusted service
        # ----------------------------------------------------

        state.service_id = (
            service.id
        )

        if state.language == "en":

            state.service_name = (
                service.name_en
                or
                service.name_ar
            )

        else:

            state.service_name = (
                service.name_ar
                or
                service.name_en
            )

        return (
            self._continue_after_service_selection(
                state=state,
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

        # ----------------------------------------------------
        # Missing
        # ----------------------------------------------------

        if not national_id_text:

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

                response_type=
                    "ask_national_id",
            )

        # ----------------------------------------------------
        # Normalize
        # ----------------------------------------------------

        national_id = (
            resolve_national_id(
                national_id_text
            )
        )

        if national_id is None:

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

                response_type=
                    "invalid_national_id",
            )

        state.national_id = (
            national_id
        )

        # ----------------------------------------------------
        # Backend lookup
        # ----------------------------------------------------

        lookup_language = (
            "en"
            if state.language == "en"
            else "ar"
        )

        lookup_result = await (
            self.tools.call(
                "lookup_patient",

                national_id=
                    national_id,

                language=
                    lookup_language,
            )
        )

        if not isinstance(
            lookup_result,
            dict,
        ):

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "حصلت مشكلة وأنا بتأكد "
                        "من بيانات المريض. "
                        "جربي تاني."
                    ),

                    en=(
                        "There was a problem checking "
                        "the patient information. "
                        "Please try again."
                    ),
                ),

                response_type=
                    "patient_lookup_error",
            )

        found = (
            lookup_result.get(
                "found"
            )
        )

        patient = (
            lookup_result.get(
                "patient"
            )
        )

        # ----------------------------------------------------
        # NEW PATIENT
        # ----------------------------------------------------

        if (
            found is False
            or
            patient is None
        ):

            state.patient_id = None
            state.patient_name = None
            state.phone = None
            state.phone_confirmed = False

            state.stage = (
                "awaiting_patient_name"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "تمام. أول مرة نسجل "
                        "البيانات دي عندنا. "
                        "ممكن تقولي اسم المريض؟"
                    ),

                    en=(
                        "Thanks. This patient isn't "
                        "registered yet. "
                        "What is the patient's name?"
                    ),
                ),

                response_type=
                    "ask_patient_name",
            )

        # ----------------------------------------------------
        # EXISTING PATIENT
        # ----------------------------------------------------

        if (
            found is True
            and
            isinstance(
                patient,
                dict,
            )
        ):

            patient_id = (
                patient.get(
                    "patient_id"
                )
                or
                patient.get(
                    "id"
                )
            )

            patient_name = (
                patient.get(
                    "display_name"
                )
                or
                patient.get(
                    "full_name_ar"
                )
                or
                patient.get(
                    "full_name_en"
                )
            )

            phone = (
                patient.get(
                    "phone"
                )
            )

            if not patient_id:

                return WorkflowResult(
                    reply=self._message(
                        state.language,

                        ar=(
                            "حصلت مشكلة وأنا "
                            "بقرأ بيانات المريض."
                        ),

                        en=(
                            "There was a problem "
                            "reading the patient data."
                        ),
                    ),

                    response_type=
                        "patient_lookup_error",
                )

            state.patient_id = (
                patient_id
            )

            state.patient_name = (
                patient_name
            )

            state.phone = (
                phone
            )

            # Important:
            # confirmation must be fresh for Voice.
            state.phone_confirmed = False

            # ------------------------------------------------
            # Voice must confirm stored phone
            # ------------------------------------------------

            if state.channel == "voice":

                if not state.phone:

                    state.stage = (
                        "awaiting_phone"
                    )

                    return WorkflowResult(
                        reply=self._message(
                            state.language,

                            ar=(
                                "ممكن تقولي رقم الموبايل "
                                "اللي هنبعت عليه تفاصيل الحجز؟"
                            ),

                            en=(
                                "What mobile number should I use "
                                "to send the booking details?"
                            ),
                        ),

                        response_type=
                            "ask_phone",
                    )

                state.stage = (
                    "awaiting_phone_confirmation"
                )

                return self._phone_confirmation_result(
                    state=state,
                )

            # ------------------------------------------------
            # Non-voice
            # ------------------------------------------------

            state.phone_confirmed = True

            return self._prepare_confirmation(
                state=state,
            )

        # ----------------------------------------------------
        # Unexpected contract
        # ----------------------------------------------------

        return WorkflowResult(
            reply=self._message(
                state.language,

                ar=(
                    "حصلت مشكلة وأنا بتأكد "
                    "من بيانات المريض."
                ),

                en=(
                    "There was a problem checking "
                    "the patient information."
                ),
            ),

            response_type=
                "patient_lookup_error",
        )

    # ========================================================
    # PATIENT NAME
    # ========================================================

    async def _handle_patient_name(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        patient_name = (
            nlu.entities
            .patient_name
        )

        if not patient_name:

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "ممكن تقولي اسم "
                        "المريض كامل؟"
                    ),

                    en=(
                        "Please provide the "
                        "patient's full name."
                    ),
                ),

                response_type=
                    "ask_patient_name",
            )

        patient_name = (
            patient_name.strip()
        )

        if len(patient_name) < 2:

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "ممكن تكتبي اسم "
                        "المريض بشكل أوضح؟"
                    ),

                    en=(
                        "Please provide a clearer "
                        "patient name."
                    ),
                ),

                response_type=
                    "invalid_patient_name",
            )

        state.patient_name = (
            patient_name
        )

        state.stage = (
            "awaiting_phone"
        )

        return WorkflowResult(
            reply=self._message(
                state.language,

                ar=(
                    "تمام. ممكن رقم "
                    "التليفون؟"
                ),

                en=(
                    "Thanks. Please provide "
                    "the phone number."
                ),
            ),

            response_type=
                "ask_phone",
        )

    async def _handle_patient_name_correction(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        corrected_name = (
            nlu.entities.patient_name
        )

        # ----------------------------------------------------
        # Missing / unclear name
        # ----------------------------------------------------

        if not self._is_valid_full_patient_name(
            corrected_name
        ):

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "اسم المريض مش واضح. "
                        "قولي الاسم الصح كامل."
                    ),

                    en=(
                        "The patient name isn't clear. "
                        "Please provide the correct full name."
                    ),
                ),

                response_type=
                    "ask_patient_name_correction",
            )

        corrected_name = (
            corrected_name.strip()
        )

        # ----------------------------------------------------
        # Save correction in state only.
        #
        # Do NOT persist to DB yet.
        # Final booking confirmation must happen first.
        # ----------------------------------------------------

        if (
            corrected_name
            != state.patient_name
        ):

            state.patient_name = (
                corrected_name
            )

            if state.patient_id:

                state.pending_patient_profile_updates[
                    "patient_name"
                ] = corrected_name

        # ----------------------------------------------------
        # Read booking back again for confirmation.
        # ----------------------------------------------------

        return self._prepare_confirmation(
            state=state,
        )    

    # ========================================================
    # PHONE
    # ========================================================

    async def _handle_phone(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        phone = (
            nlu.entities
            .phone
        )

        if not phone:

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "ممكن رقم التليفون "
                        "عشان نكمل التسجيل؟"
                    ),

                    en=(
                        "Please provide the phone "
                        "number so we can continue."
                    ),
                ),

                response_type=
                    "ask_phone",
            )

        # ----------------------------------------------------
        # Arabic digits → English digits
        # ----------------------------------------------------

        translation = str.maketrans(
            {
                "٠": "0",
                "١": "1",
                "٢": "2",
                "٣": "3",
                "٤": "4",
                "٥": "5",
                "٦": "6",
                "٧": "7",
                "٨": "8",
                "٩": "9",
            }
        )

        normalized_phone = (
            phone
            .translate(
                translation
            )
            .replace(
                " ",
                "",
            )
            .replace(
                "-",
                "",
            )
        )

        # ----------------------------------------------------
        # Numeric validation
        # ----------------------------------------------------

        if (
            not normalized_phone
            .replace(
                "+",
                "",
                1,
            )
            .isdigit()
        ):

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "رقم التليفون مش واضح. "
                        "ممكن تقوله تاني؟"
                    ),

                    en=(
                        "The phone number doesn't "
                        "look valid. Please say it again."
                    ),
                ),

                response_type=
                    "invalid_phone",
            )

        # ----------------------------------------------------
        # Egyptian mobile validation
        # ----------------------------------------------------

        if not re.fullmatch(
            r"01[0125]\d{8}",
            normalized_phone,
        ):

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "رقم الموبايل لازم يكون 11 رقم "
                        "ويبدأ بـ 010 أو 011 أو 012 أو 015. "
                        "ممكن تقوله من البداية؟"
                    ),

                    en=(
                        "The Egyptian mobile number must contain "
                        "11 digits and start with 010, 011, 012, or 015. "
                        "Please say it again from the beginning."
                    ),
                ),

                response_type=
                    "invalid_phone",
            )

        previous_phone = (
            state.phone
        )

        state.phone = (
            normalized_phone
        )

        if (
            state.patient_id
            and
            normalized_phone
            != previous_phone
        ):

            state.pending_patient_profile_updates[
                "phone"
            ] = normalized_phone

        # ----------------------------------------------------
        # Voice MUST confirm before backend resolution
        # ----------------------------------------------------

        if state.channel == "voice":

            state.phone_confirmed = False

            state.stage = (
                "awaiting_phone_confirmation"
            )

            return self._phone_confirmation_result(
                state=state,
            )

        # ----------------------------------------------------
        # Non-voice continues normally
        # ----------------------------------------------------

        state.phone_confirmed = True

        return await (
            self._resolve_patient_and_prepare_confirmation(
                state=state,
            )
        )

    # ========================================================
    # PHONE CONFIRMATION
    # ========================================================

    async def _handle_phone_confirmation(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        if (
            nlu.intent == "provide_phone"
            and nlu.entities.phone
        ):
            return await self._handle_phone(
                state=state,
                nlu=nlu,
            )

        if (
            nlu.intent == "provide_phone"
            and
            nlu.confirmation != "yes"
        ):

            # Discard the unconfirmed phone.
            state.pending_patient_profile_updates.pop(
                "phone",
                None,
            )

            state.phone = None
            state.phone_confirmed = False

            state.stage = (
                "awaiting_phone"
            )

            state.awaiting_confirmation = False
            state.pending_action = None

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "تمام، قولي رقم الموبايل "
                        "الصح من البداية."
                    ),

                    en=(
                        "Okay. Please say the correct "
                        "mobile number from the beginning."
                    ),
                ),

                response_type=
                    "ask_phone_correction",
            )

        confirmed = (
            nlu.intent == "confirm_action"
            or
            nlu.confirmation == "yes"
        )

        denied = (
            nlu.intent == "deny_action"
            or
            nlu.confirmation == "no"
        )

        # ====================================================
        # 3. WRONG PHONE
        # ====================================================

        if denied:

            # Discard the unconfirmed phone.
            state.pending_patient_profile_updates.pop(
                "phone",
                None,
            )

            state.phone = None
            state.phone_confirmed = False

            state.stage = (
                "awaiting_phone"
            )

            state.awaiting_confirmation = False
            state.pending_action = None

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "تمام، قولي رقم الموبايل "
                        "الصح من البداية."
                    ),

                    en=(
                        "Okay. Please say the correct "
                        "mobile number from the beginning."
                    ),
                ),

                response_type=
                    "ask_phone_again",
            )

        # ====================================================
        # 4. DIDN'T UNDERSTAND
        # ====================================================

        if not confirmed:

            return self._phone_confirmation_result(
                state=state,
            )

        # ====================================================
        # 5. PHONE CONFIRMED
        # ====================================================

        state.phone_confirmed = True

        # ====================================================
        # 6. PERSIST EXISTING-PATIENT CORRECTIONS
        # ====================================================

        if (
            state.patient_id
            and
            state.pending_patient_profile_updates
        ):

            persistence_error = await (
                self._persist_pending_patient_profile_updates(
                    state=state,
                )
            )

            if persistence_error is not None:

                return persistence_error

        # ====================================================
        # 7. EXISTING PATIENT
        # ====================================================

        if state.patient_id:

            return self._prepare_confirmation(
                state=state,
            )

        # ====================================================
        # 8. NEW PATIENT
        # ====================================================

        return await (
            self._resolve_patient_and_prepare_confirmation(
                state=state,
            )
        )

    def _phone_confirmation_result(
        self,
        *,
        state: SessionState,
    ) -> WorkflowResult:

        if not state.phone:

            state.stage = (
                "awaiting_phone"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "ممكن تقولي رقم الموبايل؟"
                    ),

                    en=(
                        "Please tell me "
                        "the mobile number."
                    ),
                ),

                response_type=
                    "ask_phone",
            )

        spoken_phone = (
            self._format_phone_for_confirmation(
                phone=
                    state.phone,

                language=
                    state.language,
            )
        )

        return WorkflowResult(
            reply=self._message(
                state.language,

                ar=(
                    "رقم الموبايل اللي هنبعت عليه "
                    f"التفاصيل هو: {spoken_phone}. "
                    "صح؟"
                ),

                en=(
                    "The mobile number I will use "
                    f"to send the details is {spoken_phone}. "
                    "Is that correct?"
                ),
            ),

            response_type=
                "phone_confirmation",

            data={
                "phone":
                    state.phone,
            },
        )

    # ========================================================
    # PHONE SPEECH FORMATTER
    # ========================================================

    @staticmethod
    def _format_phone_for_confirmation(
        *,
        phone: str,
        language: str,
    ) -> str:

        digits = "".join(
            character
            for character in phone
            if character.isdigit()
        )

        # 010 | 234 | 567 | 89
        groups = [
            digits[0:3],
            digits[3:6],
            digits[6:9],
            digits[9:11],
        ]

        groups = [
            group
            for group in groups
            if group
        ]

        if language == "en":

            return ", ".join(
                " ".join(
                    group
                )
                for group in groups
            )

        digit_words = {
            "0": "صفر",
            "1": "واحد",
            "2": "اتنين",
            "3": "تلاتة",
            "4": "أربعة",
            "5": "خمسة",
            "6": "ستة",
            "7": "سبعة",
            "8": "تمانية",
            "9": "تسعة",
        }

        return "، ".join(
            " ".join(
                digit_words[
                    digit
                ]
                for digit in group
            )
            for group in groups
        )

    # ========================================================
    # RESOLVE / CREATE NEW PATIENT
    # ========================================================

    async def _resolve_patient_and_prepare_confirmation(
        self,
        *,
        state: SessionState,
    ) -> WorkflowResult:

        # ----------------------------------------------------
        # Required patient data
        # ----------------------------------------------------

        if (
            not state.national_id
            or
            not state.patient_name
            or
            not state.phone
        ):

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "فيه بيانات ناقصة "
                        "لتسجيل المريض."
                    ),

                    en=(
                        "Some patient information "
                        "is missing."
                    ),
                ),

                response_type=
                    "patient_data_incomplete",
            )

        preferred_language = (
            "en"
            if state.language == "en"
            else "ar"
        )

        # ----------------------------------------------------
        # Resolve/create patient through backend
        # ----------------------------------------------------

        result = await (
            self.tools.call(
                "resolve_patient",

                national_id=
                    state.national_id,

                patient_name=
                    state.patient_name,

                phone=
                    state.phone,

                preferred_language=
                    preferred_language,

                channel=
                    state.channel,
            )
        )

        if not isinstance(
            result,
            dict,
        ):

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "حصلت مشكلة أثناء "
                        "تسجيل بيانات المريض."
                    ),

                    en=(
                        "There was a problem "
                        "registering the patient."
                    ),
                ),

                response_type=
                    "patient_resolve_error",
            )

        patient = (
            result.get(
                "patient"
            )
        )

        if not isinstance(
            patient,
            dict,
        ):

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "حصلت مشكلة أثناء "
                        "تسجيل بيانات المريض."
                    ),

                    en=(
                        "There was a problem "
                        "registering the patient."
                    ),
                ),

                response_type=
                    "patient_resolve_error",
            )

        patient_id = (
            patient.get(
                "id"
            )
            or
            patient.get(
                "patient_id"
            )
        )

        if not patient_id:

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "مقدرتش أتأكد من "
                        "تسجيل المريض."
                    ),

                    en=(
                        "I couldn't confirm "
                        "the patient registration."
                    ),
                ),

                response_type=
                    "patient_resolve_error",
            )

        # ----------------------------------------------------
        # Save trusted backend values
        # ----------------------------------------------------

        state.patient_id = (
            patient_id
        )

        if state.language == "en":

            state.patient_name = (
                patient.get(
                    "full_name_en"
                )
                or
                patient.get(
                    "full_name_ar"
                )
                or
                patient.get(
                    "display_name"
                )
                or
                state.patient_name
            )

        else:

            state.patient_name = (
                patient.get(
                    "full_name_ar"
                )
                or
                patient.get(
                    "full_name_en"
                )
                or
                patient.get(
                    "display_name"
                )
                or
                state.patient_name
            )

        state.phone = (
            patient.get(
                "phone"
            )
            or
            state.phone
        )

        return self._prepare_confirmation(
            state=state,
        )

    # ========================================================
    # PREPARE BOOKING CONFIRMATION
    # ========================================================

    def _confirmation_party(
        self,
        state: SessionState,
        style: str,
    ) -> str:
        """Doctor line for clinics/hospitals, branch line for labs."""

        if not self.is_lab:
            return {
                "voice_en": f"with {state.doctor_name}, ",
                "voice_ar": f"مع {state.doctor_name}، ",
                "text_en": f"Doctor: {state.doctor_name}\n",
                "text_ar": f"الدكتور: {state.doctor_name}\n",
            }[style]

        slot = self._selected_slot(state)

        branch = (
            self._slot_branch_name(
                slot,
                state.language,
            )
            if slot is not None
            else ""
        )

        if not branch:
            return ""

        return {
            "voice_en": f"at {branch}, ",
            "voice_ar": f"في {branch}، ",
            "text_en": f"Branch: {branch}\n",
            "text_ar": f"الفرع: {branch}\n",
        }[style]

    def _prepare_confirmation(
        self,
        *,
        state: SessionState,
    ) -> WorkflowResult:

        required_values = {
            "doctor_id":
                state.doctor_id,

            "service_id":
                state.service_id,

            "slot_id":
                state.slot_id,

            "slot_date":
                state.slot_date,

            "slot_time":
                state.slot_time,

            "national_id":
                state.national_id,

            "patient_id":
                state.patient_id,
        }

        # Lab bookings have no doctor.
        if self.is_lab:
            required_values.pop(
                "doctor_id"
            )

        missing = [
            key
            for key, value
            in required_values.items()
            if not value
        ]

        if missing:

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "فيه بيانات ناقصة "
                        "قبل تأكيد الحجز."
                    ),

                    en=(
                        "Some information is "
                        "missing before confirmation."
                    ),
                ),

                response_type=
                    "booking_data_incomplete",

                data={
                    "missing":
                        missing,
                },
            )

        # ----------------------------------------------------
        # Voice requires phone confirmation
        # ----------------------------------------------------

        if (
            state.channel == "voice"
            and
            not state.phone_confirmed
        ):

            state.stage = (
                "awaiting_phone_confirmation"
            )

            state.awaiting_confirmation = False
            state.pending_action = None

            return self._phone_confirmation_result(
                state=state,
            )

        # ----------------------------------------------------
        # Ready for final confirmation
        # ----------------------------------------------------

        state.stage = (
            "awaiting_confirmation"
        )

        state.awaiting_confirmation = (
            True
        )

        state.pending_action = (
            "create_booking"
        )

        # ----------------------------------------------------
        # Voice English
        # ----------------------------------------------------

        if (
            state.channel == "voice"
            and
            state.language == "en"
        ):

            reply = (
                f"Okay. I'll confirm the booking for "
                f"{state.patient_name}, "
                f"{self._confirmation_party(state, 'voice_en')}"
                f"on {state.slot_date}, "
                f"at {state.slot_time}. "
                "Is that correct?"
            )

        # ----------------------------------------------------
        # Voice Arabic
        # ----------------------------------------------------

        elif state.channel == "voice":

            reply = (
                f"تمام، هأكد الحجز باسم "
                f"{state.patient_name}، "
                f"{self._confirmation_party(state, 'voice_ar')}"
                f"يوم {state.slot_date}، "
                f"الساعة {state.slot_time}. "
                "البيانات دي صح؟"
            )

        # ----------------------------------------------------
        # Web/mobile/WhatsApp English
        # ----------------------------------------------------

        elif state.language == "en":

            reply = (
                "Please review the booking:\n\n"
                f"{self._confirmation_party(state, 'text_en')}"
                f"Service: {state.service_name}\n"
                f"Date: {state.slot_date}\n"
                f"Time: {state.slot_time}\n"
                f"Patient: {state.patient_name}\n\n"
                "Would you like me to confirm the booking?"
            )

        # ----------------------------------------------------
        # Web/mobile/WhatsApp Arabic
        # ----------------------------------------------------

        else:

            reply = (
                "راجعي بيانات الحجز:\n\n"
                f"{self._confirmation_party(state, 'text_ar')}"
                f"الخدمة: {state.service_name}\n"
                f"التاريخ: {state.slot_date}\n"
                f"الساعة: {state.slot_time}\n"
                f"المريض: {state.patient_name}\n\n"
                "أأكد الحجز؟"
            )

        return WorkflowResult(
            reply=reply,

            response_type=
                "booking_confirmation",

            data={
                "doctor_name":
                    state.doctor_name,

                "service_name":
                    state.service_name,

                "slot_date":
                    state.slot_date,

                "slot_time":
                    state.slot_time,

                "patient_name":
                    state.patient_name,
            },
        )

    @staticmethod
    def _is_valid_full_patient_name(
            value: str | None,
        ) -> bool:

            normalized = normalize_text(
                value
            )

            if not normalized:
                return False

            tokens = normalized.split()

            # We ask for a FULL patient name.
            if not (
                2 <= len(tokens) <= 6
            ):
                return False

            return all(
                token.isalpha()
                and len(token) >= 2
                for token in tokens
            )


    @staticmethod
    def _is_explicit_patient_name_correction(
        user_message: str,
    ) -> bool:

        normalized = normalize_text(
            user_message
        )

        tokens = set(
            normalized.split()
        )

        correction_markers = {
            "اسم",
            "الاسم",
            "اسمي",
            "المريض",
            "name",
            "patient",
        }

        return bool(
            tokens
            & correction_markers
        )

  
    def _has_confirmation_corrections(
        self,
        *,
        nlu: NLUResult,
        user_message: str,
    ) -> bool:

        entities = (
            nlu.entities
        )

        patient_name_correction = False

        if entities.patient_name:

            valid_name = (
                self
                ._is_valid_full_patient_name(
                    entities.patient_name
                )
            )

            explicit_name_correction = (
                self
                ._is_explicit_patient_name_correction(
                    user_message
                )
            )

            # "لا، آية حمادة"
            denied_current_value = (
                nlu.confirmation
                == "no"
            )

            patient_name_correction = (
                valid_name
                and (
                    explicit_name_correction
                    or denied_current_value
                    or nlu.intent == "provide_patient_name"
                )
            )

        return any(
            (
                patient_name_correction,
                bool(
                    entities.phone
                ),
                bool(
                    entities.doctor_name
                ),
                bool(
                    entities.date_text
                ),
                bool(
                    entities.time_text
                ),
            )
        )

    @staticmethod
    def _confirmation_correction_request_target(
        nlu: NLUResult,
    ) -> str | None:
        """
        Detect a semantic correction request when the user
        wants to change a field but has not supplied the
        replacement value yet.

        Examples:

            "عايزة أغير الميعاد"
            intent=provide_date
            date_text=None

            "رقم الموبايل غلط"
            intent=provide_phone
            phone=None

        This relies on NLU semantics rather than matching
        fixed user phrases.
        """

        entities = nlu.entities

        # -------------------------------------------------
        # If a replacement value is already present,
        # _handle_confirmation_corrections() should handle it.
        # -------------------------------------------------

        if (
            entities.patient_name
            or entities.phone
            or entities.doctor_name
            or entities.date_text
            or entities.time_text
        ):
            return None

        # -------------------------------------------------
        # Semantic correction target inferred from NLU.
        # -------------------------------------------------

        intent_targets = {
            "provide_patient_name":
                "patient_name",

            "provide_phone":
                "phone",

            "provide_doctor":
                "doctor",

            # Egyptian "ميعاد" may refer to the date,
            # time, or appointment schedule generally.
            "provide_date":
                "schedule",

            "provide_time":
                "time",

            "provide_national_id":
                "national_id",
        }

        return intent_targets.get(
            nlu.intent
        )

    
    @staticmethod
    def _restore_create_confirmation(
        state: SessionState,
    ) -> None:

        state.stage = (
            "awaiting_confirmation"
        )

        state.awaiting_confirmation = True

        state.pending_action = (
            "create_booking"
        )

    def _handle_confirmation_correction_request(
    self,
    *,
    state: SessionState,
    target: str,
) -> WorkflowResult:
        """
        User wants to correct booking information but has not
        supplied the new value yet.

        Keep the booking draft alive and ask only for the
        missing corrected value.
        """

        # -------------------------------------------------
        # Keep booking draft alive.
        # -------------------------------------------------

        self._restore_create_confirmation(
            state
        )

        # =================================================
        # PATIENT NAME
        # =================================================

        if target == "patient_name":

            state.stage = (
                "awaiting_patient_name_correction"
            )

            state.awaiting_confirmation = False
            state.pending_action = None

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "تمام، قولي اسم المريض "
                        "الصح كامل."
                    ),

                    en=(
                        "Okay. Please tell me the "
                        "correct patient name."
                    ),
                ),

                response_type=
                    "ask_patient_name_correction",
            )

        # =================================================
        # PHONE
        #
        # Important:
        # move to awaiting_phone so Voice Gateway activates
        # digit collection + sensitive logging.
        # =================================================

        if target == "phone":

            state.stage = (
                "awaiting_phone"
            )

            state.awaiting_confirmation = False
            state.pending_action = None

            state.phone_confirmed = False

            # Do NOT erase state.phone here.
            #
            # _handle_phone() needs the previous value to know
            # whether this is actually a changed phone number.

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "تمام، قولي رقم الموبايل "
                        "الصح من البداية."
                    ),

                    en=(
                        "Okay. Please tell me the correct "
                        "mobile number from the beginning."
                    ),
                ),

                response_type=
                    "ask_phone_correction",
            )

        # =================================================
        # DOCTOR
        # =================================================

        if target == "doctor":

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "تمام، قولي اسم الدكتور "
                        "اللي عايزة تغيري له."
                    ),

                    en=(
                        "Okay. Which doctor would you "
                        "like instead?"
                    ),
                ),

                response_type=
                    "ask_doctor_correction",
            )

        # =================================================
        # DATE / GENERAL APPOINTMENT SCHEDULE
        #
        # "ميعاد" is ambiguous in Egyptian Arabic.
        # Do not assume date or time.
        # =================================================

        if target == "schedule":

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "تمام، قولي اليوم أو الساعة "
                        "الجديدة اللي عايزاها."
                    ),

                    en=(
                        "Okay. Tell me the new date "
                        "or time you would like."
                    ),
                ),

                response_type=
                    "ask_schedule_correction",
            )

        # =================================================
        # TIME
        # =================================================

        if target == "time":

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "تمام، قولي الساعة الجديدة "
                        "اللي عايزاها."
                    ),

                    en=(
                        "Okay. What time would you "
                        "like instead?"
                    ),
                ),

                response_type=
                    "ask_time_correction",
            )

        # =================================================
        # NATIONAL ID
        #
        # National ID changes patient identity.
        # It is NOT treated as a normal booking-field update.
        # =================================================

        if target == "national_id":

            state.national_id = None
            state.patient_id = None
            state.patient_name = None
            state.phone = None
            state.phone_confirmed = False

            state.pending_patient_profile_updates.clear()

            state.awaiting_confirmation = False
            state.pending_action = None

            state.stage = (
                "awaiting_national_id"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "تمام، قولي الرقم القومي "
                        "الصح من البداية."
                    ),

                    en=(
                        "Okay. Please provide the correct "
                        "national ID from the beginning."
                    ),
                ),

                response_type=
                    "ask_national_id_correction",
            )

        # =================================================
        # SAFE FALLBACK
        # =================================================

        return WorkflowResult(
            reply=self._message(
                state.language,

                ar=(
                    "تمام، قولي البيانات "
                    "الصح اللي عايزة تغيريها."
                ),

                en=(
                    "Okay. Tell me what booking "
                    "information you would like to change."
                ),
            ),

            response_type=
                "ask_booking_correction",
        )

    @staticmethod
    def _normalize_egyptian_mobile(
        value: str,
    ) -> str | None:

        translation = str.maketrans(
            {
                "٠": "0",
                "١": "1",
                "٢": "2",
                "٣": "3",
                "٤": "4",
                "٥": "5",
                "٦": "6",
                "٧": "7",
                "٨": "8",
                "٩": "9",
            }
        )

        normalized = (
            value
            .translate(
                translation
            )
            .replace(
                " ",
                "",
            )
            .replace(
                "-",
                "",
            )
        )

        if not re.fullmatch(
            r"01[0125]\d{8}",
            normalized,
        ):

            return None

        return normalized   


    @staticmethod
    def _resolve_correction_date_text(
        value: str,
    ) -> str | None:

        raw = (
            value.strip()
        )

        # Existing state normally contains ISO date.
        try:

            return (
                date
                .fromisoformat(
                    raw
                )
                .isoformat()
            )

        except ValueError:
            pass

        resolved = (
            resolve_date(
                raw
            )
        )

        if resolved is None:

            return None

        return resolved.isoformat()

    
    @staticmethod
    def _resolve_correction_time_candidates(
        value: str,
    ) -> list[str]:

        raw = (
            value.strip()
        )

        # Existing state usually stores HH:MM.
        if re.fullmatch(
            r"\d{2}:\d{2}",
            raw,
        ):

            return [
                raw
            ]

        return (
            resolve_time_candidates(
                raw
            )
        )

    @staticmethod
    def _available_time_values(
        state: SessionState,
    ) -> list[str]:

        return [
            slot.start_time[:5]
            for slot in state.recent_slots
        ]

    async def _persist_pending_patient_profile_updates(
    self,
    *,
    state: SessionState,
) -> WorkflowResult | None:

        # ----------------------------------------------------
        # Nothing to persist
        # ----------------------------------------------------

        if (
            not state.patient_id
            or
            not state.national_id
            or
            not state.pending_patient_profile_updates
        ):

            return None

        updates = (
            state.pending_patient_profile_updates
        )

        patient_name = (
            updates.get(
                "patient_name"
            )
        )

        phone = (
            updates.get(
                "phone"
            )
        )

        # ----------------------------------------------------
        # Persist through MCP → Backend → DB
        # ----------------------------------------------------

        result = await (
            self.tools.call(
                "update_patient_profile",

                patient_id=
                    str(
                        state.patient_id
                    ),

                national_id=
                    state.national_id,

                patient_name=
                    patient_name,

                phone=
                    phone,

                language=(
                    "en"
                    if state.language == "en"
                    else "ar"
                ),

                channel=
                    state.channel,
            )
        )

        # ----------------------------------------------------
        # Backend result must be trusted/structured
        # ----------------------------------------------------

        if not isinstance(
            result,
            dict,
        ):

            self._restore_create_confirmation(
                state
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "حصلت مشكلة وأنا بحفظ "
                        "تعديل بيانات المريض. "
                        "جربي تاني."
                    ),

                    en=(
                        "There was a problem saving "
                        "the patient changes. "
                        "Please try again."
                    ),
                ),

                response_type=
                    "patient_profile_update_error",
            )

        returned_patient_id = (
            result.get(
                "patient_id"
            )
        )

        if (
            returned_patient_id
            and
            str(
                returned_patient_id
            )
            !=
            str(
                state.patient_id
            )
        ):

            self._restore_create_confirmation(
                state
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "حصلت مشكلة وأنا بتأكد "
                        "من بيانات المريض."
                    ),

                    en=(
                        "There was a problem verifying "
                        "the patient information."
                    ),
                ),

                response_type=
                    "patient_profile_update_error",
            )

        # ----------------------------------------------------
        # Refresh state from trusted backend result
        # ----------------------------------------------------

        display_name = (
            result.get(
                "display_name"
            )
        )

        returned_phone = (
            result.get(
                "phone"
            )
        )

        if display_name:

            state.patient_name = (
                display_name
            )

        if returned_phone:

            state.phone = (
                returned_phone
            )

        # ----------------------------------------------------
        # Persist succeeded
        # ----------------------------------------------------

        state.pending_patient_profile_updates.clear()

        return None


    async def _handle_confirmation_corrections(
    self,
    *,
    state: SessionState,
    nlu: NLUResult,
) -> WorkflowResult:

        entities = (
            nlu.entities
        )

        original_doctor_id = (
            state.doctor_id
        )

        original_slot_date = (
            state.slot_date
        )

        original_slot_time = (
            state.slot_time
        )

        original_service_name = (
            state.service_name
        )

        # Lab corrections stay at the booked branch.
        original_lab_slot = (
            self._selected_slot(state)
            if self.is_lab
            else None
        )

        # Confirmation is temporarily suspended while
        # corrections are validated.
        state.awaiting_confirmation = False
        state.pending_action = None

        # ========================================================
        # 1. PATIENT NAME
        # ========================================================

        if entities.patient_name:

            corrected_name = (
                entities
                .patient_name
                .strip()
            )

            if len(
                corrected_name
            ) < 2:

                self._restore_create_confirmation(
                    state
                )

                return WorkflowResult(
                    reply=self._message(
                        state.language,

                        ar=(
                            "اسم المريض مش واضح. "
                            "قولي الاسم الصح كامل."
                        ),

                        en=(
                            "The patient name isn't clear. "
                            "Please provide the correct full name."
                        ),
                    ),

                    response_type=
                        "invalid_patient_name",
                )

            if (
                corrected_name
                != state.patient_name
            ):

                state.patient_name = (
                    corrected_name
                )

                if state.patient_id:

                    state.pending_patient_profile_updates[
                        "patient_name"
                    ] = corrected_name

        # ========================================================
        # 2. PHONE
        # ========================================================

        phone_changed = False

        if entities.phone:

            corrected_phone = (
                self._normalize_egyptian_mobile(
                    entities.phone
                )
            )

            if corrected_phone is None:

                self._restore_create_confirmation(
                    state
                )

                return WorkflowResult(
                    reply=self._message(
                        state.language,

                        ar=(
                            "رقم الموبايل لازم يكون "
                            "11 رقم ويبدأ بـ "
                            "010 أو 011 أو 012 أو 015. "
                            "قولي الرقم الصح من البداية."
                        ),

                        en=(
                            "The mobile number must contain "
                            "11 digits and start with "
                            "010, 011, 012, or 015. "
                            "Please provide the correct number."
                        ),
                    ),

                    response_type=
                        "invalid_phone",
                )

            phone_changed = (
                corrected_phone
                != state.phone
            )

            state.phone = (
                corrected_phone
            )

            if (
                phone_changed
                and
                state.patient_id
            ):

                state.pending_patient_profile_updates[
                    "phone"
                ] = corrected_phone

            # --------------------------------------------
            # Voice must read corrected number back.
            # --------------------------------------------

            if phone_changed:

                state.phone_confirmed = (
                    state.channel
                    != "voice"
                )

        # ========================================================
        # 3. DOCTOR
        # ========================================================

        doctor_changed = False

        # Labs have no doctor to correct.
        if entities.doctor_name and not self.is_lab:

            if not state.specialty_id:

                self._restore_create_confirmation(
                    state
                )

                return WorkflowResult(
                    reply=self._message(
                        state.language,

                        ar=(
                            "لازم أحدد التخصص الأول "
                            "قبل تغيير الدكتور."
                        ),

                        en=(
                            "The specialty must be known "
                            "before changing the doctor."
                        ),
                    ),

                    response_type=
                        "specialty_required",
                )

            # --------------------------------------------
            # Always refresh trusted doctors.
            # --------------------------------------------

            doctors = await (
                self.tools.call(
                    "list_doctors",

                    specialty_id=
                        state.specialty_id,
                )
            )

            apply_tool_observation(
                state=state,

                tool_name=
                    "list_doctors",

                data=
                    doctors,
            )

            doctor = (
                self._find_doctor(
                    query=
                        entities.doctor_name,

                    state=
                        state,
                )
            )

            if doctor is None:

                self._restore_create_confirmation(
                    state
                )

                doctor_names = []

                for item in (
                    state.recent_doctors
                ):

                    if (
                        state.language
                        == "en"
                    ):

                        name = (
                            item.full_name_en
                            or
                            item.full_name_ar
                        )

                    else:

                        name = (
                            item.full_name_ar
                            or
                            item.full_name_en
                        )

                    if name:

                        doctor_names.append(
                            name
                        )

                return WorkflowResult(
                    reply=self._message(
                        state.language,

                        ar=(
                            "مش لاقي الدكتور ده "
                            "ضمن الدكاترة المتاحين. "
                            "المتاح: "
                            + "، ".join(
                                doctor_names
                            )
                        ),

                        en=(
                            "I couldn't find that doctor. "
                            "Available doctors are: "
                            + ", ".join(
                                doctor_names
                            )
                        ),
                    ),

                    response_type=
                        "doctor_not_found",

                    data={
                        "available_doctors":
                            doctor_names,
                    },
                )

            doctor_changed = (
                str(
                    original_doctor_id
                )
                !=
                str(
                    doctor.id
                )
            )

            state.doctor_id = (
                doctor.id
            )

            if state.language == "en":

                state.doctor_name = (
                    doctor.full_name_en
                    or
                    doctor.full_name_ar
                )

            else:

                state.doctor_name = (
                    doctor.full_name_ar
                    or
                    doctor.full_name_en
                )

            # Doctor owns the slot.
            # Old slot cannot be trusted anymore.
            if doctor_changed:

                state.slot_id = None
                state.slot_time = None

                state.recent_slots = []

        # ========================================================
        # 4 + 5.
        #
        # SCHEDULE DEPENDENCIES
        #
        # Revalidate if:
        #
        # - doctor changed
        # - date corrected
        # - time corrected
        # ========================================================

        schedule_changed = (
            doctor_changed
            or
            bool(
                entities.date_text
            )
            or
            bool(
                entities.time_text
            )
        )

        if schedule_changed:

            if not state.doctor_id and not self.is_lab:

                self._restore_create_confirmation(
                    state
                )

                return WorkflowResult(
                    reply=self._message(
                        state.language,

                        ar=(
                            "لازم نحدد الدكتور "
                            "الأول."
                        ),

                        en=(
                            "We need to select "
                            "the doctor first."
                        ),
                    ),

                    response_type=
                        "doctor_required",
                )

            # Explicit correction wins.
            # Otherwise try to preserve previous date.
            # ====================================================

            target_date_value = (
                entities.date_text
                or
                original_slot_date
            )

            if not target_date_value:

                state.slot_id = None
                state.slot_date = None
                state.slot_time = None

                state.stage = (
                    "awaiting_date"
                )

                return WorkflowResult(
                    reply=self._message(
                        state.language,

                        ar=(
                            "تمام، اليوم الصح إيه؟"
                        ),

                        en=(
                            "Okay. What is the "
                            "correct date?"
                        ),
                    ),

                    response_type=
                        "ask_date",
                )

            resolved_date_text = (
                self._resolve_correction_date_text(
                    target_date_value
                )
            )

            if resolved_date_text is None:

                self._restore_create_confirmation(
                    state
                )

                return WorkflowResult(
                    reply=self._message(
                        state.language,

                        ar=(
                            "مش قادر أحدد التاريخ ده. "
                            "قولي اليوم أو التاريخ تاني."
                        ),

                        en=(
                            "I couldn't understand that date. "
                            "Please provide the correct date again."
                        ),
                    ),

                    response_type=
                        "invalid_date",
                )

            # ====================================================
            # Reload REAL slots from backend.
            # ====================================================

            slot_filter = (
                {
                    "doctor_id":
                        state.doctor_id,
                }
                if not self.is_lab
                else {
                    "branch_id":
                        original_lab_slot.branch_id,
                }
                if original_lab_slot is not None
                else {}
            )

            slots = await (
                self.tools.call(
                    "list_available_slots",

                    **slot_filter,

                    slot_date=
                        resolved_date_text,

                    limit=100,
                )
            )

            apply_tool_observation(
                state=state,

                tool_name=
                    "list_available_slots",

                data=
                    slots,
            )

            if self.is_lab:
                state.recent_slots = [
                    slot
                    for slot in state.recent_slots
                    if slot.doctor_id is None
                ]

            state.slot_date = (
                resolved_date_text
            )

            state.slot_id = None
            state.slot_time = None

            # ====================================================
            # No slots
            # ====================================================

            if not state.recent_slots:

                state.stage = (
                    "awaiting_date"
                )

                return WorkflowResult(
                    reply=self._message(
                        state.language,

                        ar=(
                            f"مفيش مواعيد متاحة "
                            f"{'' if self.is_lab else 'مع ' + str(state.doctor_name) + ' '}"
                            f"يوم "
                            f"{resolved_date_text}. "
                            "تحبي يوم تاني؟"
                        ),

                        en=(
                            f"There are no available slots "
                            f"{'' if self.is_lab else 'with ' + str(state.doctor_name) + ' '}"
                            f"on "
                            f"{resolved_date_text}. "
                            "Would you like another date?"
                        ),
                    ),

                    response_type=
                        "no_slots",

                    data={
                        "date":
                            resolved_date_text,

                        "doctor_id":
                            state.doctor_id,
                    },
                )

            available_times = (
                self._available_time_values(
                    state
                )
            )

            # ====================================================
            # Determine time.
            #
            # Explicit correction wins.
            # Otherwise try to preserve old time.
            # ====================================================

            target_time_value = (
                entities.time_text
                or
                original_slot_time
            )

            if not target_time_value:

                state.stage = (
                    "awaiting_time"
                )

                return WorkflowResult(
                    reply=self._message(
                        state.language,

                        ar=(
                            "تمام، المواعيد المتاحة هي: "
                            + "، ".join(
                                available_times
                            )
                            + ". الساعة الصح كام؟"
                        ),

                        en=(
                            "The available times are: "
                            + ", ".join(
                                available_times
                            )
                            + ". What is the correct time?"
                        ),
                    ),

                    response_type=
                        "ask_time",

                    data={
                        "available_times":
                            available_times,
                    },
                )

            time_candidates = (
                self._resolve_correction_time_candidates(
                    target_time_value
                )
            )

            matches = [
                slot
                for slot
                in state.recent_slots
                if (
                    slot.start_time[:5]
                    in time_candidates
                )
            ]

            # ====================================================
            # Requested time isn't available.
            # ====================================================

            if not matches:

                state.stage = (
                    "awaiting_time"
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
                            + ". اختاري ميعاد تاني."
                        ),

                        en=(
                            "That time isn't available. "
                            "The available times are: "
                            + ", ".join(
                                available_times
                            )
                            + ". Please choose another time."
                        ),
                    ),

                    response_type=
                        "time_not_available",

                    data={
                        "requested_time":
                            target_time_value,

                        "available_times":
                            available_times,
                    },
                )

            # ====================================================
            # Ambiguous time.
            # ====================================================

            if len(
                matches
            ) > 1:

                state.stage = (
                    "awaiting_time"
                )

                matching_times = [
                    slot.start_time[:5]
                    for slot
                    in matches
                ]

                return WorkflowResult(
                    reply=self._message(
                        state.language,

                        ar=(
                            "لقيت أكتر من ميعاد ممكن: "
                            + "، ".join(
                                matching_times
                            )
                            + ". تقصدي أنهي واحد؟"
                        ),

                        en=(
                            "I found more than one matching time: "
                            + ", ".join(
                                matching_times
                            )
                            + ". Which one do you mean?"
                        ),
                    ),

                    response_type=
                        "ambiguous_time",

                    data={
                        "matching_times":
                            matching_times,
                    },
                )

            # ====================================================
            # Exactly one REAL slot.
            # ====================================================

            selected_slot = (
                matches[0]
            )

            state.slot_id = (
                selected_slot.id
            )

            state.slot_date = (
                selected_slot.slot_date
            )

            state.slot_time = (
                selected_slot
                .start_time[:5]
            )

        # ========================================================
        # DOCTOR CHANGE → SERVICE REVALIDATION
        #
        # Never assume that the old service is offered
        # by the newly selected doctor.
        # ========================================================

        if doctor_changed:

            services = await (
                self.tools.call(
                    "list_services",

                    doctor_id=
                        state.doctor_id,

                    limit=100,
                )
            )

            apply_tool_observation(
                state=state,

                tool_name=
                    "list_services",

                data=
                    services,
            )

            # ----------------------------------------------------
            # New doctor has no services.
            # ----------------------------------------------------

            if not state.recent_services:

                state.service_id = None
                state.service_name = None

                state.stage = (
                    "awaiting_service"
                )

                return WorkflowResult(
                    reply=self._message(
                        state.language,

                        ar=(
                            "الدكتور الجديد مفيش له "
                            "خدمة متاحة حالياً."
                        ),

                        en=(
                            "There is currently no available "
                            "service for the new doctor."
                        ),
                    ),

                    response_type=
                        "no_services",
                )

            # ----------------------------------------------------
            # Try to preserve current service.
            # ----------------------------------------------------

            service = None

            if original_service_name:

                service = (
                    self._find_service(
                        query=
                            original_service_name,

                        state=
                            state,
                    )
                )

            # ----------------------------------------------------
            # Old service isn't valid for new doctor.
            # Ask user rather than silently switching service.
            # ----------------------------------------------------

            if service is None:

                state.service_id = None
                state.service_name = None

                state.stage = (
                    "awaiting_service"
                )

                service_names = []

                for item in (
                    state.recent_services
                ):

                    if state.language == "en":

                        name = (
                            item.name_en
                            or
                            item.name_ar
                        )

                    else:

                        name = (
                            item.name_ar
                            or
                            item.name_en
                        )

                    if name:

                        service_names.append(
                            name
                        )

                return WorkflowResult(
                    reply=self._message(
                        state.language,

                        ar=(
                            "الخدمة القديمة مش متاحة "
                            "مع الدكتور الجديد. "
                            "المتاح: "
                            + "، ".join(
                                service_names
                            )
                            + ". تحبي أنهي خدمة؟"
                        ),

                        en=(
                            "The previous service isn't available "
                            "with the new doctor. "
                            "Available services are: "
                            + ", ".join(
                                service_names
                            )
                            + ". Which service would you like?"
                        ),
                    ),

                    response_type=
                        "ask_service",

                    data={
                        "services":
                            service_names,
                    },
                )

            state.service_id = (
                service.id
            )

            if state.language == "en":

                state.service_name = (
                    service.name_en
                    or
                    service.name_ar
                )

            else:

                state.service_name = (
                    service.name_ar
                    or
                    service.name_en
                )

        # ========================================================
        # ALL CORRECTIONS ARE VALID
        #
        # If phone changed in Voice:
        #
        # _prepare_confirmation()
        #        ↓
        # awaiting_phone_confirmation
        #
        # Otherwise:
        #
        # _prepare_confirmation()
        #        ↓
        # awaiting_confirmation
        # ========================================================

        # ========================================================
        # PERSIST PATIENT PROFILE CHANGES
        #
        # Voice phone corrections MUST wait for spoken
        # read-back confirmation before database persistence.
        # ========================================================

        waiting_for_voice_phone_confirmation = (
            state.channel == "voice"
            and
            "phone"
            in state.pending_patient_profile_updates
            and
            not state.phone_confirmed
        )

        if (
            state.pending_patient_profile_updates
            and
            not waiting_for_voice_phone_confirmation
        ):

            persistence_error = await (
                self._persist_pending_patient_profile_updates(
                    state=state,
                )
            )

            if persistence_error is not None:

                return persistence_error


        return self._prepare_confirmation(
            state=state,
        )
    # ========================================================
    # BOOKING CONFIRMATION
    # ========================================================

    async def _handle_confirmation(
    self,
    *,
    state: SessionState,
    nlu: NLUResult,
    user_message: str,
) -> WorkflowResult:
        
        if (
            nlu.intent == "provide_patient_name"
            or
            nlu.entities.patient_name
        ):

            return (
                self._handle_confirmation_correction_request(
                    state=state,
                    target="patient_name",
                )
            )

        if self._has_confirmation_corrections(
            nlu=nlu,
            user_message=user_message,
        ):

            return await (
                self._handle_confirmation_corrections(
                    state=state,
                    nlu=nlu,
                )
            )

        correction_target = (
            self._confirmation_correction_request_target(
                nlu
            )
        )

        if correction_target is not None:

            return (
                self._handle_confirmation_correction_request(
                    state=state,
                    target=correction_target,
                )
            )

        # ========================================================
        # 3. EXPLICIT DENY
        # ========================================================

        if (
            nlu.intent == "deny_action"
            or
            nlu.confirmation == "no"
        ):

            state.awaiting_confirmation = (
                False
            )

            state.pending_action = None

            state.stage = (
                "booking_cancelled_before_create"
            )

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "تمام، مش هأكد الحجز."
                    ),

                    en=(
                        "Okay, I won't confirm "
                        "the booking."
                    ),
                ),

                response_type=
                    "booking_not_confirmed",
            )

        # ========================================================
        # 4. NOT A CONFIRMATION
        # ========================================================

        if not (
            nlu.intent == "confirm_action"
            or
            nlu.confirmation == "yes"
        ):

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "ممكن تأكدي البيانات، "
                        "أو تقوليلي إيه اللي "
                        "عايزة تغيريه."
                    ),

                    en=(
                        "You can confirm the booking "
                        "or tell me what you would "
                        "like to change."
                    ),
                ),

                response_type=
                    "ask_confirmation",
            )
        # ----------------------------------------------------
        # SAFETY CHECK
        # ----------------------------------------------------

        if (
            not state.awaiting_confirmation
            or
            state.pending_action
            != "create_booking"
        ):

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "مفيش حجز جاهز "
                        "للتأكيد حالياً."
                    ),

                    en=(
                        "There is no booking "
                        "ready for confirmation."
                    ),
                ),

                response_type=
                    "no_pending_booking",
            )

        required = {
            "national_id":
                state.national_id,

            "slot_id":
                state.slot_id,

            "service_id":
                state.service_id,

            "patient_id":
                state.patient_id,
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
                        "فيه بيانات ناقصة "
                        "ومينفعش أنفذ الحجز."
                    ),

                    en=(
                        "Some required information "
                        "is missing, so the booking "
                        "cannot be created."
                    ),
                ),

                response_type=
                    "booking_data_incomplete",

                data={
                    "missing":
                        missing,
                },
            )

        # ----------------------------------------------------
        # Voice phone safety
        # ----------------------------------------------------

        if (
            state.channel == "voice"
            and
            not state.phone_confirmed
        ):

            state.stage = (
                "awaiting_phone_confirmation"
            )

            state.awaiting_confirmation = False
            state.pending_action = None

            return self._phone_confirmation_result(
                state=state,
            )


        # ----------------------------------------------------
        # Final persistence guard
        #
        # Never create a booking while patient corrections
        # are still waiting to be persisted.
        # ----------------------------------------------------

        if (
            state.pending_patient_profile_updates
        ):

            persistence_error = await (
                self._persist_pending_patient_profile_updates(
                    state=state,
                )
            )

            if persistence_error is not None:

                return persistence_error
    
        idempotency_key = str(
            uuid4()
        )

        # ----------------------------------------------------
        # CREATE BOOKING
        # ----------------------------------------------------

        result = await (
            self.tools.call(
                "create_booking",

                national_id=
                    state.national_id,

                slot_id=
                    state.slot_id,

                service_id=
                    state.service_id,

                idempotency_key=
                    idempotency_key,

                channel=
                    state.channel,

                session_reference=
                    state.session_id,
            )
        )

        if not isinstance(
            result,
            dict,
        ):

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "الحجز متأكدش من النظام. "
                        "جربي تاني."
                    ),

                    en=(
                        "The booking wasn't confirmed "
                        "by the system. Please try again."
                    ),
                ),

                response_type=
                    "booking_create_error",

                data={
                    "backend_result":
                        result,
                },
            )

        appointment_reference = (
            result.get(
                "appointment_reference"
            )
        )

        if (
            not appointment_reference
            and
            isinstance(
                result.get(
                    "appointment"
                ),
                dict,
            )
        ):

            appointment_reference = (
                result[
                    "appointment"
                ].get(
                    "appointment_reference"
                )
                or
                result[
                    "appointment"
                ].get(
                    "reference"
                )
            )

        if not appointment_reference:

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "النظام مرجعش تأكيد واضح "
                        "للحجز، فمش هعتبره تم."
                    ),

                    en=(
                        "The system did not return "
                        "a clear booking confirmation, "
                        "so I won't mark it as completed."
                    ),
                ),

                response_type=
                    "booking_create_unconfirmed",

                data={
                    "backend_result":
                        result,
                },
            )

        state.appointment_reference = (
            appointment_reference
        )

        state.awaiting_confirmation = False
        state.pending_action = None

        state.stage = (
            "booking_completed"
        )

        state.recent_slots = []

        return WorkflowResult(
            reply=self._message(
                state.language,

                ar=(
                    (
                        "تمام، حجزك اتأكد "
                        "وهبعتلك باقي التفاصيل على واتساب."
                    )
                    if state.channel == "voice"
                    else
                    (
                        "تم تأكيد الحجز بنجاح. "
                        f"رقم الحجز: "
                        f"{appointment_reference}"
                    )
                ),

                en=(
                    (
                        "Your booking is confirmed. "
                        "I'll send the remaining details "
                        "on WhatsApp."
                    )
                    if state.channel == "voice"
                    else
                    (
                        "Your booking has been "
                        "confirmed successfully. "
                        f"Booking reference: "
                        f"{appointment_reference}"
                    )
                ),
            ),

            response_type=
                "booking_created",

            data={
                "appointment_reference":
                    appointment_reference,

                "backend_result":
                    result,
            },
        )

    # ========================================================
    # RESOLVERS
    # ========================================================

    def _find_specialty(
        self,
        *,
        query: str,
        specialties: list,
    ) -> dict | None:

        # ----------------------------------------------------
        # Exact match
        # ----------------------------------------------------

        for item in specialties:

            if not isinstance(
                item,
                dict,
            ):
                continue

            candidates = [
                item.get(
                    "name_ar"
                ),
                item.get(
                    "name_en"
                ),
                item.get(
                    "code"
                ),
            ]

            for candidate in candidates:

                if (
                    normalize_text(
                        query
                    )
                    ==
                    normalize_text(
                        candidate
                    )
                ):

                    return item

        # ----------------------------------------------------
        # Partial match
        # ----------------------------------------------------

        matches = []

        for item in specialties:

            if not isinstance(
                item,
                dict,
            ):
                continue

            candidates = [
                item.get(
                    "name_ar"
                ),
                item.get(
                    "name_en"
                ),
                item.get(
                    "code"
                ),
            ]

            if any(
                text_matches(
                    query,
                    candidate,
                )
                for candidate
                in candidates
            ):

                matches.append(
                    item
                )

        if len(matches) == 1:

            return matches[0]

        return None


    def _find_doctor(
    self,
    *,
    query: str,
    state: SessionState,
):

        query_norm = normalize_doctor_name(
            query
        )

        if not query_norm:
            return None

        # ----------------------------------------------------
        # Exact match
        # ----------------------------------------------------

        for doctor in state.recent_doctors:

            candidates = [
                doctor.full_name_ar,
                doctor.full_name_en,
            ]

            for candidate in candidates:

                if (
                    query_norm
                    == normalize_doctor_name(
                        candidate
                    )
                ):
                    return doctor

        # ----------------------------------------------------
        # Unique partial match
        # ----------------------------------------------------

        matches = []

        for doctor in state.recent_doctors:

            candidates = [
                doctor.full_name_ar,
                doctor.full_name_en,
            ]

            for candidate in candidates:

                candidate_norm = (
                    normalize_doctor_name(
                        candidate
                    )
                )

                if (
                    candidate_norm
                    and (
                        query_norm
                        in candidate_norm
                        or candidate_norm
                        in query_norm
                    )
                ):
                    matches.append(doctor)
                    break

        if len(matches) == 1:
            return matches[0]

        return None

    def _find_service(
        self,
        *,
        query: str,
        state: SessionState,
    ):

        # ----------------------------------------------------
        # Exact match
        # ----------------------------------------------------

        for service in (
            state.recent_services
        ):

            candidates = [
                service.name_ar,
                service.name_en,
                service.code,
            ]

            for candidate in candidates:

                if (
                    normalize_text(
                        query
                    )
                    ==
                    normalize_text(
                        candidate
                    )
                ):

                    return service

        # ----------------------------------------------------
        # Partial match
        # ----------------------------------------------------

        matches = []

        for service in (
            state.recent_services
        ):

            candidates = [
                service.name_ar,
                service.name_en,
                service.code,
            ]

            if any(
                text_matches(
                    query,
                    candidate,
                )
                for candidate
                in candidates
            ):

                matches.append(
                    service
                )

        if len(matches) == 1:

            return matches[0]

        return None

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