from __future__ import annotations

from datetime import date, time
from typing import Literal

from pydantic import (
    BaseModel,
    Field,
)


class PostCallBookingConfirmationRequest(
    BaseModel
):
    event_type: Literal[
        "booking_confirmation",
    ]

    appointment_reference: str = Field(
        min_length=1,
        max_length=100,
    )

    source: Literal[
        "voice",
    ] = "voice"


# ============================================================
# INTERNAL TRUSTED WHATSAPP PAYLOAD
#
# This object stays inside the backend.
# Do NOT return it to the Voice Gateway.
# ============================================================

class WhatsAppBookingNotificationPayload(
    BaseModel
):
    language: Literal[
        "ar",
        "en",
    ]
    event_type: Literal[
        "booking_confirmation",
    ] = "booking_confirmation"

    destination_channel: Literal[
        "whatsapp",
    ] = "whatsapp"

    appointment_reference: str

    recipient_phone: str
    patient_name: str

    doctor_name: str | None = None
    specialty_name: str | None = None
    service_name: str | None = None

    branch_name: str | None = None

    branch_medical_record_number: (
        str | None
    ) = None

    scheduled_date: date
    start_time: time
    end_time: time

    appointment_status: str
    original_channel: str


class PostCallBookingConfirmationResponse(
    BaseModel
):
    status: Literal[
        "accepted",
    ] = "accepted"

    appointment_reference: str

    prepared: bool = True