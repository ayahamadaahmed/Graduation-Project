import logging
import re
import time

from datetime import date

from typing import (
    AsyncIterator,
    Literal,
)
from mcp.server.transport_security import TransportSecuritySettings
from mcp_server.tools.catalog import (
    get_working_hours as get_working_hours_impl,
)
from uuid import UUID

from mcp.server.fastmcp import (
    Context,
    FastMCP,
)

from mcp_server.tools.appointments import (
    cancel_booking as cancel_booking_impl,
    create_booking as create_booking_impl,
    lookup_booking as lookup_booking_impl,
    reschedule_booking as reschedule_booking_impl,
    search_patient_bookings as search_patient_bookings_impl,

)

from mcp_server.tools.catalog import (
    get_provider_info as get_provider_info_impl,
    list_available_slots as list_available_slots_impl,
    list_doctors as list_doctors_impl,
    list_services as list_services_impl,
    list_specialties as list_specialties_impl,
)

from mcp_server.tools.patients import (
    lookup_patient as lookup_patient_impl,
    resolve_patient as resolve_patient_impl,
    update_patient_profile
        as update_patient_profile_impl,
)

from contextlib import (
    asynccontextmanager,
)
from mcp_server.backend_client import (
    backend_client,
)
from mcp_server.auth import (
    authorize_mcp_request,
)
from mcp_server.config import (
    get_mcp_settings,
)
logger = logging.getLogger(
    "uvicorn.error"
)

@asynccontextmanager
async def mcp_lifespan(
    server: FastMCP,
) -> AsyncIterator[dict]:

    if get_mcp_settings().auth_mode != "enforce":

        logger.warning(
            "mcp_service_auth_mode=audit "
            "calls without a service token "
            "are still served"
        )

    await (
        backend_client.start()
    )

    await (
        backend_client.warmup()
    )

    try:

        yield {}

    finally:

        await (
            backend_client.close()
        )

mcp = FastMCP(
    "MedMind Booking MCP",
    host="127.0.0.1",
    port=9000,
    lifespan=mcp_lifespan,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "127.0.0.1:*",
            "localhost:*",
            "host.docker.internal:*",
        ],
        allowed_origins=[
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://host.docker.internal:*",
        ],
    ),
)

TENANT_PATTERN = re.compile(
    r"^[A-Za-z0-9]"
    r"[A-Za-z0-9._-]{0,63}$"
)


def _require_request_tenant_id(
    context: Context,
) -> str:
    """
    Extract the tenant identity from the current
    Streamable HTTP MCP request.

    Fail closed:
    MCP tools must never silently fall back
    to a global/default tenant.

    Every tool calls this first, so it also
    authenticates the caller for all tools.
    """

    request_context = (
        context.request_context
    )

    request = getattr(
        request_context,
        "request",
        None,
    )

    if request is None:

        raise RuntimeError(
            "MCP request does not contain "
            "HTTP request context."
        )

    headers = getattr(
        request,
        "headers",
        None,
    )

    if headers is None:

        raise RuntimeError(
            "MCP request does not contain "
            "HTTP headers."
        )

    # Agent -> MCP credential, checked before the
    # tenant is read (mcp_server/auth.py).
    client = getattr(
        request,
        "client",
        None,
    )

    authorize_mcp_request(
        headers,
        client_host=getattr(
            client,
            "host",
            None,
        ),
    )

    raw_tenant_id = (
        headers.get(
            "x-tenant-id"
        )
    )

    if not raw_tenant_id:

        raise RuntimeError(
            "Missing X-Tenant-ID on MCP request."
        )

    tenant_id = (
        str(
            raw_tenant_id
        )
        .strip()
    )

    if not TENANT_PATTERN.fullmatch(
        tenant_id
    ):

        raise RuntimeError(
            "Invalid X-Tenant-ID "
            "on MCP request."
        )

    return tenant_id


def _request_tenant_id(
    context: Context,
) -> str | None:
    """
    Read X-Tenant-ID from the current
    Streamable HTTP MCP request.

    Diagnostic only for now.
    """

    request_context = (
        context.request_context
    )

    request = getattr(
        request_context,
        "request",
        None,
    )

    if request is None:

        return None

    headers = getattr(
        request,
        "headers",
        None,
    )

    if headers is None:

        return None

    tenant_id = (
        headers.get(
            "x-tenant-id"
        )
        or
        headers.get(
            "X-Tenant-ID"
        )
    )

    if not tenant_id:

        return None

    return str(
        tenant_id
    ).strip()


@mcp.tool()
async def get_provider_info(
    context: Context,
):
    """
    Get the current healthcare provider details.
    """

    tenant_id = (
        _require_request_tenant_id(
            context
        )
    )

    return await get_provider_info_impl(
        tenant_id=tenant_id
    )


@mcp.tool()
async def resolve_patient(
    context: Context,
    national_id: str,
    patient_name: str,
    phone: str,
    channel: Literal[
        "web",
        "mobile",
        "voice",
        "whatsapp",
    ],
    preferred_language: Literal[
        "ar",
        "en",
    ] = "ar",
):
    """
    Resolve or create a patient before booking.
    """

    tenant_id = (
        _require_request_tenant_id(
            context
        )
    )

    return await resolve_patient_impl(
        tenant_id=tenant_id,

        national_id=national_id,

        patient_name=(
            patient_name
        ),

        phone=phone,

        preferred_language=(
            preferred_language
        ),

        channel=channel,
    )

@mcp.tool()
async def lookup_patient(
    context: Context,
    national_id: str,
    language: Literal[
        "ar",
        "en",
    ] = "ar",
):
    tenant_id = (
        _require_request_tenant_id(
            context
        )
    )

    return await lookup_patient_impl(
        tenant_id=tenant_id,
        national_id=national_id,
        language=language,
    )  

@mcp.tool()
async def list_specialties(
    context: Context,
):
    """
    List medical specialties
    for the current healthcare provider.
    """

    total_started_at = (
        time.perf_counter()
    )

    tenant_started_at = (
        time.perf_counter()
    )

    tenant_id = (
        _require_request_tenant_id(
            context
        )
    )

    tenant_ms = (
        (
            time.perf_counter()
            - tenant_started_at
        )
        * 1000
    )

    impl_started_at = (
        time.perf_counter()
    )

    result = await (
        list_specialties_impl(
            tenant_id=tenant_id,
        )
    )

    impl_ms = (
        (
            time.perf_counter()
            - impl_started_at
        )
        * 1000
    )

    total_ms = (
        (
            time.perf_counter()
            - total_started_at
        )
        * 1000
    )

    logger.info(
        "mcp_server_tool_timing "
        "tool=list_specialties "
        "tenant_ms=%.2f "
        "impl_ms=%.2f "
        "total_ms=%.2f",
        tenant_ms,
        impl_ms,
        total_ms,
    )

    return result


@mcp.tool()
async def list_doctors(
    context: Context,
    specialty_id: UUID | None = None,
    branch_id: UUID | None = None,
    limit: int = 100,
):
    """
    List doctors for the current provider.
    """

    tenant_id = (
        _require_request_tenant_id(
            context
        )
    )

    return await list_doctors_impl(
        tenant_id=tenant_id,

        specialty_id=(
            specialty_id
        ),

        branch_id=(
            branch_id
        ),

        limit=limit,
    )

@mcp.tool()
async def get_working_hours(
    context: Context,
    doctor_id: UUID | None = None,
    branch_id: UUID | None = None,
    day_of_week: int | None = None,
):
    """
    List active doctor working hours
    for the current healthcare provider.

    Optional filters:
    - doctor_id
    - branch_id
    - day_of_week

    Weekday convention:
    Monday = 0
    ...
    Sunday = 6
    """

    tenant_id = (
        _require_request_tenant_id(
            context
        )
    )

    return await get_working_hours_impl(
        tenant_id=tenant_id,
        doctor_id=doctor_id,
        branch_id=branch_id,
        day_of_week=day_of_week,
    )


@mcp.tool()
async def list_services(
    context: Context,
    service_type: str | None = None,
    doctor_id: UUID | None = None,
    limit: int = 100,
):
    """
    List active healthcare services.

    Can filter services by doctor so the
    booking agent receives only services
    that the selected doctor can provide.
    """

    tenant_id = (
        _require_request_tenant_id(
            context
        )
    )

    return await list_services_impl(
        tenant_id=tenant_id,
        service_type=service_type,
        doctor_id=doctor_id,
        limit=limit,
    )


@mcp.tool()
async def list_available_slots(
    context: Context,
    slot_date: date,
    doctor_id: UUID | None = None,
    branch_id: UUID | None = None,
    limit: int = 100,
):
    """
    List available appointment slots.

    Diagnostic labs book without a doctor: omit doctor_id; their
    slots have doctor_id null. Each slot carries branch_id and
    branch names, so same-time slots at different branches can be
    told apart.
    """

    tenant_id = (
        _require_request_tenant_id(
            context
        )
    )

    return await list_available_slots_impl(
        tenant_id=tenant_id,

        slot_date=slot_date,

        doctor_id=doctor_id,

        branch_id=branch_id,

        limit=limit,
    )

@mcp.tool()
async def create_booking(
    context: Context,
    national_id: str,
    slot_id: UUID,
    service_id: UUID,
    idempotency_key: str,
    channel: Literal[
        "web",
        "mobile",
        "voice",
        "whatsapp",
    ], 
    notes: str | None = None,
    session_reference: str | None = None,
):
    """
    Create a healthcare appointment.

    Reuse idempotency_key for retries
    of the same logical write.
    """

    tenant_id = (
        _require_request_tenant_id(
            context
        )
    )

    return await create_booking_impl(
        tenant_id=tenant_id,

        national_id=national_id,

        slot_id=slot_id,

        service_id=service_id,

        idempotency_key=(
            idempotency_key
        ),

        channel=channel,

        notes=notes,

        session_reference=(
            session_reference
        ),
    )

@mcp.tool()
async def search_patient_bookings(
    context: Context,
    national_id: str,
    include_cancelled: bool = False,
    future_only: bool = False,
    limit: int = 20,
):
    """
    List appointments belonging to a patient.
    """

    tenant_id = (
        _require_request_tenant_id(
            context
        )
    )

    return await search_patient_bookings_impl(
        tenant_id=tenant_id,

        national_id=national_id,

        include_cancelled=(
            include_cancelled
        ),

        future_only=future_only,

        limit=limit,
    )


@mcp.tool()
async def lookup_booking(
    context: Context,
    national_id: str,
    appointment_reference: str,
):
    """
    Secure appointment lookup.
    """

    tenant_id = (
        _require_request_tenant_id(
            context
        )
    )

    return await lookup_booking_impl(
        tenant_id=tenant_id,

        national_id=national_id,

        appointment_reference=(
            appointment_reference
        ),
    )


@mcp.tool()
async def cancel_booking(
    context: Context,
    national_id: str,
    appointment_reference: str,
    idempotency_key: str,
    reason: str | None = None,
    session_reference: str | None = None,
):
    """
    Cancel an appointment.
    """

    tenant_id = (
        _require_request_tenant_id(
            context
        )
    )

    return await cancel_booking_impl(
        tenant_id=tenant_id,

        national_id=national_id,

        appointment_reference=(
            appointment_reference
        ),

        idempotency_key=(
            idempotency_key
        ),

        reason=reason,

        session_reference=(
            session_reference
        ),
    )


@mcp.tool()
async def reschedule_booking(
    context: Context,
    national_id: str,
    appointment_reference: str,
    new_slot_id: UUID,
    idempotency_key: str,
    reason: str | None = None,
    session_reference: str | None = None,
):
    """
    Reschedule an appointment.
    """

    tenant_id = (
        _require_request_tenant_id(
            context
        )
    )

    return await reschedule_booking_impl(
        tenant_id=tenant_id,

        national_id=national_id,

        appointment_reference=(
            appointment_reference
        ),

        new_slot_id=new_slot_id,

        idempotency_key=(
            idempotency_key
        ),

        reason=reason,

        session_reference=(
            session_reference
        ),
    )



@mcp.tool()
async def update_patient_profile(
    context: Context,

    patient_id: str,

    national_id: str,

    channel: Literal[
        "web",
        "mobile",
        "voice",
        "whatsapp",
    ],

    language: Literal[
        "ar",
        "en",
    ],

    patient_name: str | None = None,

    phone: str | None = None,
):

    tenant_id = (
        _require_request_tenant_id(
            context
        )
    )

    if (
        patient_name is None
        and
        phone is None
    ):

        raise ValueError(
            "At least one patient field "
            "must be provided."
        )

    return await (
        update_patient_profile_impl(
            tenant_id=
                tenant_id,

            patient_id=
                patient_id,

            national_id=
                national_id,

            patient_name=
                patient_name,

            phone=
                phone,

            language=
                language,

            channel=
                channel,
        )
    ) 

if __name__ == "__main__":

    mcp.run(
        transport="streamable-http"
    )