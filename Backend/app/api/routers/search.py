"""Global (cross-provider) search. Public catalog data only, no tenant header.

Proposed contract from the weekly plan: GET /search/providers,
GET /search/doctors, GET /search/availability. Booking still goes through the
tenant-scoped POST /appointments with X-Tenant-ID of the selected provider,
which today only the AI channel calls, via the MCP server's service
credential (app/security/booking_auth.py). A future patient app needs its own
patient authentication, not a shared service token.
"""

from datetime import date, time
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.dependencies import SearchRepositoryDependency
from app.schemas.search import (
    SearchDoctorOut,
    SearchProviderOut,
    SearchSlotOut,
)


MAX_AVAILABILITY_DAYS = 14

OrgType = Literal[
    "clinic",
    "hospital",
    "diagnostic_lab",
]

# Shared catalog codes, e.g. "CARDIOLOGY" or "CBC": specialty and service IDs
# are per provider, so cross-provider filters use the code instead.
CatalogCode = Annotated[
    str | None,
    Query(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    ),
]

FreeText = Annotated[
    str | None,
    Query(
        min_length=2,
        max_length=100,
    ),
]

Governorate = Annotated[
    str | None,
    Query(
        min_length=1,
        max_length=100,
    ),
]


router = APIRouter(
    prefix="/search",
    tags=["search"],
)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None

    value = value.strip()

    return value or None


@router.get(
    "/providers",
    response_model=list[SearchProviderOut],
)
def search_providers(
    repository: SearchRepositoryDependency,
    org_type: OrgType | None = None,
    q: FreeText = None,
    governorate: Governorate = None,
    specialty_code: CatalogCode = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[SearchProviderOut]:
    rows = repository.search_providers(
        org_type=org_type,
        name=_clean(q),
        governorate=_clean(governorate),
        specialty_code=specialty_code,
        limit=limit,
    )

    return [
        SearchProviderOut.model_validate(row)
        for row in rows
    ]


@router.get(
    "/doctors",
    response_model=list[SearchDoctorOut],
)
def search_doctors(
    repository: SearchRepositoryDependency,
    provider_id: UUID | None = None,
    org_type: OrgType | None = None,
    branch_id: UUID | None = None,
    governorate: Governorate = None,
    specialty_code: CatalogCode = None,
    service_code: CatalogCode = None,
    q: FreeText = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[SearchDoctorOut]:
    rows = repository.search_doctors(
        provider_id=provider_id,
        org_type=org_type,
        branch_id=branch_id,
        governorate=_clean(governorate),
        specialty_code=specialty_code,
        service_code=service_code,
        name=_clean(q),
        limit=limit,
    )

    return [
        SearchDoctorOut.model_validate(row)
        for row in rows
    ]


@router.get(
    "/availability",
    response_model=list[SearchSlotOut],
)
def search_availability(
    repository: SearchRepositoryDependency,
    date_from: date,
    date_to: date | None = None,
    time_from: time | None = None,
    time_to: time | None = None,
    provider_id: UUID | None = None,
    org_type: OrgType | None = None,
    branch_id: UUID | None = None,
    governorate: Governorate = None,
    doctor_id: UUID | None = None,
    specialty_code: CatalogCode = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[SearchSlotOut]:
    date_to = date_to or date_from

    if date_to < date_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_DATE_RANGE",
                "message": "date_to must be on or after date_from.",
            },
        )

    if (date_to - date_from).days >= MAX_AVAILABILITY_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "DATE_RANGE_TOO_LARGE",
                "message": (
                    "The search range cannot exceed "
                    f"{MAX_AVAILABILITY_DAYS} days."
                ),
            },
        )

    if time_from and time_to and time_to <= time_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_TIME_RANGE",
                "message": "time_to must be after time_from.",
            },
        )

    rows = repository.search_availability(
        date_from=date_from,
        date_to=date_to,
        time_from=time_from,
        time_to=time_to,
        provider_id=provider_id,
        org_type=org_type,
        branch_id=branch_id,
        governorate=_clean(governorate),
        doctor_id=doctor_id,
        specialty_code=specialty_code,
        limit=limit,
    )

    return [
        SearchSlotOut.model_validate(row)
        for row in rows
    ]
