from fastapi import APIRouter
from uuid import UUID
from app.api.dependencies import (
    CurrentProvider,
    PatientServiceDependency,
)
from app.schemas.patient import (
    PatientLookupRequest,
    PatientLookupResponse,
    PatientResolveRequest,
    PatientResolution,
    PatientProfileUpdateRequest,
    PatientProfileUpdateResponse,
)


router = APIRouter(
    prefix="/patients",
    tags=["patients"],
)


@router.post(
    "/resolve",
    response_model=PatientResolution,
)
def resolve_patient(
    data: PatientResolveRequest,
    provider: CurrentProvider,
    service: PatientServiceDependency,
) -> PatientResolution:
    return service.resolve_for_booking(
        provider_id=provider.id,
        provider_timezone=provider.timezone,
        national_id=data.national_id,
        patient_name=data.patient_name,
        phone=data.phone,
        preferred_language=(
            data.preferred_language
        ),
        channel=data.channel,
    )


@router.post(
    "/lookup",
    response_model=PatientLookupResponse,
)

def lookup_patient(
    data: PatientLookupRequest,
    provider: CurrentProvider,
    service: PatientServiceDependency,
) -> PatientLookupResponse:
    
    patient = service.lookup(
        provider_id=provider.id,
        national_id=data.national_id,
        language=data.language,
    )

    return PatientLookupResponse(
        found=patient is not None,
        patient=patient,
    )


@router.patch(
    "/{patient_id}/profile",
    response_model=
        PatientProfileUpdateResponse,
)
def update_patient_profile(
    patient_id: UUID,

    data:
        PatientProfileUpdateRequest,

    provider:
        CurrentProvider,

    service:
        PatientServiceDependency,
) -> PatientProfileUpdateResponse:

    return service.update_profile(
        provider_id=
            provider.id,

        patient_id=
            patient_id,

        patient_name=
            data.patient_name,

        phone=
            data.phone,

        language=
            data.language,

        channel=
            data.channel,
    )