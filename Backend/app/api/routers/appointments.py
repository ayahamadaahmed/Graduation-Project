from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    status,
)
from fastapi.routing import APIRoute
from starlette.routing import Match
from starlette.types import Scope
from typing import Annotated
from uuid import UUID

from app.api.dependencies import (
    AppointmentServiceDependency,
    CurrentProvider,
    StaffAuditServiceDependency,
)
from app.security.booking_auth import (
    BookingService,
    ConfirmCaller,
    reject_staff_attribution,
    require_booking_service,
    require_confirm_credentials,
)
from app.security.rbac import (
    require_staff_roles,
)
from app.security.staff_context import (
    StaffContext,
)

from app.schemas.appointment import (
    AppointmentCancelRequest,
    AppointmentCancelResponse,
    AppointmentConfirmRequest,
    AppointmentConfirmResponse,
    AppointmentCreateRequest,
    AppointmentCreateResponse,
    AppointmentDetails,
    AppointmentRead,
    AppointmentRescheduleRequest,
    AppointmentRescheduleResponse,
    AppointmentSearchByNationalIdRequest,
    AppointmentsByNationalIdResponse,
    PatientAppointmentsResponse,
    AppointmentLookupRequest,
    AppointmentLookupResponse,
)

IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
    ),
]


router = APIRouter(
    prefix="/appointments",
    tags=["appointments"],
)

# Routes the MCP server calls for the AI agent: the booking service
# credential is checked before the tenant lookup (app/security/booking_auth.py).
BookingServiceAuth = [Depends(require_booking_service)]

# Staff-only reads. Doctor / lab scope is enforced in AppointmentService.
StaffAppointmentReader = Annotated[
    StaffContext,
    Depends(
        require_staff_roles(
            "provider_admin",
            "receptionist",
            "doctor",
            "lab_staff",
        )
    ),
]

@router.post(
    "",
    response_model=AppointmentCreateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=BookingServiceAuth,
)
def create_appointment(
    data: AppointmentCreateRequest,
    provider: CurrentProvider,
    caller: BookingService,
    service: AppointmentServiceDependency,
    idempotency_key: IdempotencyKey = None,
) -> AppointmentCreateResponse:

    reject_staff_attribution(caller, data.created_by_type)

    return service.create_confirmed_booking(
        provider_id=provider.id,
        provider_timezone=provider.timezone,
        data=data,
        idempotency_key=idempotency_key,
    )

@router.post(
    "/{appointment_reference}/cancel",
    response_model=AppointmentCancelResponse,
    dependencies=BookingServiceAuth,
)
def cancel_appointment(
    appointment_reference: str,
    data: AppointmentCancelRequest,
    provider: CurrentProvider,
    caller: BookingService,
    service: AppointmentServiceDependency,
    idempotency_key: IdempotencyKey = None,
) -> AppointmentCancelResponse:

    reject_staff_attribution(caller, data.changed_by)

    return service.cancel_booking(
        provider_id=provider.id,
        appointment_reference=(
            appointment_reference
        ),
        data=data,
        idempotency_key=idempotency_key,
    )

@router.post(
    "/{appointment_reference}/confirm",
    response_model=AppointmentConfirmResponse,
    # Credentials are checked before the tenant lookup.
    dependencies=[Depends(require_confirm_credentials)],
)
def confirm_appointment(
    appointment_reference: str,
    data: AppointmentConfirmRequest,
    provider: CurrentProvider,
    caller: ConfirmCaller,
    service: AppointmentServiceDependency,
    audit: StaffAuditServiceDependency,
) -> AppointmentConfirmResponse:
    """The MCP service or a provider_admin/receptionist of this provider.

    Both still prove the patient with national_id. Staff confirmations are
    attributed to the staff user and audited in the same commit; the service
    credential cannot claim a staff confirmation.
    """
    audit_hook = None

    if isinstance(caller, StaffContext):
        data = data.model_copy(
            update={
                "changed_by": "staff",
                "actor_reference": str(caller.user_id),
            }
        )
        audit_hook = audit.write_hook(
            staff=caller,
            action="appointment.confirm",
            resource_type="appointment",
        )

    elif data.changed_by == "staff":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "SERVICE_CANNOT_ACT_AS_STAFF",
                "message": "A staff confirmation needs a staff access token.",
            },
        )

    return service.confirm_booking(
        provider_id=provider.id,
        appointment_reference=(
            appointment_reference
        ),
        data=data,
        audit=audit_hook,
    )

@router.post(
    "/{appointment_reference}/reschedule",
    response_model=AppointmentRescheduleResponse,
    dependencies=BookingServiceAuth,
)
def reschedule_appointment(
    appointment_reference: str,
    data: AppointmentRescheduleRequest,
    provider: CurrentProvider,
    caller: BookingService,
    service: AppointmentServiceDependency,
    idempotency_key: IdempotencyKey = None,
) -> AppointmentRescheduleResponse:
    reject_staff_attribution(caller, data.changed_by)

    return service.reschedule_booking(
        provider_id=provider.id,
        provider_timezone=provider.timezone,
        appointment_reference=appointment_reference,
        data=data,
        idempotency_key=idempotency_key,
    )

@router.get(
    "/reference/{appointment_reference}",
    response_model=AppointmentDetails,
)
def get_appointment_by_reference(
    appointment_reference: str,
    staff: StaffAppointmentReader,
    service: AppointmentServiceDependency,
    audit: StaffAuditServiceDependency,
) -> AppointmentDetails:
    details = service.get_booking_by_reference_for_staff(
        staff=staff,
        appointment_reference=(
            appointment_reference
        ),
    )

    audit.record(
        provider_id=staff.provider_id,
        user_id=staff.user_id,
        membership_id=staff.membership_id,
        patient_id=details.patient_id,
        action="appointment.read",
        resource_type="appointment",
        resource_id=str(details.id),
        outcome="success",
    )

    return details


# Single-segment POST-only paths of this router.
POST_ONLY_SEGMENTS = frozenset(
    {
        "lookup",
        "search-by-national-id",
    }
)


class AppointmentReferenceReadRoute(APIRoute):
    """GET /appointments/{appointment_reference} must not capture the
    POST-only paths above: reporting no match there lets the router answer
    with its normal 405 (Allow: POST) before any dependency runs."""

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        match, child_scope = super().matches(scope)

        if (
            match is not Match.NONE
            and child_scope.get("path_params", {}).get(
                "appointment_reference"
            )
            in POST_ONLY_SEGMENTS
        ):
            return Match.NONE, {}

        return match, child_scope


# API Blueprint path (GET /appointments/{id}, where {id} is the appointment
# reference): the same staff-only read. Service callers have no access here;
# they use POST /appointments/lookup, which also verifies the patient.
router.add_api_route(
    "/{appointment_reference}",
    get_appointment_by_reference,
    methods=["GET"],
    response_model=AppointmentDetails,
    route_class_override=AppointmentReferenceReadRoute,
)


@router.get(
    "/patient/{patient_id}",
    response_model=PatientAppointmentsResponse,
)
def get_patient_appointments(
    patient_id: UUID,
    staff: StaffAppointmentReader,
    service: AppointmentServiceDependency,
    audit: StaffAuditServiceDependency,
    include_cancelled: bool = False,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=100,
        ),
    ] = 50,
) -> PatientAppointmentsResponse:
    result = service.list_patient_bookings_for_staff(
        staff=staff,
        patient_id=patient_id,
        include_cancelled=include_cancelled,
        limit=limit,
    )

    audit.record(
        provider_id=staff.provider_id,
        user_id=staff.user_id,
        membership_id=staff.membership_id,
        patient_id=patient_id,
        action="appointment.list_for_patient",
        resource_type="appointment",
        outcome="success",
    )

    return result



@router.post(
    "/search-by-national-id",
    response_model=(
        AppointmentsByNationalIdResponse
    ),
    dependencies=BookingServiceAuth,
)
def search_appointments_by_national_id(
    data: AppointmentSearchByNationalIdRequest,
    provider: CurrentProvider,
    service: AppointmentServiceDependency,
) -> AppointmentsByNationalIdResponse:

    return (
        service.search_bookings_by_national_id(
            provider_id=provider.id,
            provider_timezone=provider.timezone,
            data=data,
        )
    )  


@router.post(
    "/lookup",
    response_model=AppointmentLookupResponse,
    dependencies=BookingServiceAuth,
)
def lookup_appointment(
    data: AppointmentLookupRequest,
    provider: CurrentProvider,
    service: AppointmentServiceDependency,
) -> AppointmentLookupResponse:

    return service.lookup_booking_for_patient(
        provider_id=provider.id,
        data=data,
    )      