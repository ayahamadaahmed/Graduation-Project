from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.core.idempotency_exceptions import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
)
from app.models import (
    Doctor,
    DoctorBranch,
    DoctorService,
    DoctorVerificationDecision,
    Service,
    ServiceSpecialty,
)
from app.repositories.admin_catalog_repository import (
    AdminCatalogRepository,
)
from app.repositories.idempotency_repository import (
    idempotency_repository,
)
from app.schemas.admin_catalog import (
    AdminDoctorCreate,
    AdminDoctorOut,
    AdminDoctorUpdate,
    AdminServiceCreate,
)
from app.schemas.catalog import ServiceOut
from app.security.staff_context import StaffContext
from app.services.idempotency_service import IdempotencyService

# Called with the new/changed resource id just before the commit, so the
# audit row is saved in the same transaction as the write it describes.
AuditHook = Callable[[str | None], None]


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


# Doctor verification: (current status, decision) -> new status. Any pair
# not listed is a 409, except the no-ops below (200, nothing recorded).
VERIFICATION_TRANSITIONS = {
    ("pending", "verified"): "verified",
    ("pending", "rejected"): "rejected",
    ("verified", "rejected"): "rejected",
    ("rejected", "resubmitted"): "pending",
}
VERIFICATION_NO_OPS = frozenset(
    {
        ("verified", "verified"),
        ("pending", "resubmitted"),
    }
)


class AdminCatalogService:
    def __init__(
        self,
        repository: AdminCatalogRepository,
        idempotency_service: IdempotencyService | None = None,
    ) -> None:
        self.repository = repository
        self.idempotency_service = idempotency_service

    def _begin_idempotent(
        self,
        *,
        provider_id: UUID,
        operation: str,
        idempotency_key: str | None,
        payload: dict[str, Any],
    ):
        """Returns (replayed_response | None, record | None)."""
        if not idempotency_key:
            return None, None

        if self.idempotency_service is None:
            raise _error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "IDEMPOTENCY_UNAVAILABLE",
                "The request could not be safely processed.",
            )

        try:
            idem = self.idempotency_service.begin(
                self.repository.session,
                tenant_id=str(provider_id),
                operation=operation,
                idempotency_key=idempotency_key,
                payload=payload,
            )
        except IdempotencyConflictError as exc:
            raise _error(
                status.HTTP_409_CONFLICT,
                "IDEMPOTENCY_CONFLICT",
                "The Idempotency-Key was already used with different data.",
            ) from exc
        except IdempotencyInProgressError as exc:
            raise _error(
                status.HTTP_409_CONFLICT,
                "IDEMPOTENCY_IN_PROGRESS",
                "The request is already being processed.",
            ) from exc
        except (RuntimeError, ValueError) as exc:
            raise _error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "IDEMPOTENCY_UNAVAILABLE",
                "The request could not be safely processed.",
            ) from exc

        if idem.is_replay:
            return idem.cached_response, None

        return None, idem.record

    def _doctor_out(self, doctor: Doctor) -> AdminDoctorOut:
        branch_ids, service_ids = self.repository.doctor_link_ids(
            doctor.provider_id,
            doctor.id,
        )

        result = AdminDoctorOut.model_validate(doctor)
        result.branch_ids = branch_ids
        result.service_ids = service_ids

        return result

    def create_doctor(
        self,
        *,
        provider_id: UUID,
        data: AdminDoctorCreate,
        idempotency_key: str | None = None,
        audit: AuditHook | None = None,
    ) -> AdminDoctorOut:
        repository = self.repository
        session = repository.session

        try:
            replayed, idempotency_record = self._begin_idempotent(
                provider_id=provider_id,
                operation="admin_create_doctor",
                idempotency_key=idempotency_key,
                payload=data.model_dump(mode="json"),
            )

            if replayed is not None:
                # Releases the transaction-scoped applock; nothing was written.
                session.rollback()
                return AdminDoctorOut.model_validate(replayed)

            if not repository.active_specialty_ids(provider_id, [data.specialty_id]):
                raise _error(
                    status.HTTP_404_NOT_FOUND,
                    "SPECIALTY_NOT_FOUND",
                    "Specialty does not belong to this provider.",
                )

            if repository.active_branch_ids(provider_id, data.branch_ids) != set(data.branch_ids):
                raise _error(
                    status.HTTP_404_NOT_FOUND,
                    "BRANCH_NOT_FOUND",
                    "Every branch must be an active branch of this provider.",
                )

            if repository.active_service_ids(provider_id, data.service_ids) != set(data.service_ids):
                raise _error(
                    status.HTTP_404_NOT_FOUND,
                    "SERVICE_NOT_FOUND",
                    "Every service must be an active service of this provider.",
                )

            license_number = (data.license_number or "").strip() or None

            if license_number and repository.license_exists(provider_id, license_number):
                raise _error(
                    status.HTTP_409_CONFLICT,
                    "DOCTOR_LICENSE_EXISTS",
                    "A doctor with this license number already exists.",
                )

            now = datetime.now(timezone.utc)
            doctor_id = uuid4()

            doctor = Doctor(
                id=doctor_id,
                provider_id=provider_id,
                specialty_id=data.specialty_id,
                full_name_ar=data.full_name_ar.strip(),
                full_name_en=data.full_name_en.strip(),
                license_number=license_number,
                consultation_fee=data.consultation_fee,
                experience_years=data.experience_years,
                gender=data.gender,
                review_count=0,
                accepting_new_patients=True,
                # New doctors stay pending until the platform verifies them.
                verification_status="pending",
                is_active=True,
                created_at=now,
                updated_at=now,
            )

            repository.add(doctor)
            # The links reference the doctor row (no ORM relationships).
            repository.flush()

            for index, branch_id in enumerate(data.branch_ids):
                repository.add(
                    DoctorBranch(
                        id=uuid4(),
                        provider_id=provider_id,
                        doctor_id=doctor_id,
                        branch_id=branch_id,
                        is_primary=index == 0,
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    )
                )

            for service_id in data.service_ids:
                repository.add(
                    DoctorService(
                        id=uuid4(),
                        provider_id=provider_id,
                        doctor_id=doctor_id,
                        service_id=service_id,
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    )
                )

            repository.flush()
            result = self._doctor_out(doctor)

            if audit is not None:
                audit(str(doctor_id))

            if idempotency_record is not None:
                idempotency_repository.mark_completed(
                    idempotency_record,
                    response=result.model_dump(mode="json"),
                )

            session.commit()

            return result

        except IntegrityError as exc:
            session.rollback()

            raise _error(
                status.HTTP_409_CONFLICT,
                "DOCTOR_CONFLICT",
                "The doctor conflicts with existing data.",
            ) from exc

        except Exception:
            session.rollback()
            raise

    def update_doctor(
        self,
        *,
        provider_id: UUID,
        doctor_id: UUID,
        data: AdminDoctorUpdate,
        audit: AuditHook | None = None,
    ) -> AdminDoctorOut:
        session = self.repository.session

        try:
            doctor = self.repository.get_doctor(provider_id, doctor_id)

            # Another provider's doctor is reported like a missing one.
            if doctor is None:
                raise _error(
                    status.HTTP_404_NOT_FOUND,
                    "DOCTOR_NOT_FOUND",
                    "Doctor not found.",
                )

            for field in ("is_active", "accepting_new_patients", "consultation_fee"):
                if field in data.model_fields_set:
                    value = getattr(data, field)

                    if value is None and field != "consultation_fee":
                        raise _error(
                            status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "INVALID_DOCTOR_UPDATE",
                            f"{field} cannot be null.",
                        )

                    setattr(doctor, field, value)

            doctor.updated_at = datetime.now(timezone.utc)
            self.repository.flush()
            result = self._doctor_out(doctor)

            if audit is not None:
                audit(str(doctor.id))

            session.commit()

            return result

        except Exception:
            session.rollback()
            raise

    def decide_doctor_verification(
        self,
        *,
        provider_id: UUID,
        doctor_id: UUID,
        decision: str,
        reason: str | None,
        reviewer: StaffContext,
        audit: AuditHook | None = None,
    ) -> AdminDoctorOut:
        """Approve ("verified") or reject ("rejected", with a reason)."""
        return self._change_doctor_verification(
            provider_id=provider_id,
            doctor_id=doctor_id,
            decision=decision,
            reason=reason if decision == "rejected" else None,
            reviewer=reviewer,
            audit=audit,
        )

    def resubmit_doctor_verification(
        self,
        *,
        provider_id: UUID,
        doctor_id: UUID,
        reviewer: StaffContext,
        audit: AuditHook | None = None,
    ) -> AdminDoctorOut:
        """Return a rejected doctor to pending for a new review."""
        return self._change_doctor_verification(
            provider_id=provider_id,
            doctor_id=doctor_id,
            decision="resubmitted",
            reason=None,
            reviewer=reviewer,
            audit=audit,
        )

    def _change_doctor_verification(
        self,
        *,
        provider_id: UUID,
        doctor_id: UUID,
        decision: str,
        reason: str | None,
        reviewer: StaffContext,
        audit: AuditHook | None,
    ) -> AdminDoctorOut:
        session = self.repository.session

        try:
            doctor = self.repository.get_doctor(provider_id, doctor_id)

            # Another provider's doctor is reported like a missing one.
            if doctor is None:
                raise _error(
                    status.HTTP_404_NOT_FOUND,
                    "DOCTOR_NOT_FOUND",
                    "Doctor not found.",
                )

            current_status = doctor.verification_status

            # Repeating an approval or a resubmission changes nothing and
            # records nothing.
            if (current_status, decision) in VERIFICATION_NO_OPS:
                return self._doctor_out(doctor)

            new_status = VERIFICATION_TRANSITIONS.get((current_status, decision))

            if new_status is None:
                raise _error(
                    status.HTTP_409_CONFLICT,
                    "DOCTOR_VERIFICATION_CONFLICT",
                    f"A {current_status} doctor cannot be {decision}.",
                )

            if not self.repository.set_doctor_verification_status(
                provider_id=provider_id,
                doctor_id=doctor_id,
                expected_status=current_status,
                new_status=new_status,
            ):
                raise _error(
                    status.HTTP_409_CONFLICT,
                    "DOCTOR_VERIFICATION_CONFLICT",
                    "The doctor's verification status changed; reload and try again.",
                )

            self.repository.add(
                DoctorVerificationDecision(
                    provider_id=provider_id,
                    doctor_id=doctor_id,
                    decision=decision,
                    previous_status=current_status,
                    reason=reason,
                    reviewer_user_id=reviewer.user_id,
                    reviewer_membership_id=reviewer.membership_id,
                )
            )
            self.repository.flush()
            self.repository.refresh(doctor)
            result = self._doctor_out(doctor)

            if audit is not None:
                audit(str(doctor.id))

            # Status, decision record and audit row: one commit.
            session.commit()

            return result

        except Exception:
            session.rollback()
            raise

    def create_service(
        self,
        *,
        provider_id: UUID,
        data: AdminServiceCreate,
        idempotency_key: str | None = None,
        audit: AuditHook | None = None,
    ) -> ServiceOut:
        repository = self.repository
        session = repository.session

        try:
            replayed, idempotency_record = self._begin_idempotent(
                provider_id=provider_id,
                operation="admin_create_service",
                idempotency_key=idempotency_key,
                payload=data.model_dump(mode="json"),
            )

            if replayed is not None:
                session.rollback()
                return ServiceOut.model_validate(replayed)

            if repository.service_code_exists(provider_id, data.code):
                raise _error(
                    status.HTTP_409_CONFLICT,
                    "SERVICE_CODE_EXISTS",
                    "A service with this code already exists.",
                )

            if repository.active_specialty_ids(provider_id, data.specialty_ids) != set(data.specialty_ids):
                raise _error(
                    status.HTTP_404_NOT_FOUND,
                    "SPECIALTY_NOT_FOUND",
                    "Every specialty must be an active specialty of this provider.",
                )

            now = datetime.now(timezone.utc)
            service_id = uuid4()

            service = Service(
                id=service_id,
                provider_id=provider_id,
                code=data.code,
                name_ar=data.name_ar.strip(),
                name_en=data.name_en.strip(),
                duration_minutes=data.duration_minutes,
                price=data.price,
                service_type=data.service_type,
                requires_preparation=data.requires_preparation,
                preparation_instructions_ar=data.preparation_instructions_ar,
                preparation_instructions_en=data.preparation_instructions_en,
                is_active=True,
                created_at=now,
                updated_at=now,
            )

            repository.add(service)
            repository.flush()

            for specialty_id in data.specialty_ids:
                repository.add(
                    ServiceSpecialty(
                        id=uuid4(),
                        provider_id=provider_id,
                        service_id=service_id,
                        specialty_id=specialty_id,
                        created_at=now,
                    )
                )

            repository.flush()
            result = ServiceOut.model_validate(service)

            if audit is not None:
                audit(str(service_id))

            if idempotency_record is not None:
                idempotency_repository.mark_completed(
                    idempotency_record,
                    response=result.model_dump(mode="json"),
                )

            session.commit()

            return result

        except IntegrityError as exc:
            session.rollback()

            raise _error(
                status.HTTP_409_CONFLICT,
                "SERVICE_CONFLICT",
                "The service conflicts with existing data.",
            ) from exc

        except Exception:
            session.rollback()
            raise
