from __future__ import annotations
from uuid import uuid4
import re
import unicodedata
from typing import Any

from medmind.core.tool_executor import (
    MCPToolExecutor,
)

from medmind.state.models import (
    SessionState,
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

    return [
        value
    ]


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


# ============================================================
# BOOKING WORKFLOW
# ============================================================

class BookingWorkflow:

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

        # ----------------------------------------------------
        # Detect booking request
        # ----------------------------------------------------

        is_booking_request = (
            nlu.intent == "book_appointment"
            or nlu.operation_type == "book_appointment"
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
                response_type=
                    "not_booking",
            )

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
            == "awaiting_phone"
        ):

            return await (
                self._handle_phone(
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
    # NEW
    # ========================================================

    async def _handle_new(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        specialty_name = (
            nlu.entities
            .specialty_name
        )

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

        specialty_name = (
            nlu.entities
            .specialty_name
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
            )
        )

    async def _resolve_specialty(
        self,
        *,
        state: SessionState,
        specialty_name: str,
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
                        + "، ".join(names)
                    ),
                    en=(
                        "I couldn't find that "
                        "specialty. Available "
                        "specialties: "
                        + ", ".join(names)
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

        # ----------------------------------------------------
        # Save locally
        # ----------------------------------------------------

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

        found = lookup_result.get(
            "found"
        )

        patient = lookup_result.get(
            "patient"
        )

        # ----------------------------------------------------
        # NEW PATIENT
        # ----------------------------------------------------

        if (
            found is False
            or patient is None
        ):

            state.patient_id = None
            state.patient_name = None
            state.phone = None

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
            and isinstance(
                patient,
                dict,
            )
        ):

            patient_id = (
                patient.get(
                    "patient_id"
                )
            )

            patient_name = (
                patient.get(
                    "display_name"
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
    # BOOKING CONFIRMATION
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
            or nlu.confirmation == "no"
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

        # ----------------------------------------------------
        # NOT A CONFIRMATION
        # ----------------------------------------------------

        if not (
            nlu.intent == "confirm_action"
            or nlu.confirmation == "yes"
        ):

            return WorkflowResult(
                reply=self._message(
                    state.language,

                    ar=(
                        "تحبي أأكد الحجز؟ "
                        "قولي أيوه أو لأ."
                    ),

                    en=(
                        "Would you like me to "
                        "confirm the booking? "
                        "Please answer yes or no."
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
            or state.pending_action
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
        # IDEMPOTENCY KEY
        #
        # Generated by Python, never by the LLM.
        # ----------------------------------------------------

        idempotency_key = str(
            uuid4()
        )

        # ----------------------------------------------------
        # CREATE BOOKING THROUGH MCP → BACKEND
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
                    "web",

                session_reference=
                    state.session_id,
            )
        )

        # ----------------------------------------------------
        # IMPORTANT
        #
        # Don't claim success unless backend returned
        # an actual appointment reference.
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Find appointment reference
        # ----------------------------------------------------

        appointment_reference = (
            result.get(
                "appointment_reference"
            )
        )

        # Some APIs wrap the appointment object.
        if (
            not appointment_reference
            and isinstance(
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

        # ----------------------------------------------------
        # BACKEND DID NOT CONFIRM CREATION
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        state.appointment_reference = (
            appointment_reference
        )

        state.awaiting_confirmation = (
            False
        )

        state.pending_action = None

        state.stage = (
            "booking_completed"
        )
        state.recent_slots = []

        return WorkflowResult(
            reply=self._message(
                state.language,

                ar=(
                    "تم تأكيد الحجز بنجاح. "
                    f"رقم الحجز: "
                    f"{appointment_reference}"
                ),

                en=(
                    "Your booking has been "
                    "confirmed successfully. "
                    f"Booking reference: "
                    f"{appointment_reference}"
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
        # Structural normalization
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
                        "ممكن تكتبيه تاني؟"
                    ),

                    en=(
                        "The phone number doesn't "
                        "look valid. Please send "
                        "it again."
                    ),
                ),

                response_type=
                    "invalid_phone",
            )

        state.phone = (
            normalized_phone
        )

        # ----------------------------------------------------
        # Required patient data
        # ----------------------------------------------------

        if (
            not state.national_id
            or not state.patient_name
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

        # ----------------------------------------------------
        # Resolve/create patient through backend
        # ----------------------------------------------------

        preferred_language = (
            "en"
            if state.language == "en"
            else "ar"
        )

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
                    "web",
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

        patient = result.get(
            "patient"
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
        # Save trusted backend result
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

        state.stage = (
            "awaiting_confirmation"
        )

        state.awaiting_confirmation = (
            True
        )

        state.pending_action = (
            "create_booking"
        )

        if state.language == "en":

            reply = (
                "Please review the booking:\n\n"
                f"Doctor: {state.doctor_name}\n"
                f"Service: {state.service_name}\n"
                f"Date: {state.slot_date}\n"
                f"Time: {state.slot_time}\n"
                f"Patient: {state.patient_name}\n\n"
                "Would you like me to confirm the booking?"
            )

        else:

            reply = (
                "راجعي بيانات الحجز:\n\n"
                f"الدكتور: {state.doctor_name}\n"
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
    # ========================================================
    # DOCTOR
    # ========================================================

    async def _handle_doctor(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        doctor_name = (
            nlu.entities
            .doctor_name
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
            query=doctor_name,
            state=state,
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

        # ----------------------------------------------------
        # Save selected doctor
        # ----------------------------------------------------

        state.doctor_id = (
            doctor.id
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
    # SERVICE
    # ========================================================

    async def _handle_service(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        service_name = (
            nlu.entities
            .service_name
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
        # ----------------------------------------------------
        # PATIENT ALREADY KNOWN IN THIS SESSION
        # ----------------------------------------------------

        if (
            state.patient_id
            and state.national_id
        ):

            return self._prepare_confirmation(
                state=state,
            )


        state.stage = (
            "awaiting_national_id"
        )

        return WorkflowResult(
            reply=self._message(
                state.language,

                ar=(
                    f"تمام، اخترتي "
                    f"{state.service_name}. "
                    "ممكن الرقم القومي "
                    "عشان نكمل الحجز؟"
                ),

                en=(
                    f"Great, you selected "
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

        date_text = (
            nlu.entities
            .date_text
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

        # Remember requested date
        state.slot_date = (
            resolved_date_text
        )

        # No selected slot yet
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

        # ----------------------------------------------------
        # Next stage
        # ----------------------------------------------------

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

    async def _handle_time(
        self,
        *,
        state: SessionState,
        nlu: NLUResult,
    ) -> WorkflowResult:

        time_text = (
            nlu.entities
            .time_text
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
        # Match ONLY against trusted available slots
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
        # No real available slot matched
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
                    f"That time isn't available. "
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
        # Ambiguous:
        #
        # User said "1" and somehow both
        # 01:00 and 13:00 are available.
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
        # Exactly one REAL slot matched
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
            selected_slot.start_time[
                :5
            ]
        )
        # ----------------------------------------------------
        # Load services valid for selected doctor
        # ----------------------------------------------------

        return await (
            self._load_doctor_services(
                state=state,
            )
        )

    # ========================================================
    # LOAD DOCTOR SERVICES
    # ========================================================

    async def _load_doctor_services(
        self,
        *,
        state: SessionState,
    ) -> WorkflowResult:

        # ----------------------------------------------------
        # Doctor required
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
        # Load trusted services from backend
        # ----------------------------------------------------

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
                        "مش لاقي خدمة متاحة "
                        "للدكتور ده حالياً."
                    ),

                    en=(
                        "I couldn't find an "
                        "available service for "
                        "this doctor."
                    ),
                ),

                response_type=
                    "no_services",
            )

        # ----------------------------------------------------
        # Exactly one service
        # → auto-select
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

            # ------------------------------------------------
            # Known patient in current session
            # → skip identity collection
            # ------------------------------------------------

            if (
                state.patient_id
                and state.national_id
            ):

                return self._prepare_confirmation(
                    state=state,
                )

            # ------------------------------------------------
            # Patient not known yet
            # ------------------------------------------------

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

        # ----------------------------------------------------
        # Multiple services
        # → ask user to select
        # ----------------------------------------------------

        state.stage = (
            "awaiting_service"
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
        # Exact match first
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
        # Substring match second
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

        # ----------------------------------------------------
        # Exact match
        # ----------------------------------------------------

        for doctor in (
            state.recent_doctors
        ):

            candidates = [
                doctor.full_name_ar,
                doctor.full_name_en,
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
                    return doctor

        # ----------------------------------------------------
        # Partial match
        # ----------------------------------------------------

        matches = []

        for doctor in (
            state.recent_doctors
        ):

            candidates = [
                doctor.full_name_ar,
                doctor.full_name_en,
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
                    doctor
                )

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
        # Exact
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
        # Partial
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
