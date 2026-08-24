from fastapi import (
    APIRouter,
    Header,
    Query,
    status,
)
from typing import Annotated
from uuid import UUID

from app.api.dependencies import (
    AppointmentServiceDependency,
    CurrentProvider,

)

from app.schemas.appointment import (
    AppointmentCancelRequest,
    AppointmentCancelResponse,
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

@router.post(
    "",
    response_model=AppointmentCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_appointment(
    data: AppointmentCreateRequest,
    provider: CurrentProvider,
    service: AppointmentServiceDependency,
    idempotency_key: IdempotencyKey = None,
) -> AppointmentCreateResponse:

    return service.create_confirmed_booking(
        provider_id=provider.id,
        provider_timezone=provider.timezone,
        data=data,
        idempotency_key=idempotency_key,
    )

@router.post(
    "/{appointment_reference}/cancel",
    response_model=AppointmentCancelResponse,
)
def cancel_appointment(
    appointment_reference: str,
    data: AppointmentCancelRequest,
    provider: CurrentProvider,
    service: AppointmentServiceDependency,
    idempotency_key: IdempotencyKey = None,
) -> AppointmentCancelResponse:

    return service.cancel_booking(
        provider_id=provider.id,
        appointment_reference=(
            appointment_reference
        ),
        data=data,
        idempotency_key=idempotency_key,
    )

@router.post(
    "/{appointment_reference}/reschedule",
    response_model=AppointmentRescheduleResponse,
)
def reschedule_appointment(
    appointment_reference: str,
    data: AppointmentRescheduleRequest,
    provider: CurrentProvider,
    service: AppointmentServiceDependency,
    idempotency_key: IdempotencyKey = None,
) -> AppointmentRescheduleResponse:
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
    provider: CurrentProvider,
    service: AppointmentServiceDependency,
) -> AppointmentDetails:
    return service.get_booking_by_reference(
        provider_id=provider.id,
        appointment_reference=(
            appointment_reference
        ),
    )


@router.get(
    "/patient/{patient_id}",
    response_model=PatientAppointmentsResponse,
)
def get_patient_appointments(
    patient_id: UUID,
    provider: CurrentProvider,
    service: AppointmentServiceDependency,
    include_cancelled: bool = False,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=100,
        ),
    ] = 50,
) -> PatientAppointmentsResponse:
    return service.list_patient_bookings(
        provider_id=provider.id,
        patient_id=patient_id,
        include_cancelled=include_cancelled,
        limit=limit,
    )



@router.post(
    "/search-by-national-id",
    response_model=(
        AppointmentsByNationalIdResponse
    ),
)
def search_appointments_by_national_id(
    data: AppointmentSearchByNationalIdRequest,
    provider: CurrentProvider,
    service: AppointmentServiceDependency,
) -> AppointmentsByNationalIdResponse:

    return (
        service.search_bookings_by_national_id(
            provider_id=provider.id,
            data=data,
        )
    )


@router.post(
    "/lookup",
    response_model=AppointmentLookupResponse,
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
