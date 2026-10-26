from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import (
    Branch,
    Doctor,
    DoctorBranch,
    DoctorService,
    Service,
    Specialty,
)


class AdminCatalogRepository:
    """Provider-scoped writes for the provider-admin catalog API.

    The catalog tables have plain (not composite) foreign keys, so every
    ownership check below is what keeps one provider from linking another
    provider's specialty, branch or service.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def active_specialty_ids(
        self,
        provider_id: UUID,
        specialty_ids: list[UUID],
    ) -> set[UUID]:
        if not specialty_ids:
            return set()

        statement = select(Specialty.id).where(
            Specialty.provider_id == provider_id,
            Specialty.is_active == 1,
            Specialty.id.in_(specialty_ids),
        )
        return set(self.session.scalars(statement).all())

    def active_branch_ids(
        self,
        provider_id: UUID,
        branch_ids: list[UUID],
    ) -> set[UUID]:
        statement = select(Branch.id).where(
            Branch.provider_id == provider_id,
            Branch.is_active == 1,
            Branch.id.in_(branch_ids),
        )
        return set(self.session.scalars(statement).all())

    def active_service_ids(
        self,
        provider_id: UUID,
        service_ids: list[UUID],
    ) -> set[UUID]:
        if not service_ids:
            return set()

        statement = select(Service.id).where(
            Service.provider_id == provider_id,
            Service.is_active == 1,
            Service.id.in_(service_ids),
        )
        return set(self.session.scalars(statement).all())

    def service_code_exists(
        self,
        provider_id: UUID,
        code: str,
    ) -> bool:
        statement = select(Service.id).where(
            Service.provider_id == provider_id,
            Service.code == code,
        )
        return self.session.scalar(statement) is not None

    def license_exists(
        self,
        provider_id: UUID,
        license_number: str,
    ) -> bool:
        statement = select(Doctor.id).where(
            Doctor.provider_id == provider_id,
            Doctor.license_number == license_number,
        )
        return self.session.scalar(statement) is not None

    def get_doctor(
        self,
        provider_id: UUID,
        doctor_id: UUID,
    ) -> Doctor | None:
        statement = select(Doctor).where(
            Doctor.id == doctor_id,
            Doctor.provider_id == provider_id,
        )
        return self.session.scalar(statement)

    def doctor_link_ids(
        self,
        provider_id: UUID,
        doctor_id: UUID,
    ) -> tuple[list[UUID], list[UUID]]:
        branch_ids = self.session.scalars(
            select(DoctorBranch.branch_id)
            .where(
                DoctorBranch.provider_id == provider_id,
                DoctorBranch.doctor_id == doctor_id,
                DoctorBranch.is_active == 1,
            )
            .order_by(DoctorBranch.is_primary.desc())
        ).all()

        service_ids = self.session.scalars(
            select(DoctorService.service_id).where(
                DoctorService.provider_id == provider_id,
                DoctorService.doctor_id == doctor_id,
                DoctorService.is_active == 1,
            )
        ).all()

        return list(branch_ids), list(service_ids)

    def set_doctor_verification_status(
        self,
        *,
        provider_id: UUID,
        doctor_id: UUID,
        expected_status: str,
        new_status: str,
    ) -> bool:
        """Change the status only if it is still `expected_status` (one row),
        so two concurrent reviews cannot both apply."""
        statement = (
            update(Doctor)
            .where(
                Doctor.id == doctor_id,
                Doctor.provider_id == provider_id,
                Doctor.verification_status == expected_status,
            )
            .values(
                verification_status=new_status,
                updated_at=datetime.now(timezone.utc),
            )
            .execution_options(synchronize_session=False)
        )
        return self.session.execute(statement).rowcount == 1

    def refresh(self, row) -> None:
        self.session.refresh(row)

    def add(self, row) -> None:
        self.session.add(row)

    def flush(self) -> None:
        self.session.flush()
