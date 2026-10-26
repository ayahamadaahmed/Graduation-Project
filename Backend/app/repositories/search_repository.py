"""Cross-provider (global) search over the public catalog.

Only active, verified clinics / hospitals / labs and their active branches,
doctors and services are visible. Callers never pass a tenant: every query
derives provider scope from the rows themselves, so a doctor, branch or slot
is returned only together with the provider that owns it.
"""

from datetime import date, time
from typing import Any
from uuid import UUID

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Branch,
    Doctor,
    DoctorAvailabilitySlot,
    DoctorBranch,
    DoctorService,
    Provider,
    Service,
    Specialty,
)
from app.repositories.doctor_eligibility import bookable_doctor_conditions


PUBLIC_ORG_TYPES = (
    "clinic",
    "hospital",
    "diagnostic_lab",
)


def _public_provider_filters() -> tuple:
    return (
        Provider.org_type.in_(PUBLIC_ORG_TYPES),
        Provider.verification_status == "verified",
        Provider.is_active == 1,
    )


def _escape_like(value: str) -> str:
    return (
        value
        .replace("[", "[[]")
        .replace("%", "[%]")
        .replace("_", "[_]")
    )


class SearchRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def search_providers(
        self,
        *,
        org_type: str | None,
        name: str | None,
        governorate: str | None,
        specialty_code: str | None,
        limit: int,
    ) -> list[Provider]:
        statement = select(Provider).where(
            *_public_provider_filters(),
        )

        if org_type:
            statement = statement.where(
                Provider.org_type == org_type,
            )

        if name:
            statement = statement.where(
                Provider.name.like(
                    f"%{_escape_like(name)}%"
                ),
            )

        if governorate:
            statement = statement.where(
                exists().where(
                    Branch.provider_id == Provider.id,
                    Branch.is_active == 1,
                    Branch.governorate == governorate,
                )
            )

        if specialty_code:
            statement = statement.where(
                exists().where(
                    Specialty.provider_id == Provider.id,
                    Specialty.is_active == 1,
                    Specialty.code == specialty_code,
                )
            )

        statement = statement.order_by(
            Provider.name,
        ).limit(limit)

        return list(self.session.scalars(statement).all())

    def search_doctors(
        self,
        *,
        provider_id: UUID | None,
        org_type: str | None,
        branch_id: UUID | None,
        governorate: str | None,
        specialty_code: str | None,
        service_code: str | None,
        name: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        statement = (
            select(
                Doctor.id,
                Doctor.provider_id,
                Doctor.specialty_id,
                Doctor.full_name_ar,
                Doctor.full_name_en,
                Doctor.consultation_fee,
                Doctor.experience_years,
                Doctor.gender,
                Doctor.rating_avg,
                Doctor.review_count,
                Doctor.accepting_new_patients,
                Specialty.code.label("specialty_code"),
                Specialty.name_ar.label("specialty_name_ar"),
                Specialty.name_en.label("specialty_name_en"),
                Provider.name.label("provider_name"),
                Provider.org_type.label("provider_org_type"),
            )
            .join(
                Provider,
                Provider.id == Doctor.provider_id,
            )
            .join(
                Specialty,
                and_(
                    Specialty.id == Doctor.specialty_id,
                    Specialty.provider_id == Doctor.provider_id,
                ),
            )
            .where(
                *_public_provider_filters(),
                *bookable_doctor_conditions(),
                Specialty.is_active == 1,
            )
        )

        if provider_id:
            statement = statement.where(
                Doctor.provider_id == provider_id,
            )

        if org_type:
            statement = statement.where(
                Provider.org_type == org_type,
            )

        if specialty_code:
            statement = statement.where(
                Specialty.code == specialty_code,
            )

        if name:
            pattern = f"%{_escape_like(name)}%"
            statement = statement.where(
                or_(
                    Doctor.full_name_en.like(pattern),
                    Doctor.full_name_ar.like(pattern),
                ),
            )

        if branch_id or governorate:
            branch_filters = [
                DoctorBranch.doctor_id == Doctor.id,
                DoctorBranch.provider_id == Doctor.provider_id,
                DoctorBranch.is_active == 1,
                Branch.id == DoctorBranch.branch_id,
                Branch.provider_id == Doctor.provider_id,
                Branch.is_active == 1,
            ]

            if branch_id:
                branch_filters.append(
                    Branch.id == branch_id,
                )

            if governorate:
                branch_filters.append(
                    Branch.governorate == governorate,
                )

            statement = statement.where(
                exists().where(*branch_filters),
            )

        if service_code:
            statement = statement.where(
                exists().where(
                    DoctorService.doctor_id == Doctor.id,
                    DoctorService.provider_id == Doctor.provider_id,
                    DoctorService.is_active == 1,
                    Service.id == DoctorService.service_id,
                    Service.provider_id == Doctor.provider_id,
                    Service.is_active == 1,
                    Service.code == service_code,
                )
            )

        statement = statement.order_by(
            Provider.name,
            Doctor.full_name_en,
        ).limit(limit)

        return [
            dict(row)
            for row in self.session.execute(statement).mappings().all()
        ]

    def search_availability(
        self,
        *,
        date_from: date,
        date_to: date,
        time_from: time | None,
        time_to: time | None,
        provider_id: UUID | None,
        org_type: str | None,
        branch_id: UUID | None,
        governorate: str | None,
        doctor_id: UUID | None,
        specialty_code: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        slot = DoctorAvailabilitySlot

        statement = (
            select(
                slot.id,
                slot.provider_id,
                slot.doctor_id,
                slot.branch_id,
                slot.slot_date,
                slot.start_time,
                slot.end_time,
                Provider.name.label("provider_name"),
                Provider.org_type.label("provider_org_type"),
                Branch.name_ar.label("branch_name_ar"),
                Branch.name_en.label("branch_name_en"),
                Branch.governorate.label("governorate"),
                Doctor.full_name_ar.label("doctor_name_ar"),
                Doctor.full_name_en.label("doctor_name_en"),
                Specialty.code.label("specialty_code"),
                Specialty.name_ar.label("specialty_name_ar"),
                Specialty.name_en.label("specialty_name_en"),
            )
            .join(
                Provider,
                Provider.id == slot.provider_id,
            )
            .join(
                Branch,
                and_(
                    Branch.id == slot.branch_id,
                    Branch.provider_id == slot.provider_id,
                ),
            )
            # Outer joins: lab slots are branch-level (doctor_id IS NULL).
            .outerjoin(
                Doctor,
                and_(
                    Doctor.id == slot.doctor_id,
                    Doctor.provider_id == slot.provider_id,
                ),
            )
            .outerjoin(
                Specialty,
                and_(
                    Specialty.id == Doctor.specialty_id,
                    Specialty.provider_id == slot.provider_id,
                ),
            )
            .where(
                *_public_provider_filters(),
                Branch.is_active == 1,
                slot.status == "available",
                slot.slot_date >= date_from,
                slot.slot_date <= date_to,
                # Same rule as the tenant slot list: doctor-less slots are
                # bookable only at labs; doctor slots need an active doctor
                # of the same provider.
                or_(
                    and_(
                        slot.doctor_id.is_(None),
                        Provider.org_type == "diagnostic_lab",
                    ),
                    and_(
                        slot.doctor_id.is_not(None),
                        Doctor.id.is_not(None),
                        *bookable_doctor_conditions(),
                    ),
                ),
            )
        )

        if time_from:
            statement = statement.where(
                slot.start_time >= time_from,
            )

        if time_to:
            statement = statement.where(
                slot.start_time < time_to,
            )

        if provider_id:
            statement = statement.where(
                slot.provider_id == provider_id,
            )

        if org_type:
            statement = statement.where(
                Provider.org_type == org_type,
            )

        if branch_id:
            statement = statement.where(
                slot.branch_id == branch_id,
            )

        if governorate:
            statement = statement.where(
                Branch.governorate == governorate,
            )

        if doctor_id:
            statement = statement.where(
                slot.doctor_id == doctor_id,
            )

        if specialty_code:
            statement = statement.where(
                Specialty.code == specialty_code,
            )

        statement = statement.order_by(
            slot.slot_date,
            slot.start_time,
            Provider.name,
            slot.id,
        ).limit(limit)

        return [
            dict(row)
            for row in self.session.execute(statement).mappings().all()
        ]
