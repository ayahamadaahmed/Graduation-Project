from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.mssql import (
    UNIQUEIDENTIFIER,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from app.db.base import Base


class StaffAuditLog(Base):

    __tablename__ = "staff_audit_logs"

    __table_args__ = (
        CheckConstraint(
            "outcome IN ("
            "'success', "
            "'not_found', "
            "'denied', "
            "'error'"
            ")",
            name=(
                "ck_staff_audit_logs_outcome"
            ),
        ),

        Index(
            "ix_staff_audit_logs_"
            "provider_created",
            "provider_id",
            "created_at",
        ),

        Index(
            "ix_staff_audit_logs_"
            "user_created",
            "user_id",
            "created_at",
        ),

        Index(
            "ix_staff_audit_logs_"
            "patient_created",
            "patient_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(
            as_uuid=True
        ),
        primary_key=True,
        default=uuid4,
        server_default=text(
            "NEWID()"
        ),
    )

    # Tenant where the action occurred.
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(
            as_uuid=True
        ),
        nullable=False,
    )

    # Staff principal.
    user_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(
            as_uuid=True
        ),
        nullable=False,
    )

    # Exact provider membership used.
    membership_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(
            as_uuid=True
        ),
        nullable=False,
    )

    # Nullable because denied/not-found operations
    # may not resolve a patient.
    patient_id: Mapped[
        UUID | None
    ] = mapped_column(
        UNIQUEIDENTIFIER(
            as_uuid=True
        ),
        nullable=True,
    )

    # Example:
    # patient.lookup
    # patient.record.read
    # lab.result.read
    action: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    # Example:
    # patient
    # appointment
    # lab_result
    resource_type: Mapped[str] = (
        mapped_column(
            String(50),
            nullable=False,
        )
    )

    # Optional generic internal identifier.
    # Do NOT put National ID, phone,
    # email, or message content here.
    resource_id: Mapped[
        str | None
    ] = mapped_column(
        String(100),
        nullable=True,
    )

    outcome: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    created_at: Mapped[
        datetime
    ] = mapped_column(
        DateTime(
            timezone=True
        ),
        nullable=False,
        server_default=text(
            "TODATETIMEOFFSET("
            "SYSUTCDATETIME(), "
            "'+00:00'"
            ")"
        ),
    )