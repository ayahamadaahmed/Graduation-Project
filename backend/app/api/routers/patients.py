from fastapi import APIRouter

from app.api.dependencies import (
    CurrentProvider,
    PatientServiceDependency,
)
from app.schemas.patient import (
    PatientLookupRequest,
    PatientLookupResponse,
    PatientResolveRequest,
    PatientResolution,
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
    _provider: CurrentProvider,
    service: PatientServiceDependency,
) -> PatientLookupResponse:
    patient = service.lookup(
        national_id=data.national_id,
        language=data.language,
    )

    return PatientLookupResponse(
        found=patient is not None,
        patient=patient,
    )