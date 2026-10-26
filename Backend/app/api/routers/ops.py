"""Privileged provider analytics and audit reads (provider_admin only).

GET /analytics/booking-success is not implemented: failed booking attempts
are not persisted anywhere yet, so a success rate cannot be computed.
"""

from collections import Counter
from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import (
    OpsRepositoryDependency,
    StaffAuditServiceDependency,
)
from app.schemas.ops import (
    AppointmentAnalyticsOut,
    AppointmentCountRow,
    AuditEventOut,
)
from app.security.rbac import require_staff_roles
from app.security.staff_context import StaffContext


MAX_ANALYTICS_DAYS = 366

router = APIRouter(tags=["ops"])

ProviderAdmin = Annotated[
    StaffContext,
    Depends(require_staff_roles("provider_admin")),
]


@router.get(
    "/analytics/appointments",
    response_model=AppointmentAnalyticsOut,
)
def appointment_analytics(
    staff: ProviderAdmin,
    repository: OpsRepositoryDependency,
    date_from: date,
    date_to: date,
) -> AppointmentAnalyticsOut:
    if (
        date_to < date_from
        or (date_to - date_from).days >= MAX_ANALYTICS_DAYS
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_DATE_RANGE",
                "message": (
                    "date_to must be on or after date_from and "
                    f"within {MAX_ANALYTICS_DAYS} days."
                ),
            },
        )

    rows = [
        AppointmentCountRow(**row)
        for row in repository.appointment_counts(
            provider_id=staff.provider_id,
            date_from=date_from,
            date_to=date_to,
        )
    ]

    by_status: Counter[str] = Counter()
    by_channel: Counter[str] = Counter()

    for row in rows:
        by_status[row.status] += row.count
        by_channel[row.channel] += row.count

    return AppointmentAnalyticsOut(
        provider_id=staff.provider_id,
        date_from=date_from,
        date_to=date_to,
        total=sum(by_status.values()),
        by_status=dict(by_status),
        by_channel=dict(by_channel),
        rows=rows,
    )


@router.get(
    "/audit-events",
    response_model=list[AuditEventOut],
)
def list_audit_events(
    staff: ProviderAdmin,
    repository: OpsRepositoryDependency,
    audit: StaffAuditServiceDependency,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    action: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=100,
            pattern=r"^[a-z0-9_.]+$",
        ),
    ] = None,
    user_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AuditEventOut]:
    if created_from is not None and created_to is not None:
        # An offset on one bound only cannot be compared reliably.
        if (created_from.utcoffset() is None) != (created_to.utcoffset() is None):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "INVALID_DATE_RANGE",
                    "message": (
                        "created_from and created_to must both include "
                        "a UTC offset or both omit it."
                    ),
                },
            )
        if created_to < created_from:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "INVALID_DATE_RANGE",
                    "message": (
                        "created_to must be on or after created_from."
                    ),
                },
            )

    rows = repository.list_audit_events(
        provider_id=staff.provider_id,
        created_from=created_from,
        created_to=created_to,
        action=action,
        user_id=user_id,
        limit=limit,
    )

    result = [
        AuditEventOut.model_validate(row)
        for row in rows
    ]

    # Reading the audit trail is itself audited.
    audit.record(
        provider_id=staff.provider_id,
        user_id=staff.user_id,
        membership_id=staff.membership_id,
        action="audit_events.read",
        resource_type="staff_audit_log",
        outcome="success",
    )

    return result
