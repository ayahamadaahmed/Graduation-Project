from typing import Literal

from mcp_server.backend_client import (
    backend_client,
)


async def lookup_patient(
    *,
    tenant_id: str,
    national_id: str,
    language: Literal[
        "ar",
        "en",
    ] = "ar",
):
    """
    Look up an existing patient using
    the national ID only.

    This does not create or update
    patient information.
    """

    return await backend_client.request(
        tenant_id=tenant_id,

        method="POST",

        path="/api/v1/patients/lookup",

        json={
            "national_id":
                national_id,

            "language":
                language,
        },
    )


async def resolve_patient(
    *,
    tenant_id: str,
    national_id: str,
    patient_name: str,
    phone: str,
    preferred_language: Literal[
        "ar",
        "en",
    ] = "ar",
    channel: Literal[
        "web",
        "mobile",
        "voice",
        "whatsapp",
    ] = "web",
):
    """
    Resolve an existing patient or create
    the patient/provider profile required
    for booking.
    """

    return await backend_client.request(
        tenant_id=tenant_id,

        method="POST",

        path="/api/v1/patients/resolve",

        json={
            "national_id":
                national_id,

            "patient_name":
                patient_name,

            "phone":
                phone,

            "preferred_language":
                preferred_language,

            "channel":
                channel,
        },
    )