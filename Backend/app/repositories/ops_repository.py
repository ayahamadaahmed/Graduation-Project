from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Appointment, StaffAuditLog


class OpsRepository:
    """Provider-scoped analytics and audit reads (aggregates and IDs only, no PHI)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def appointment_counts(
        self,
        *,
        provider_id: UUID,
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        statement = (
            select(
                Appointment.status,
                Appointment.channel,
                func.count().label("count"),
            )
            .where(
                Appointment.provider_id == provider_id,
                Appointment.scheduled_date >= date_from,
                Appointment.scheduled_date <= date_to,
            )
            .group_by(
                Appointment.status,
                Appointment.channel,
            )
            .order_by(
                Appointment.status,
                Appointment.channel,
            )
        )

        return [
            dict(row)
            for row in self.session.execute(statement).mappings().all()
        ]

    def list_audit_events(
        self,
        *,
        provider_id: UUID,
        created_from: datetime | None,
        created_to: datetime | None,
        action: str | None,
        user_id: UUID | None,
        limit: int,
    ) -> list[StaffAuditLog]:
        statement = select(StaffAuditLog).where(
            StaffAuditLog.provider_id == provider_id,
        )

        if created_from:
            statement = statement.where(
                StaffAuditLog.created_at >= created_from,
            )

        if created_to:
            statement = statement.where(
                StaffAuditLog.created_at < created_to,
            )

        if action:
            statement = statement.where(
                StaffAuditLog.action == action,
            )

        if user_id:
            statement = statement.where(
                StaffAuditLog.user_id == user_id,
            )

        statement = statement.order_by(
            StaffAuditLog.created_at.desc(),
        ).limit(limit)

        return list(self.session.scalars(statement).all())
