from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ConversationChannel = Literal[
    "web",
    "mobile",
    "voice",
    "whatsapp",
]

Language = Literal[
    "ar",
    "en",
    "mixed",
]


OperationType = Literal[
    "book_appointment",
    "cancel_appointment",
    "reschedule_appointment",
    "lookup_appointment",
    "search_appointments",
]


# ============================================================
# READ CONTEXT
# ============================================================

class SpecialtySnapshot(
    BaseModel
):
    id: str
    code: str

    name_ar: str | None = None
    name_en: str | None = None


class DoctorSnapshot(
    BaseModel
):
    id: str

    specialty_id: str

    full_name_ar: str | None = None
    full_name_en: str | None = None

    specialty_name_ar: str | None = None
    specialty_name_en: str | None = None

    consultation_fee: str | None = None

    experience_years: int | None = None

    rating_avg: str | None = None

    review_count: int | None = None


class ServiceSnapshot(
    BaseModel
):
    id: str
    code: str

    name_ar: str | None = None
    name_en: str | None = None

    voice_label_ar: str | None = None
    voice_label_en: str | None = None
    voice_featured_rank: int | None = None

    price: str | None = None

    service_type: str | None = None

    price: str | None = None

    service_type: str | None = None



class AppointmentSnapshot(
    BaseModel
):
    appointment_reference: str

    doctor_name: str | None = None
    service_name: str | None = None
    specialty_name: str | None = None
    branch_name: str | None = None

    scheduled_date: str | None = None
    start_time: str | None = None
    end_time: str | None = None

    status: str | None = None

class SlotSnapshot(
    BaseModel
):
    id: str

    # None for branch-level lab slots.
    doctor_id: str | None = None

    branch_id: str

    branch_name_ar: str | None = None

    branch_name_en: str | None = None

    slot_date: str

    start_time: str

    end_time: str

    status: str
# ============================================================
# SESSION STATE
# ============================================================

class SessionState(
    BaseModel
):
    channel: ConversationChannel 
    session_id: str

    tenant_id: str

    language: Language = "ar"

    # --------------------------------------------------------
    # Current workflow
    # --------------------------------------------------------

    operation_type: (
        OperationType
        | None
    ) = None

    stage: str = "new"

    pending_patient_profile_updates: dict[
        str,
        str,
    ] = Field(
        default_factory=dict,
    )

    pending_operation_entities: dict[
        str,
        str,
    ] = Field(
        default_factory=dict,
    )
    # --------------------------------------------------------
    # Selected specialty
    # --------------------------------------------------------

    specialty_id: (
        str
        | None
    ) = None

    specialty_name: (
        str
        | None
    ) = None

    # --------------------------------------------------------
    # Selected doctor
    # --------------------------------------------------------

    doctor_id: (
        str
        | None
    ) = None

    doctor_name: (
        str
        | None
    ) = None

    # --------------------------------------------------------
    # Selected service
    # --------------------------------------------------------

    service_id: (
        str
        | None
    ) = None

    service_name: (
        str
        | None
    ) = None

    # --------------------------------------------------------
    # Selected slot
    # --------------------------------------------------------

    slot_id: (
        str
        | None
    ) = None

    slot_date: (
        str
        | None
    ) = None

    slot_time: (
        str
        | None
    ) = None



    new_slot_id: (
        str
        | None
    ) = None

    new_slot_date: (
        str
        | None
    ) = None

    new_slot_time: (
        str
        | None
    ) = None
    # --------------------------------------------------------
    # Patient
    # --------------------------------------------------------

    patient_id: str | None = None

    national_id: str | None = None

    patient_name: str | None = None

    phone: str | None = None

    phone_confirmed: bool = False

    # --------------------------------------------------------
    # Appointment
    # --------------------------------------------------------

    appointment_reference: (
        str
        | None
    ) = None

    candidate_appointments: list[
        AppointmentSnapshot
    ] = Field(
        default_factory=list
    )
    # --------------------------------------------------------
    # Confirmation
    # --------------------------------------------------------

    awaiting_confirmation: bool = False

    pending_action: (
        str
        | None
    ) = None

    # --------------------------------------------------------
    # Read memory
    # --------------------------------------------------------

    recent_specialties: list[
        SpecialtySnapshot
    ] = Field(
        default_factory=list
    )

    recent_doctors: list[
        DoctorSnapshot
    ] = Field(
        default_factory=list
    )

    recent_services: list[
        ServiceSnapshot
    ] = Field(
        default_factory=list
    )
    recent_slots: list[
        SlotSnapshot
    ] = Field(
        default_factory=list
    )

    conversation_specialty_id: (
        str
        | None
    ) = None

    conversation_specialty_name: (
        str
        | None
    ) = None

    conversation_doctor_id: (
        str
        | None
    ) = None

    conversation_doctor_name: (
        str
        | None
    ) = None

    conversation_service_id: (
        str
        | None
    ) = None

    conversation_service_name: (
        str
        | None
    ) = None

    conversation_date_text: str | None = None

    conversation_focus_capability: (
        str
        | None
    ) = None
    # --------------------------------------------------------
    # Safe LLM context
    # --------------------------------------------------------

    def safe_llm_context(
        self,
    ) -> dict:

        return {
            "language":
                self.language,

            "operation_type":
                self.operation_type,

            "stage":
                self.stage,

            "specialty_id":
                self.specialty_id,

            "specialty_name":
                self.specialty_name,

            "doctor_id":
                self.doctor_id,

            "doctor_name":
                self.doctor_name,

            "service_id":
                self.service_id,

            "conversation_date_text":
                self.conversation_date_text,
                
            "service_name":
                self.service_name,

            "slot_id":
                self.slot_id,

            "slot_date":
                self.slot_date,

            "slot_time":
                self.slot_time,

            "new_slot_id":
                self.new_slot_id,

            "new_slot_date":
                self.new_slot_date,

            "new_slot_time":
                self.new_slot_time,
                
            "appointment_reference":
                self.appointment_reference,

            "awaiting_confirmation":
                self.awaiting_confirmation,

            "pending_action":
                self.pending_action,

            "pending_operation_entities":
                dict(
                    self.pending_operation_entities
                ),    

            "conversation_specialty_id":
                self.conversation_specialty_id,

            "conversation_specialty_name":
                self.conversation_specialty_name,

            "conversation_doctor_id":
                self.conversation_doctor_id,

            "conversation_doctor_name":
                self.conversation_doctor_name,

            "conversation_service_id":
                self.conversation_service_id,

            "conversation_service_name":
                self.conversation_service_name,

            "conversation_focus_capability":
                self.conversation_focus_capability,    

            "recent_doctors": [
                doctor.model_dump()
                for doctor
                in self.recent_doctors
            ],

            "recent_services": [
                service.model_dump()
                for service
                in self.recent_services
            ],
            "recent_slots": [
                slot.model_dump()
                for slot
                in self.recent_slots
            ],
        }

    # --------------------------------------------------------
    # Reset operation
    # --------------------------------------------------------

    def forget_identity_proof(
        self,
    ) -> None:
        """Drop the national ID kept from an earlier operation.

        Cancelling or rescheduling must be authorised by a national ID the
        caller gives during that operation, never by one remembered from
        a previous booking, cancellation or reschedule.
        """

        self.national_id = None

    def reset_operation(
    self,
    *,
    preserve_patient: bool = True,
) -> None:

        patient_id = self.patient_id
        national_id = self.national_id
        patient_name = self.patient_name
        phone = self.phone
        phone_confirmed = self.phone_confirmed

        self.operation_type = None
        self.stage = "new"

        self.specialty_id = None
        self.specialty_name = None

        self.doctor_id = None
        self.doctor_name = None

        self.service_id = None
        self.service_name = None

        self.slot_id = None
        self.slot_date = None
        self.slot_time = None

        self.new_slot_id = None
        self.new_slot_date = None
        self.new_slot_time = None

        self.pending_patient_profile_updates.clear()
        self.appointment_reference = None
        self.candidate_appointments = []
        self.pending_operation_entities.clear()
        self.awaiting_confirmation = False
        self.pending_action = None

        self.recent_specialties = []
        self.recent_doctors = []
        self.recent_services = []
        self.recent_slots = []

        if not preserve_patient:

            self.patient_id = None
            self.national_id = None
            self.patient_name = None
            self.phone = None
            self.phone_confirmed = False

            return

        self.patient_id = patient_id
        self.national_id = national_id
        self.patient_name = patient_name
        self.phone = phone
        self.phone_confirmed = phone_confirmed