"""SQLAlchemy mapping for explicit cross-provider record access grants."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Unicode,
    func,
    text,
)
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PatientAccessGrant(Base):
    """A patient's consent for one provider to read another provider's records.

    One row means: patient ``patient_id`` allows ``grantee_provider_id`` to read
    the records that ``owner_provider_id`` holds. Without an active row (not
    revoked, not expired) no provider may read another provider's records.
    """

    __tablename__ = "patient_access_grants"

    __table_args__ = (
        ForeignKeyConstraint(
            ["patient_id", "owner_provider_id"],
            ["patient_provider_profiles.patient_id", "patient_provider_profiles.provider_id"],
            name="FK_patient_access_grants_owner_profile",
        ),
        CheckConstraint(
            "owner_provider_id <> grantee_provider_id",
            name="CK_patient_access_grants_distinct",
        ),
        CheckConstraint(
            "scope IN ('full_record','history_only','reports_only')",
            name="CK_patient_access_grants_scope",
        ),
        CheckConstraint(
            "granted_by IN ('patient','staff')",
            name="CK_patient_access_grants_by",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > granted_at",
            name="CK_patient_access_grants_expiry",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= granted_at",
            name="CK_patient_access_grants_revoked",
        ),
        Index(
            "UX_patient_access_grants_active",
            "patient_id",
            "owner_provider_id",
            "grantee_provider_id",
            "scope",
            unique=True,
            mssql_where=text("revoked_at IS NULL"),
        ),
        Index("IX_patient_access_grants_grantee", "grantee_provider_id", "patient_id"),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        primary_key=True,
        server_default=func.newid(),
    )
    patient_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
    )
    # The provider that holds the records.
    owner_provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
    )
    # The provider allowed to read them.
    grantee_provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("providers.id", name="FK_patient_access_grants_grantee"),
    )
    # full_record / history_only / reports_only
    scope: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'full_record'"),
    )
    # patient / staff
    granted_by: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'patient'"),
    )
    granted_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DATETIMEOFFSET,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DATETIMEOFFSET,
    )
    revoked_reason: Mapped[str | None] = mapped_column(
        Unicode(300),
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
