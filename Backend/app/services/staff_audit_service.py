from uuid import (
    UUID,
    uuid4,
)

from app.models.staff_audit_log import (
    StaffAuditLog,
)
from app.repositories.staff_audit_repository import (
    StaffAuditRepository,
)


ALLOWED_AUDIT_OUTCOMES = frozenset(
    {
        "success",
        "not_found",
        "denied",
        "error",
    }
)


class StaffAuditService:

    def __init__(
        self,
        repository: StaffAuditRepository,
    ) -> None:

        self.repository = repository

    def record(
        self,
        *,
        provider_id: UUID,
        user_id: UUID,
        membership_id: UUID,
        action: str,
        resource_type: str,
        outcome: str,
        patient_id: UUID | None = None,
        resource_id: str | None = None,
    ) -> StaffAuditLog:

        if (
            outcome
            not in ALLOWED_AUDIT_OUTCOMES
        ):
            raise ValueError(
                "Unsupported audit outcome."
            )

        normalized_action = (
            action.strip()
        )

        normalized_resource_type = (
            resource_type.strip()
        )

        if not normalized_action:

            raise ValueError(
                "Audit action is required."
            )

        if not normalized_resource_type:

            raise ValueError(
                "Audit resource type "
                "is required."
            )

        session = (
            self.repository.session
        )

        try:

            audit_log = StaffAuditLog(
                id=uuid4(),
                provider_id=provider_id,
                user_id=user_id,
                membership_id=(
                    membership_id
                ),
                patient_id=patient_id,
                action=normalized_action,
                resource_type=(
                    normalized_resource_type
                ),
                resource_id=resource_id,
                outcome=outcome,
            )

            self.repository.add(
                audit_log
            )

            session.commit()

            session.refresh(
                audit_log
            )

            return audit_log

        except Exception:

            session.rollback()

            raise