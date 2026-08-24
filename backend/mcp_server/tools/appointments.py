from typing import Literal

from uuid import UUID

from mcp_server.backend_client import (
    backend_client,
)


BookingChannel = Literal[
    "web",
    "mobile",
    "voice",
    "whatsapp",
]


# ============================================================
# CREATE BOOKING
# ============================================================

async def create_booking(
    *,
    tenant_id: str,
    national_id: str,
    slot_id: UUID,
    service_id: UUID,
    idempotency_key: str,
    channel: BookingChannel = "web",
    notes: str | None = None,
    session_reference: str | None = None,
):
    """
    Create a healthcare appointment.

    The caller generates one idempotency key
    for one logical create action.

    The same key MUST be reused when retrying
    the same operation.
    """

    return await backend_client.request(
        tenant_id=tenant_id,

        method="POST",

        path=(
            "/api/v1/appointments"
        ),

        idempotency_key=(
            idempotency_key
        ),

        json={
            "national_id":
                national_id,

            "slot_id":
                str(
                    slot_id
                ),

            "service_id":
                str(
                    service_id
                ),

            "channel":
                channel,

            "notes":
                notes,

            "created_by_type":
                "ai_agent",

            "created_by_reference":
                session_reference,
        },
    )


# ============================================================
# SEARCH PATIENT BOOKINGS
# ============================================================

async def search_patient_bookings(
    *,
    tenant_id: str,
    national_id: str,
    include_cancelled: bool = False,
    limit: int = 20,
):
    """
    Search appointments owned by a patient.
    """

    return await backend_client.request(
        tenant_id=tenant_id,

        method="POST",

        path=(
            "/api/v1/appointments/"
            "search-by-national-id"
        ),

        json={
            "national_id":
                national_id,

            "include_cancelled":
                include_cancelled,

            "limit":
                limit,
        },
    )


# ============================================================
# LOOKUP BOOKING
# ============================================================

async def lookup_booking(
    *,
    tenant_id: str,
    national_id: str,
    appointment_reference: str,
):
    """
    Securely lookup one appointment.

    The Backend validates patient ownership.
    """

    normalized_reference = (
        appointment_reference
        .strip()
        .upper()
    )

    return await backend_client.request(
        tenant_id=tenant_id,

        method="POST",

        path=(
            "/api/v1/appointments/lookup"
        ),

        json={
            "national_id":
                national_id,

            "appointment_reference":
                normalized_reference,
        },
    )


# ============================================================
# CANCEL BOOKING
# ============================================================

async def cancel_booking(
    *,
    tenant_id: str,
    national_id: str,
    appointment_reference: str,
    idempotency_key: str,
    reason: str | None = None,
    session_reference: str | None = None,
):
    """
    Cancel an appointment.

    The same idempotency key MUST be reused
    when retrying the same cancellation.
    """

    normalized_reference = (
        appointment_reference
        .strip()
        .upper()
    )

    return await backend_client.request(
        tenant_id=tenant_id,

        method="POST",

        path=(
            "/api/v1/appointments/"
            f"{normalized_reference}/cancel"
        ),

        idempotency_key=(
            idempotency_key
        ),

        json={
            "national_id":
                national_id,

            "reason":
                reason,

            "changed_by":
                "ai_agent",

            "actor_reference":
                session_reference,
        },
    )


# ============================================================
# RESCHEDULE BOOKING
# ============================================================

async def reschedule_booking(
    *,
    tenant_id: str,
    national_id: str,
    appointment_reference: str,
    new_slot_id: UUID,
    idempotency_key: str,
    reason: str | None = None,
    session_reference: str | None = None,
):
    """
    Move an appointment to another slot.

    The same idempotency key MUST be reused
    when retrying the same reschedule.
    """

    normalized_reference = (
        appointment_reference
        .strip()
        .upper()
    )

    return await backend_client.request(
        tenant_id=tenant_id,

        method="POST",

        path=(
            "/api/v1/appointments/"
            f"{normalized_reference}/reschedule"
        ),

        idempotency_key=(
            idempotency_key
        ),

        json={
            "national_id":
                national_id,

            "new_slot_id":
                str(
                    new_slot_id
                ),

            "reason":
                reason,

            "changed_by":
                "ai_agent",

            "actor_reference":
                session_reference,
        },
    )