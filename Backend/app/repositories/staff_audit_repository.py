from sqlalchemy.orm import Session

from app.models.staff_audit_log import (
    StaffAuditLog,
)


class StaffAuditRepository:

    def __init__(
        self,
        session: Session,
    ) -> None:

        self.session = session

    def add(
        self,
        audit_log: StaffAuditLog,
    ) -> StaffAuditLog:

        self.session.add(
            audit_log
        )

        self.session.flush()

        return audit_log