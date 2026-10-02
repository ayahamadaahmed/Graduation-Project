from datetime import date
from uuid import UUID

from app.models import (
    Branch,
    Doctor,
    DoctorAvailabilitySlot,
    Provider,
    Service,
    Specialty,
)
from app.repositories.catalog_repository import CatalogRepository


class CatalogService:
    def __init__(self, repository: CatalogRepository) -> None:
        self.repository = repository

    def get_provider(self, tenant_key: str) -> Provider | None:
        return self.repository.get_provider_by_tenant_key(tenant_key)

    def get_branches(self, provider_id: UUID) -> list[Branch]:
        return self.repository.list_branches(provider_id)

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
    def get_public_providers(
        self,
        *,
        org_type: str,
    ) -> list[Provider]:

        normalized_type = (
            org_type
            .strip()
            .lower()
        )

        if normalized_type not in {
            "clinic",
            "hospital",
        }:
            raise ValueError(
                "org_type must be "
                "clinic or hospital"
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
