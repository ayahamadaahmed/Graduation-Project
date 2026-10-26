from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import (
    CurrentProvider,
    StaffAuditServiceDependency,
    WorkingHoursServiceDependency,
)
from app.schemas.working_hours import (
    SlotGenerationRequest,
    SlotGenerationResult,
    WorkingHourCreate,
    WorkingHourOut,
)
from app.security.rbac import require_staff_roles
from app.security.staff_context import StaffContext

router = APIRouter(
    prefix="/admin/working-hours",
    tags=["admin working hours"],
)

# Writes need a provider_admin of the X-Tenant-ID provider; each write and
# its audit row share one commit. The list stays readable with X-Tenant-ID
# only: the MCP booking tools use it.
ProviderAdmin = Annotated[
    StaffContext,
    Depends(require_staff_roles("provider_admin")),
]


@router.post(
    "",
    response_model=WorkingHourOut,
    status_code=status.HTTP_201_CREATED,
)
def create_working_hour(
    data: WorkingHourCreate,
    provider: CurrentProvider,
    staff: ProviderAdmin,
    service: WorkingHoursServiceDependency,
    audit: StaffAuditServiceDependency,
) -> WorkingHourOut:
    working_hour = service.create(
        provider_id=provider.id,
        data=data,
        audit=audit.write_hook(
            staff=staff,
            action="working_hours.create",
            resource_type="doctor_working_hours",
        ),
    )

    return WorkingHourOut.model_validate(
        working_hour
    )


@router.get(
    "",
    response_model=list[WorkingHourOut],
)
def list_working_hours(
    provider: CurrentProvider,
    service: WorkingHoursServiceDependency,
    doctor_id: UUID | None = None,
    branch_id: UUID | None = None,
    day_of_week: Annotated[
        int | None,
        Query(ge=0, le=6),
    ] = None,
) -> list[WorkingHourOut]:
    rows = service.list(
        provider_id=provider.id,
        doctor_id=doctor_id,
        branch_id=branch_id,
        day_of_week=day_of_week,
    )

    return [
        WorkingHourOut.model_validate(row)
        for row in rows
    ]


@router.post(
    "/generate-slots",
    response_model=SlotGenerationResult,
)
def generate_slots(
    data: SlotGenerationRequest,
    provider: CurrentProvider,
    staff: ProviderAdmin,
    service: WorkingHoursServiceDependency,
    audit: StaffAuditServiceDependency,
) -> SlotGenerationResult:
    return service.generate_slots(
        provider_id=provider.id,
        provider_timezone=provider.timezone,
        data=data,
        audit=audit.write_hook(
            staff=staff,
            action="availability_slots.generate",
            resource_type="doctor_availability_slots",
        ),
    )
