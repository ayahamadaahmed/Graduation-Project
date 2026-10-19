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
    ] ,
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


async def update_patient_profile(
    *,
    tenant_id: str,
    patient_id: str,
    national_id: str,
    patient_name: str | None,
    phone: str | None,
    language: Literal[
        "ar",
        "en",
    ],
    channel: Literal[
        "web",
        "mobile",
        "voice",
        "whatsapp",
    ],
):

    payload = {
        "national_id":
            national_id,

        "language":
            language,

        "channel":
            channel,
    }

    if patient_name is not None:

        payload[
            "patient_name"
        ] = patient_name

    if phone is not None:

        payload[
            "phone"
        ] = phone

    return await (
        backend_client.request(
            tenant_id=
                tenant_id,

            method=
                "PATCH",

            path=(
                "/api/v1/patients/"
                f"{patient_id}/profile"
            ),

            json=
                payload,
        )
    )