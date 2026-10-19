from datetime import date
from typing import Annotated
from uuid import UUID
import logging
import time
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import (
    CatalogServiceDependency,
    CurrentProvider,
)
from app.schemas.catalog import (
    BranchOut,
    DepartmentOut,
    DepartmentSpecialtyLinkIn,
    DoctorOut,
    ProviderOut,
    ServiceOut,
    SlotOut,
    SpecialtyOut,
)
from app.security.rbac import require_staff_roles
from app.security.staff_context import StaffContext
from app.services.catalog_service import (
    DepartmentNotFoundError,
    SpecialtyNotFoundError,
)

logger = logging.getLogger(
    "uvicorn.error"
)

router = APIRouter(tags=["catalog"])

DepartmentAdmin = Annotated[
    StaffContext,
    Depends(require_staff_roles("provider_admin")),
]


def _not_found(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": code, "message": message},
    )


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
    "/departments",
    response_model=list[DepartmentOut],
)
def list_departments(
    provider: CurrentProvider,
    service: CatalogServiceDependency,
    branch_id: UUID | None = Query(default=None),
) -> list[DepartmentOut]:
    rows = service.get_departments(provider.id, branch_id)
    return [DepartmentOut.model_validate(row) for row in rows]


@router.get(
    "/departments/{department_id}/specialties",
    response_model=list[SpecialtyOut],
)
def list_department_specialties(
    department_id: UUID,
    provider: CurrentProvider,
    service: CatalogServiceDependency,
    branch_id: UUID | None = Query(default=None),
) -> list[SpecialtyOut]:
    try:
        rows = service.get_department_specialties(provider.id, department_id, branch_id)
    except DepartmentNotFoundError:
        raise _not_found("DEPARTMENT_NOT_FOUND", "Department not found.") from None
    return [SpecialtyOut.model_validate(row) for row in rows]


@router.post(
    "/departments/{department_id}/specialties",
    response_model=SpecialtyOut,
    status_code=status.HTTP_201_CREATED,
)
def link_department_specialty(
    department_id: UUID,
    data: DepartmentSpecialtyLinkIn,
    provider: CurrentProvider,
    staff: DepartmentAdmin,
    service: CatalogServiceDependency,
    branch_id: UUID | None = Query(default=None),
) -> SpecialtyOut:
    try:
        specialty = service.link_department_specialty(
            provider.id, department_id, data.specialty_id, branch_id
        )
    except DepartmentNotFoundError:
        raise _not_found("DEPARTMENT_NOT_FOUND", "Department not found.") from None
    except SpecialtyNotFoundError:
        raise _not_found("SPECIALTY_NOT_FOUND", "Specialty not found.") from None
    return SpecialtyOut.model_validate(specialty)


@router.get(
    "/specialties",
    response_model=list[SpecialtyOut],
)
def list_specialties(
    provider: CurrentProvider,
    service: CatalogServiceDependency,
) -> list[SpecialtyOut]:

    total_started_at = (
        time.perf_counter()
    )

    service_started_at = (
        time.perf_counter()
    )

    rows = service.get_specialties(
        provider.id
    )

    service_ms = (
        (
            time.perf_counter()
            - service_started_at
        )
        * 1000
    )

    serialize_started_at = (
        time.perf_counter()
    )

    result = [
        SpecialtyOut.model_validate(
            row
        )
        for row in rows
    ]

    serialize_ms = (
        (
            time.perf_counter()
            - serialize_started_at
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
        "catalog_specialties_timing "
        "service_ms=%.2f "
        "serialize_ms=%.2f "
        "total_ms=%.2f "
        "row_count=%s",
        service_ms,
        serialize_ms,
        total_ms,
        len(
            rows
        ),
    )

    return result


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
    specialty_id: UUID | None = Query(
        default=None,
    ),

) -> list[ServiceOut]:

    rows = service.get_services(
        provider_id=provider.id,
        service_type=service_type,
        doctor_id=doctor_id,
        specialty_id=specialty_id,
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
    branches = {
        branch.id: branch
        for branch in service.get_branches(provider.id)
    }
    return [
        SlotOut.from_slot(row, branches.get(row.branch_id))
        for row in rows
    ]
