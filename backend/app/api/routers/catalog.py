from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.dependencies import (
    CatalogServiceDependency,
    CurrentProvider,
)
from app.schemas.catalog import (
    BranchOut,
    DoctorOut,
    ProviderOut,
    ServiceOut,
    SlotOut,
    SpecialtyOut,
)

router = APIRouter(tags=["catalog"])


@router.get(
    "/providers/current",
    response_model=ProviderOut,
)
def get_current_provider(
    provider: CurrentProvider,
) -> ProviderOut:
    return ProviderOut.model_validate(provider)


@router.get(
    "/branches",
    response_model=list[BranchOut],
)
def list_branches(
    provider: CurrentProvider,
    service: CatalogServiceDependency,
) -> list[BranchOut]:
    rows = service.get_branches(provider.id)
    return [BranchOut.model_validate(row) for row in rows]


@router.get(
    "/specialties",
    response_model=list[SpecialtyOut],
)
def list_specialties(
    provider: CurrentProvider,
    service: CatalogServiceDependency,
) -> list[SpecialtyOut]:
    rows = service.get_specialties(provider.id)
    return [SpecialtyOut.model_validate(row) for row in rows]


@router.get(
    "/services",
    response_model=list[ServiceOut],
)
def list_services(
    provider: CurrentProvider,
    service: CatalogServiceDependency,

    service_type: str | None = Query(
        default=None,
        max_length=30,
    ),

    doctor_id: UUID | None = Query(
        default=None,
    ),

) -> list[ServiceOut]:

    rows = service.get_services(
        provider_id=provider.id,
        service_type=service_type,
        doctor_id=doctor_id,
    )

    return [
        ServiceOut.model_validate(
            row
        )
        for row in rows
    ]


@router.get(
    "/doctors",
    response_model=list[DoctorOut],
)
def list_doctors(
    provider: CurrentProvider,
    service: CatalogServiceDependency,
    specialty_id: UUID | None = None,
    branch_id: UUID | None = None,
    service_id: UUID | None = None,
) -> list[DoctorOut]:
    rows = service.get_doctors(
        provider_id=provider.id,
        specialty_id=specialty_id,
        branch_id=branch_id,
        service_id=service_id,
    )
    return [DoctorOut.model_validate(row) for row in rows]


@router.get(
    "/slots",
    response_model=list[SlotOut],
)
def list_slots(
    provider: CurrentProvider,
    service: CatalogServiceDependency,
    slot_date: date,
    doctor_id: UUID | None = None,
    branch_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[SlotOut]:
    rows = service.get_available_slots(
        provider_id=provider.id,
        slot_date=slot_date,
        doctor_id=doctor_id,
        branch_id=branch_id,
        limit=limit,
    )
    return [SlotOut.model_validate(row) for row in rows]
