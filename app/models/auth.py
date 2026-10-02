from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
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


class UserAccount(Base):
    """
    Global MedMind staff identity.

    A user account is not tied directly
    to one provider. Provider access is
    defined through ProviderMembership.
    """

    __tablename__ = "user_accounts"

    __table_args__ = (
        UniqueConstraint(
            "email",
            name="uq_user_accounts_email",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("NEWID()"),
    )

    # Store normalized lowercase email.
    email: Mapped[str] = mapped_column(
        String(254),
        nullable=False,
    )

    # Never store plaintext passwords.
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("1"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text(
            "TODATETIMEOFFSET("
            "SYSUTCDATETIME(), "
            "'+00:00'"
            ")"
        ),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text(
            "TODATETIMEOFFSET("
            "SYSUTCDATETIME(), "
            "'+00:00'"
            ")"
        ),
        onupdate=func.sysutcdatetime(),
    )


class ProviderMembership(Base):
    """
    Authorizes a MedMind user inside
    one provider / tenant.
    """

    __tablename__ = "provider_memberships"

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "provider_id",
            name=(
                "uq_provider_memberships_"
                "user_provider"
            ),
        ),

        CheckConstraint(
            "role IN ("
            "'provider_admin', "
            "'doctor', "
            "'receptionist', "
            "'lab_staff'"
            ")",
            name=(
                "ck_provider_memberships_role"
            ),
        ),

        CheckConstraint(
            "("
            "role = 'doctor' "
            "AND doctor_id IS NOT NULL"
            ") OR ("
            "role <> 'doctor' "
            "AND doctor_id IS NULL"
            ")",
            name=(
                "ck_provider_memberships_"
                "doctor_role"
            ),
        ),

        Index(
            "ix_provider_memberships_provider",
            "provider_id",
            "is_active",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("NEWID()"),
    )

    user_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        ForeignKey(
            "user_accounts.id"
        ),
        nullable=False,
    )

    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        ForeignKey(
            "providers.id"
        ),
        nullable=False,
    )

    # Initial RBAC roles:
    #
    # provider_admin
    # doctor
    # receptionist
    # lab_staff
    role: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    # Required only when role == doctor.
    doctor_id: Mapped[
        UUID | None
    ] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        ForeignKey(
            "doctors.id"
        ),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("1"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text(
            "TODATETIMEOFFSET("
            "SYSUTCDATETIME(), "
            "'+00:00'"
            ")"
        ),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text(
            "TODATETIMEOFFSET("
            "SYSUTCDATETIME(), "
            "'+00:00'"
            ")"
        ),
        onupdate=func.sysutcdatetime(),
    )