from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import (
    CurrentProvider,
    WorkingHoursServiceDependency,
)
from app.schemas.working_hours import (
    SlotGenerationRequest,
    SlotGenerationResult,
    WorkingHourCreate,
    WorkingHourOut,
)

router = APIRouter(
    prefix="/admin/working-hours",
    tags=["admin working hours"],
)


@router.post(
    "",
    response_model=WorkingHourOut,
    status_code=status.HTTP_201_CREATED,
)
def create_working_hour(
    data: WorkingHourCreate,
    provider: CurrentProvider,
    service: WorkingHoursServiceDependency,
) -> WorkingHourOut:
    working_hour = service.create(
        provider_id=provider.id,
        data=data,
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
    service: WorkingHoursServiceDependency,
) -> SlotGenerationResult:
    return service.generate_slots(
        provider_id=provider.id,
        provider_timezone=provider.timezone,
        data=data,
    )