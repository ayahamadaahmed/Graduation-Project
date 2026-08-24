from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    Field,
)


# ============================================================
# INTENTS
# ============================================================

Intent = Literal[
    # Operations
    "book_appointment",
    "cancel_appointment",
    "reschedule_appointment",
    "lookup_appointment",
    "search_appointments",

    # Information
    "ask_doctor",
    "ask_service",
    "ask_available_slots",
    "ask_provider",

    # Contextual values
    "provide_specialty",
    "provide_doctor",
    "provide_service",
    "provide_date",
    "provide_time",
    "provide_patient_name",
    "provide_phone",
    "provide_national_id",
    "provide_appointment_reference",

    # Confirmation
    "confirm_action",
    "deny_action",

    # Conversation
    "greeting",
    "help",

    # Fallback
    "unknown",
]


OperationType = Literal[
    "book_appointment",
    "cancel_appointment",
    "reschedule_appointment",
    "lookup_appointment",
    "search_appointments",
]


Confirmation = Literal[
    "yes",
    "no",
    "unknown",
]


# ============================================================
# ENTITIES
# ============================================================

class NLUEntities(
    BaseModel
):

    specialty_name: str | None = Field(
        default=None,
        description=(
            "Medical specialty mentioned by the user. "
            "Example: جلدية or Dermatology."
        ),
    )

    doctor_name: str | None = Field(
        default=None,
        description=(
            "Doctor name mentioned by the user."
        ),
    )

    service_name: str | None = Field(
        default=None,
        description=(
            "Healthcare service mentioned by the user."
        ),
    )

    date_text: str | None = Field(
        default=None,
        description=(
            "Date expression exactly as understood "
            "from the user's message. "
            "Examples: بكرة, 20 أغسطس, tomorrow."
        ),
    )

    time_text: str | None = Field(
        default=None,
        description=(
            "Time expression mentioned by the user. "
            "Examples: 12 ونص, 5 العصر, 3 PM."
        ),
    )

    patient_name: str | None = Field(
        default=None,
        description=(
            "Patient name if explicitly provided."
        ),
    )

    phone: str | None = Field(
        default=None,
        description=(
            "Phone number if explicitly provided."
        ),
    )

    national_id: str | None = Field(
        default=None,
        description=(
            "National ID if explicitly provided."
        ),
    )

    appointment_reference: str | None = Field(
        default=None,
        description=(
            "Appointment reference such as "
            "APT-260815-XXXX."
        ),
    )


# ============================================================
# NLU RESULT
# ============================================================

class NLUResult(
    BaseModel
):

    intent: Intent = Field(
        description=(
            "Meaning of the CURRENT user message."
        )
    )

    operation_type: OperationType | None = Field(
        default=None,
        description=(
            "Set only when the user explicitly starts "
            "or switches to a booking-related operation. "
            "For contextual replies inside an existing "
            "operation, normally leave this null."
        ),
    )

    entities: NLUEntities = Field(
        default_factory=NLUEntities,
    )

    confirmation: Confirmation = Field(
        default="unknown",
        description=(
            "Whether the user explicitly confirms "
            "or rejects a pending action."
        ),
    )

    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Confidence in the interpretation."
        ),
    )