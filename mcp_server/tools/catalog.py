from datetime import date

from uuid import UUID

from mcp_server.backend_client import (
    backend_client,
)


# ============================================================
# PROVIDER
# ============================================================

async def get_provider_info(
    *,
    tenant_id: str,
):
    """
    Get current provider information.
    """

    return await backend_client.request(
        tenant_id=tenant_id,
        method="GET",
        path="/api/v1/providers/current",
    )


# ============================================================
# DOCTORS
# ============================================================

async def list_doctors(
    *,
    tenant_id: str,
    specialty_id: UUID | None = None,
    branch_id: UUID | None = None,
    limit: int = 100,
):
    """
    List doctors.

    Can optionally filter by specialty
    and branch.
    """

    params: dict[
        str,
        str | int,
    ] = {
        "limit":
            limit,
    }

    if specialty_id is not None:

        params[
            "specialty_id"
        ] = str(
            specialty_id
        )

    if branch_id is not None:

        params[
            "branch_id"
        ] = str(
            branch_id
        )

    return await backend_client.request(
        tenant_id=tenant_id,
        method="GET",
        path="/api/v1/doctors",
        params=params,
    )

async def list_specialties(
    *,
    tenant_id: str,
):
    """
    List active medical specialties
    for the current healthcare provider.
    """

    return await backend_client.request(
        tenant_id=tenant_id,
        method="GET",
        path="/api/v1/specialties",
    )
# ============================================================
# SERVICES
# ============================================================
async def list_services(
    *,
    tenant_id: str,
    service_type: str | None = None,
    doctor_id: UUID | None = None,
    specialty_id: UUID | None = None,
    limit: int = 100,
):
    """
    List active healthcare services.

    Optionally filter services by:
    - service type
    - doctor

    Doctor filtering is validated by
    the backend through doctor_services.
    """

    params = {}

    if service_type is not None:
        params["service_type"] = (
            service_type
        )

    if doctor_id is not None:
        params["doctor_id"] = str(
            doctor_id
        )

    if specialty_id is not None:
        params["specialty_id"] = str(
            specialty_id
        )    

    result = await backend_client.request(
        tenant_id=tenant_id,
        method="GET",
        path="/api/v1/services",
        params=params,
    )

    # Keep MCP-side limit behavior.
    # Backend /services does not currently
    # expose a limit query parameter.
    if isinstance(
        result,
        list,
    ):
        return result[:limit]

    return result

async def get_working_hours(
    *,
    tenant_id: str,
    doctor_id: UUID | None = None,
    branch_id: UUID | None = None,
    day_of_week: int | None = None,
):
    """
    List active doctor working hours
    for the current healthcare provider.

    Optional filters:
    - doctor
    - branch
    - weekday

    Backend weekday convention:
    Monday = 0
    ...
    Sunday = 6
    """

    params = {}

    if doctor_id is not None:

        params[
            "doctor_id"
        ] = str(
            doctor_id
        )

    if branch_id is not None:

        params[
            "branch_id"
        ] = str(
            branch_id
        )

    if day_of_week is not None:

        params[
            "day_of_week"
        ] = (
            day_of_week
        )

    return await backend_client.request(
        tenant_id=tenant_id,
        method="GET",
        path="/api/v1/admin/working-hours",
        params=params,
    )

# ============================================================
# SLOTS
# ============================================================

async def list_available_slots(
    *,
    tenant_id: str,
    slot_date: date,
    doctor_id: UUID | None = None,
    branch_id: UUID | None = None,
    limit: int = 100,
):
    """
    List available appointment slots
    for one date.
    """

    params: dict[
        str,
        str | int,
    ] = {
        "slot_date":
            slot_date.isoformat(),

        "limit":
            limit,
    }

    if doctor_id is not None:

        params[
            "doctor_id"
        ] = str(
            doctor_id
        )

    if branch_id is not None:

        params[
            "branch_id"
        ] = str(
            branch_id
        )

    return await backend_client.request(
        tenant_id=tenant_id,
        method="GET",
        path="/api/v1/slots",
        params=params,
    )