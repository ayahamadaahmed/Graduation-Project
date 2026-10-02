from datetime import date
from uuid import UUID
import logging
import time
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models import (
    Branch,
    Doctor,
    DoctorAvailabilitySlot,
    DoctorBranch,
    Provider,
    Service,
    Specialty,
    
)
from app.models.doctor import DoctorService


logger = logging.getLogger(
    "uvicorn.error"
)

class CatalogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_provider_by_tenant_key(
        self,
        tenant_key: str,
    ) -> Provider | None:

        total_started_at = (
            time.perf_counter()
        )
        
        checkout_started_at = (
            time.perf_counter()
        )

        self.session.connection()

        checkout_ms = (
            (
                time.perf_counter()
                - checkout_started_at
            )
            * 1000
        )

        # ========================================================
        # 2. Build query
        # ========================================================

        statement = (
            select(
                Provider
            )
            .where(
                Provider.tenant_key
                == tenant_key,

                Provider.is_active
                == 1,
            )
        )

        # ========================================================
        # 3. Execute query
        # ========================================================

        query_started_at = (
            time.perf_counter()
        )

        provider = (
            self.session.scalar(
                statement
            )
        )

        query_ms = (
            (
                time.perf_counter()
                - query_started_at
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
            "provider_repository_timing "
            "checkout_ms=%.2f "
            "query_ms=%.2f "
            "total_ms=%.2f "
            "found=%s",
            checkout_ms,
            query_ms,
            total_ms,
            provider is not None,
        )

        return provider
    def list_public_providers(
        self,
        *,
        org_type: str,
    ) -> list[Provider]:

        statement = (
            select(Provider)
            .where(
                Provider.org_type
                == org_type,

                Provider.verification_status
                == "verified",

                Provider.is_active
                == 1,
            )
            .order_by(
                Provider.name
            )
        )

        return list(
            self.session
            .scalars(statement)
            .all()
        )

    def get_public_provider_by_id(
        self,
        provider_id: UUID,
    ) -> Provider | None:

        statement = (
            select(Provider)
            .where(
                Provider.id
                == provider_id,

                Provider.org_type.in_(
                    (
                        "clinic",
                        "hospital",
                    )
                ),

                Provider.verification_status
                == "verified",

                Provider.is_active
                == 1,
            )
        )

        return self.session.scalar(
            statement
        )
    def list_branches(self, provider_id: UUID) -> list[Branch]:
        statement = (
            select(Branch)
            .where(
                Branch.provider_id == provider_id,
                Branch.is_active== 1,
            )
            .order_by(Branch.name_en)
        )
        return list(self.session.scalars(statement).all())

    def list_specialties(
        self,
        provider_id: UUID,
    ) -> list[Specialty]:

        total_started_at = (
            time.perf_counter()
        )

        # ========================================================
        # 1. Connection checkout
        # ========================================================

        checkout_started_at = (
            time.perf_counter()
        )

        self.session.connection()

        checkout_ms = (
            (
                time.perf_counter()
                - checkout_started_at
            )
            * 1000
        )

        # ========================================================
        # 2. Build query
        # ========================================================

        build_started_at = (
            time.perf_counter()
        )

        statement = (
            select(Specialty)
            .where(
                Specialty.provider_id
                == provider_id,

                Specialty.is_active
                == 1,
            )
            .order_by(
                Specialty.name_en
            )
        )

        build_ms = (
            (
                time.perf_counter()
                - build_started_at
            )
            * 1000
        )

        # ========================================================
        # 3. Execute query
        # ========================================================

        execute_started_at = (
            time.perf_counter()
        )

        scalar_result = (
            self.session.scalars(
                statement
            )
        )

        execute_ms = (
            (
                time.perf_counter()
                - execute_started_at
            )
            * 1000
        )

        # ========================================================
        # 4. Fetch / ORM materialization
        # ========================================================

        fetch_started_at = (
            time.perf_counter()
        )

        rows = list(
            scalar_result.all()
        )

        fetch_ms = (
            (
                time.perf_counter()
                - fetch_started_at
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
            "catalog_repository_specialties_timing "
            "checkout_ms=%.2f "
            "build_ms=%.2f "
            "execute_ms=%.2f "
            "fetch_ms=%.2f "
            "total_ms=%.2f "
            "row_count=%d",
            checkout_ms,
            build_ms,
            execute_ms,
            fetch_ms,
            total_ms,
            len(rows),
        )

        return rows

    def list_services(
    self,
    provider_id: UUID,
    service_type: str | None = None,
    doctor_id: UUID | None = None,
    specialty_id: UUID | None = None,
) -> list[Service]:

        statement = select(
            Service
        ).where(
            Service.provider_id == provider_id,
            Service.is_active == 1,
        )

        # ========================================================
        # FILTER BY SERVICE TYPE
        # ========================================================

        if service_type is not None:

            statement = statement.where(
                Service.service_type == service_type
            )

        # ========================================================
        # FILTER BY DOCTOR
        # ========================================================

        if (
            doctor_id is not None
            or specialty_id is not None
        ):

            statement = (
                statement
                .join(
                    DoctorService,
                    DoctorService.service_id
                    == Service.id,
                )
                .where(
                    DoctorService.provider_id
                    == provider_id,
                    DoctorService.is_active
                    == 1,
                )
            )

        if doctor_id is not None:

            statement = statement.where(
                DoctorService.doctor_id
                == doctor_id
            )

        if specialty_id is not None:

            statement = (
                statement
                .join(
                    Doctor,
                    Doctor.id
                    == DoctorService.doctor_id,
                )
                .where(
                    Doctor.provider_id
                    == provider_id,
                    Doctor.specialty_id
                    == specialty_id,
                    Doctor.is_active
                    == 1,
                )
            )

        # ========================================================
        # RESULT
        # ========================================================

        statement = (
            statement
            .distinct()
            .order_by(
                Service.name_en
            )
        )

        return list(
            self.session.scalars(
                statement
            ).all()
        )
    def list_doctors(
        self,
        provider_id: UUID,
        specialty_id: UUID | None = None,
        branch_id: UUID | None = None,
        service_id: UUID | None = None,
    ) -> list[dict]:

        statement = (
            select(
                *Doctor.__table__.columns,

                Specialty.name_ar.label(
                    "specialty_name_ar"
                ),

                Specialty.name_en.label(
                    "specialty_name_en"
                ),
            )
            .join(
                Specialty,
                (
                    Specialty.id
                    == Doctor.specialty_id
                )
                & (
                    Specialty.provider_id
                    == Doctor.provider_id
                ),
            )
            .where(
                Doctor.provider_id == provider_id,
                Doctor.is_active == 1,
            )
        )

        if specialty_id:
            statement = statement.where(
                Doctor.specialty_id
                == specialty_id
            )

        if branch_id:
            statement = statement.join(
                DoctorBranch,
                DoctorBranch.doctor_id
                == Doctor.id,
            ).where(
                DoctorBranch.provider_id
                == provider_id,
                DoctorBranch.branch_id
                == branch_id,
                DoctorBranch.is_active == 1,
            )

        if service_id:
            statement = statement.join(
                DoctorService,
                DoctorService.doctor_id
                == Doctor.id,
            ).where(
                DoctorService.provider_id
                == provider_id,
                DoctorService.service_id
                == service_id,
                DoctorService.is_active == 1,
            )

        statement = (
            statement
            .distinct()
            .order_by(
                Doctor.full_name_en
            )
        )

        rows = (
            self.session
            .execute(statement)
            .mappings()
            .all()
        )

        return [
            dict(row)
            for row in rows
        ]
    def list_available_slots(
        self,
        provider_id: UUID,
        slot_date: date,
        doctor_id: UUID | None = None,
        branch_id: UUID | None = None,
        limit: int = 100,
    ) -> list[DoctorAvailabilitySlot]:

        statement = (
            select(DoctorAvailabilitySlot)
            .join(
                Doctor,
                Doctor.id == DoctorAvailabilitySlot.doctor_id,
            )
            .join(
                Branch,
                Branch.id == DoctorAvailabilitySlot.branch_id,
            )
            .where(
                # Slot must belong to the current tenant/provider.
                DoctorAvailabilitySlot.provider_id == provider_id,

                # Never expose slots that belong to catalog records
                # from another provider.
                Doctor.provider_id == provider_id,
                Branch.provider_id == provider_id,

                # Historical doctors/branches may remain in the DB,
                # but their slots must not be publicly bookable.
                Doctor.is_active == 1,
                Branch.is_active == 1,

                DoctorAvailabilitySlot.slot_date == slot_date,
                DoctorAvailabilitySlot.status == "available",
            )
        )

        if doctor_id:
            statement = statement.where(
                DoctorAvailabilitySlot.doctor_id == doctor_id,
            )

        if branch_id:
            statement = statement.where(
                DoctorAvailabilitySlot.branch_id == branch_id,
            )

        statement = statement.order_by(
            DoctorAvailabilitySlot.start_time,
            DoctorAvailabilitySlot.doctor_id,
        ).limit(limit)

        return list(
            self.session.scalars(statement).all()
        )