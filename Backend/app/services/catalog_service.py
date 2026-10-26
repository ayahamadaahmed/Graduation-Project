from datetime import date
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.models import (
    Branch,
    Department,
    Doctor,
    DoctorAvailabilitySlot,
    Provider,
    Service,
    Specialty,
)
from app.repositories.catalog_repository import (
    PUBLIC_PROVIDER_ORG_TYPES,
    CatalogRepository,
)


class DepartmentNotFoundError(LookupError):
    """Department is missing, inactive, another provider's, or outside the branch scope."""


class SpecialtyNotFoundError(LookupError):
    """Specialty is missing, inactive, or another provider's."""


class CatalogService:
    def __init__(self, repository: CatalogRepository) -> None:
        self.repository = repository

    def get_provider(self, tenant_key: str) -> Provider | None:
        return self.repository.get_provider_by_tenant_key(tenant_key)

    def get_branches(self, provider_id: UUID) -> list[Branch]:
        return self.repository.list_branches(provider_id)

    def get_departments(
        self,
        provider_id: UUID,
        branch_id: UUID | None = None,
    ) -> list[Department]:
        return self.repository.list_departments(provider_id, branch_id)

    def _scoped_department(
        self,
        provider_id: UUID,
        department_id: UUID,
        branch_id: UUID | None,
    ) -> Department:
        department = self.repository.get_department(provider_id, department_id)
        if department is None:
            raise DepartmentNotFoundError(department_id)
        # In a branch scope only provider-wide departments and that branch's own are visible.
        if (
            branch_id is not None
            and department.branch_id is not None
            and department.branch_id != branch_id
        ):
            raise DepartmentNotFoundError(department_id)
        return department

    def get_department_specialties(
        self,
        provider_id: UUID,
        department_id: UUID,
        branch_id: UUID | None = None,
    ) -> list[Specialty]:
        self._scoped_department(provider_id, department_id, branch_id)
        return self.repository.list_department_specialties(provider_id, department_id)

    def link_department_specialty(
        self,
        provider_id: UUID,
        department_id: UUID,
        specialty_id: UUID,
        branch_id: UUID | None = None,
    ) -> Specialty:
        """Link an existing specialty to an existing department; idempotent."""
        self._scoped_department(provider_id, department_id, branch_id)
        specialty = self.repository.get_specialty(provider_id, specialty_id)
        if specialty is None:
            raise SpecialtyNotFoundError(specialty_id)
        if not self.repository.department_specialty_exists(provider_id, department_id, specialty_id):
            try:
                self.repository.add_department_specialty(provider_id, department_id, specialty_id)
            except IntegrityError:
                # A concurrent request created the same link (unique key); anything else is re-raised.
                self.repository.rollback()
                if not self.repository.department_specialty_exists(provider_id, department_id, specialty_id):
                    raise
        return specialty

    def get_specialties(
        self,
        provider_id: UUID,
    ) -> list[Specialty]:
        return self.repository.list_specialties(provider_id)

    def get_services(
        self,
        provider_id: UUID,
        service_type: str | None = None,
        doctor_id: UUID | None = None,
        specialty_id: UUID | None = None,
    ) -> list[Service]:

        return self.repository.list_services(
            provider_id=provider_id,
            service_type=service_type,
            doctor_id=doctor_id,
            specialty_id=specialty_id,
        )

    def get_doctors(
        self,
        provider_id: UUID,
        specialty_id: UUID | None,
        branch_id: UUID | None,
        service_id: UUID | None,
    ) -> list[dict]:
        return self.repository.list_doctors(
            provider_id=provider_id,
            specialty_id=specialty_id,
            branch_id=branch_id,
            service_id=service_id,
        )

    def get_available_slots(
        self,
        provider_id: UUID,
        slot_date: date,
        doctor_id: UUID | None,
        branch_id: UUID | None,
        limit: int,
    ) -> list[DoctorAvailabilitySlot]:
        return self.repository.list_available_slots(
            provider_id=provider_id,
            slot_date=slot_date,
            doctor_id=doctor_id,
            branch_id=branch_id,
            limit=limit,
        )
    def doctor_is_active(
        self,
        provider_id: UUID,
        doctor_id: UUID,
    ) -> bool:
        return self.repository.doctor_is_active(
            provider_id=provider_id,
            doctor_id=doctor_id,
        )

    def get_public_providers(
        self,
        *,
        org_type: str | None = None,
    ) -> list[Provider]:

        # Omitted: every publicly visible provider type.
        if org_type is None:
            return (
                self.repository
                .list_public_providers(
                    org_type=None
                )
            )

        normalized_type = (
            org_type
            .strip()
            .lower()
        )

        if normalized_type not in PUBLIC_PROVIDER_ORG_TYPES:
            raise ValueError(
                "org_type must be "
                "clinic, hospital or diagnostic_lab"
            )

        return (
            self.repository
            .list_public_providers(
                org_type=normalized_type
            )
        )

    def get_public_provider(
        self,
        provider_id: UUID,
    ) -> Provider | None:

        return (
            self.repository
            .get_public_provider_by_id(
                provider_id
            )
        )

    def get_public_provider_branches(
        self,
        provider_id: UUID,
    ) -> list[Branch] | None:

        provider = (
            self.get_public_provider(
                provider_id
            )
        )

        if provider is None:
            return None

        return (
            self.repository
            .list_branches(
                provider_id
            )
        )
