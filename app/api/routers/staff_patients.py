from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
)

from app.api.dependencies import (
    CurrentProvider,
    PatientServiceDependency,
    StaffAuditServiceDependency,
)
from app.schemas.patient import (
    PatientLookupRequest,
)
from app.schemas.staff_patient import (
    StaffPatientLookupResponse,
    StaffPatientLookupResult,
)
from app.security.rbac import (
    require_staff_roles,
)
from app.security.staff_context import (
    StaffContext,
)


router = APIRouter(
    prefix="/staff/patients",
    tags=["staff patients"],
)


StaffPatientReader = Annotated[
    StaffContext,
    Depends(
        require_staff_roles(
            "doctor",
            "receptionist",
            "lab_staff",
        )
    ),
]

@router.post(
    "/lookup",
    response_model=(
        StaffPatientLookupResponse
    ),
)
def lookup_patient_for_staff(
    data: PatientLookupRequest,
    provider: CurrentProvider,
    staff: StaffPatientReader,
    service: PatientServiceDependency,
    audit: StaffAuditServiceDependency,
) -> StaffPatientLookupResponse:

    patient = service.lookup(
        provider_id=provider.id,
        national_id=data.national_id,
        language=data.language,
    )

    if patient is None:

        audit.record(
            provider_id=provider.id,
            user_id=staff.user_id,
            membership_id=(
                staff.membership_id
            ),
            action="patient.lookup",
            resource_type="patient",
            outcome="not_found",
        )

        return StaffPatientLookupResponse(
            found=False,
            patient=None,
        )

    audit.record(
        provider_id=provider.id,
        user_id=staff.user_id,
        membership_id=(
            staff.membership_id
        ),
        patient_id=(
            patient.patient_id
        ),
        action="patient.lookup",
        resource_type="patient",
        outcome="success",
    )

    return StaffPatientLookupResponse(
        found=True,
        patient=(
            StaffPatientLookupResult(
                patient_id=(
                    patient.patient_id
                ),
                patient_code=(
                    patient.patient_code
                ),
                display_name=(
                    patient.display_name
                ),
                masked_national_id=(
                    patient.masked_national_id
                ),
                phone=patient.phone,
            )
        ),
    )