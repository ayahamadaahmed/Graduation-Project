"""Provider-admin maintenance of the data used by search and booking.

Proposed contract (the weekly plan leaves the exact routes TBD). Every route
needs a provider_admin of the X-Tenant-ID provider. Each write and its audit
row are committed together. Creates accept an optional Idempotency-Key so a
retried request cannot create a second doctor or service. Working hours and
slot generation stay under /admin/working-hours.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status

from app.api.dependencies import (
    AdminCatalogServiceDependency,
    CurrentProvider,
    StaffAuditServiceDependency,
)
from app.schemas.admin_catalog import (
    AdminDoctorCreate,
    AdminDoctorOut,
    AdminDoctorUpdate,
    AdminServiceCreate,
    DoctorVerificationRequest,
)
from app.schemas.catalog import ServiceOut
from app.security.rbac import require_staff_roles
from app.security.staff_context import StaffContext


router = APIRouter(
    prefix="/admin",
    tags=["admin catalog"],
)

ProviderAdmin = Annotated[
    StaffContext,
    Depends(require_staff_roles("provider_admin")),
]

# Same header rules as the booking routes.
IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
    ),
]



@router.post(
    "/doctors",
    response_model=AdminDoctorOut,
    status_code=status.HTTP_201_CREATED,
)
def create_doctor(
    data: AdminDoctorCreate,
    provider: CurrentProvider,
    staff: ProviderAdmin,
    service: AdminCatalogServiceDependency,
    audit: StaffAuditServiceDependency,
    idempotency_key: IdempotencyKey = None,
) -> AdminDoctorOut:
    return service.create_doctor(
        provider_id=provider.id,
        data=data,
        idempotency_key=idempotency_key,
        audit=audit.write_hook(
            staff=staff,
            action="doctor.create",
            resource_type="doctor",
        ),
    )


@router.patch(
    "/doctors/{doctor_id}",
    response_model=AdminDoctorOut,
)
def update_doctor(
    doctor_id: UUID,
    data: AdminDoctorUpdate,
    provider: CurrentProvider,
    staff: ProviderAdmin,
    service: AdminCatalogServiceDependency,
    audit: StaffAuditServiceDependency,
) -> AdminDoctorOut:
    return service.update_doctor(
        provider_id=provider.id,
        doctor_id=doctor_id,
        data=data,
        audit=audit.write_hook(
            staff=staff,
            action="doctor.update",
            resource_type="doctor",
        ),
    )


VERIFICATION_AUDIT_ACTIONS = {
    "verified": "doctor.verify",
    "rejected": "doctor.reject",
}


@router.post(
    "/doctors/{doctor_id}/verification",
    response_model=AdminDoctorOut,
)
def decide_doctor_verification(
    doctor_id: UUID,
    data: DoctorVerificationRequest,
    provider: CurrentProvider,
    staff: ProviderAdmin,
    service: AdminCatalogServiceDependency,
    audit: StaffAuditServiceDependency,
) -> AdminDoctorOut:
    """Approve (pending -> verified) or reject (pending/verified -> rejected,
    reason required) one of this provider's doctors."""
    return service.decide_doctor_verification(
        provider_id=provider.id,
        doctor_id=doctor_id,
        decision=data.decision,
        reason=data.reason,
        reviewer=staff,
        audit=audit.write_hook(
            staff=staff,
            action=VERIFICATION_AUDIT_ACTIONS[data.decision],
            resource_type="doctor",
        ),
    )


@router.post(
    "/doctors/{doctor_id}/resubmit",
    response_model=AdminDoctorOut,
)
def resubmit_doctor_verification(
    doctor_id: UUID,
    provider: CurrentProvider,
    staff: ProviderAdmin,
    service: AdminCatalogServiceDependency,
    audit: StaffAuditServiceDependency,
) -> AdminDoctorOut:
    """Return a rejected doctor to pending for a new review."""
    return service.resubmit_doctor_verification(
        provider_id=provider.id,
        doctor_id=doctor_id,
        reviewer=staff,
        audit=audit.write_hook(
            staff=staff,
            action="doctor.resubmit",
            resource_type="doctor",
        ),
    )


@router.post(
    "/services",
    response_model=ServiceOut,
    status_code=status.HTTP_201_CREATED,
)
def create_service(
    data: AdminServiceCreate,
    provider: CurrentProvider,
    staff: ProviderAdmin,
    service: AdminCatalogServiceDependency,
    audit: StaffAuditServiceDependency,
    idempotency_key: IdempotencyKey = None,
) -> ServiceOut:
    return service.create_service(
        provider_id=provider.id,
        data=data,
        idempotency_key=idempotency_key,
        audit=audit.write_hook(
            staff=staff,
            action="service.create",
            resource_type="service",
        ),
    )
