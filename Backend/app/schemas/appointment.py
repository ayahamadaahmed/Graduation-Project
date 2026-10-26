from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

class AppointmentCreateRequest(BaseModel):
    national_id: str = Field(
        min_length=14,
        max_length=14,
    )

    slot_id: UUID
    service_id: UUID

    channel: Literal[
        "web",
        "mobile",
        "voice",
        "whatsapp",
    ] 

    notes: str | None = Field(
        default=None,
        max_length=2000,
    )

    created_by_type: Literal[
        "patient",
        "ai_agent",
        "staff",
        "system",
    ] = "ai_agent"

    created_by_reference: str | None = Field(
        default=None,
        max_length=100,
    )

class AppointmentCreateResponse(BaseModel):
    appointment_reference: str

    patient_code: str
    patient_name: str

    branch_medical_record_number: str

    doctor_name: str | None = None
    service_name: str | None = None
    specialty_name: str | None = None
    branch_name: str | None = None

    scheduled_date: date
    start_time: time
    end_time: time

    channel: str
    status: str

    notes: str | None = None

    confirmed_at: datetime | None = None

    reschedule_count: int

class AppointmentSearchByNationalIdRequest(
    BaseModel
):
    national_id: str = Field(
        min_length=14,
        max_length=14,
    )

    include_cancelled: bool = False

    future_only: bool = False

    limit: int = Field(
        default=20,
        ge=1,
        le=100,
    )

class AppointmentSearchItem(BaseModel):
    appointment_reference: str

    patient_name: str

    branch_medical_record_number: (
        str | None
    ) = None

    doctor_name: str | None = None
    service_name: str | None = None
    specialty_name: str | None = None
    branch_name: str | None = None

    scheduled_date: date
    start_time: time
    end_time: time

    status: str
    channel: str

    notes: str | None = None

    reschedule_count: int

    cancellation_reason: str | None = None

    confirmed_at: datetime | None = None
    cancelled_at: datetime | None = None

class AppointmentsByNationalIdResponse(BaseModel):
    patient_code: str
    patient_name: str

    count: int

    appointments: list[
        AppointmentSearchItem
    ]        

class AppointmentRead(BaseModel):
    id: UUID
    provider_id: UUID
    appointment_reference: str

    patient_id: UUID
    patient_name: str
    phone: str
    preferred_language: str | None = None

    slot_id: UUID
    doctor_id: UUID | None = None
    branch_id: UUID
    branch_medical_record_number: str | None = None
    doctor_name: str | None = None
    service_name: str | None = None
    specialty_name: str | None = None
    branch_name: str | None = None
    service_id: UUID | None

    scheduled_date: date
    start_time: time
    end_time: time

    channel: str
    status: str
    notes: str | None

    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    created_by_type: str
    created_by_reference: str | None

    reschedule_count: int

class AppointmentCancelRequest(BaseModel):
    national_id: str = Field(
        min_length=14,
        max_length=14,
    )

    reason: str | None = Field(
        default=None,
        max_length=500,
    )

    changed_by: Literal[
        "patient",
        "ai_agent",
        "staff",
        "system",
    ] = "ai_agent"

    actor_reference: str | None = Field(
        default=None,
        max_length=100,
    )

class AppointmentConfirmRequest(BaseModel):
    national_id: str = Field(
        min_length=14,
        max_length=14,
    )

    changed_by: Literal[
        "patient",
        "ai_agent",
        "staff",
        "system",
    ] = "ai_agent"

    actor_reference: str | None = Field(
        default=None,
        max_length=100,
    )

class AppointmentConfirmResponse(BaseModel):
    appointment_reference: str
    previous_status: str
    status: str

    confirmed_at: datetime | None

class AppointmentCancelResponse(BaseModel):
    appointment_reference: str
    previous_status: str
    status: str

    slot_id: UUID
    slot_status: str

    cancelled_at: datetime
    cancellation_reason: str | None   

class AppointmentRescheduleRequest(BaseModel):
    national_id: str = Field(
        min_length=14,
        max_length=14,
    )

    new_slot_id: UUID

    reason: str | None = Field(
        default=None,
        max_length=500,
    )

    changed_by: Literal[
        "patient",
        "ai_agent",
        "staff",
        "system",
    ] = "ai_agent"

    actor_reference: str | None = Field(
        default=None,
        max_length=100,
    )

class AppointmentLookupRequest(BaseModel):
    national_id: str = Field(
        min_length=14,
        max_length=14,
    )

    appointment_reference: str = Field(
        min_length=5,
        max_length=40,
    )    


class AppointmentLookupResponse(BaseModel):
    appointment_reference: str

    patient_code: str
    patient_name: str

    branch_medical_record_number: (
        str
        | None
    ) = None

    # --------------------------------------------------------
    # Trusted internal IDs
    # --------------------------------------------------------

    doctor_id: UUID | None = None
    branch_id: UUID

    service_id: (
        UUID
        | None
    ) = None

    slot_id: UUID

    # --------------------------------------------------------
    # Display values
    # --------------------------------------------------------

    doctor_name: (
        str
        | None
    ) = None

    specialty_name: (
        str
        | None
    ) = None

    service_name: (
        str
        | None
    ) = None

    branch_name: (
        str
        | None
    ) = None

    # --------------------------------------------------------
    # Schedule
    # --------------------------------------------------------

    scheduled_date: date

    start_time: time

    end_time: time

    # --------------------------------------------------------
    # Appointment status
    # --------------------------------------------------------

    status: str
    channel: str

    notes: (
        str
        | None
    ) = None

    reschedule_count: int

    confirmed_at: (
        datetime
        | None
    ) = None

    cancellation_reason: (
        str
        | None
    ) = None

    cancelled_at: (
        datetime
        | None
    ) = None

class AppointmentRescheduleResponse(BaseModel):
    appointment_reference: str

    previous_status: str
    status: str

    old_slot_id: UUID
    new_slot_id: UUID

    doctor_id: UUID | None = None
    branch_id: UUID
    service_id: UUID | None

    scheduled_date: date
    start_time: time
    end_time: time

    old_slot_status: str
    new_slot_status: str

    reschedule_count: int
    updated_at: datetime   

class AppointmentDetails(AppointmentRead):
    cancellation_reason: str | None = None
    cancelled_at: datetime | None = None


class PatientAppointmentsResponse(BaseModel):
    patient_id: UUID
    count: int
    appointments: list[AppointmentDetails]      