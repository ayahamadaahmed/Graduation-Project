"""SQLAlchemy mapping for provider departments."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Unicode,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Department(Base):
    """An organisational department of a provider (separate from specialties).

    `branch_id` NULL means the department exists provider-wide; otherwise it
    belongs to one branch of the SAME provider (enforced by a composite key).
    """

    __tablename__ = "departments"

    __table_args__ = (
        UniqueConstraint("provider_id", "code", name="UQ_departments_provider_code"),
        # Lets child tables prove they use a department of the same provider (composite foreign keys).
        UniqueConstraint("id", "provider_id", name="UQ_departments_id_provider"),
        ForeignKeyConstraint(
            ["branch_id", "provider_id"],
            ["branches.id", "branches.provider_id"],
            name="FK_departments_branch_provider",
        ),
        Index("IX_departments_provider_active", "provider_id", "is_active"),
        Index("IX_departments_provider_branch", "provider_id", "branch_id"),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        primary_key=True,
        server_default=func.newid(),
    )
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("providers.id", name="FK_departments_provider"),
    )
    branch_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
    )
    code: Mapped[str] = mapped_column(
        String(100),
    )
    name_ar: Mapped[str] = mapped_column(
        Unicode(150),
    )
    name_en: Mapped[str] = mapped_column(
        Unicode(150),
    )
    description_ar: Mapped[str | None] = mapped_column(
        Unicode(1000),
    )
    description_en: Mapped[str | None] = mapped_column(
        Unicode(1000),
    )
    phone: Mapped[str | None] = mapped_column(
        String(30),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.sysutcdatetime(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.sysutcdatetime(),
    )


class DepartmentSpecialty(Base):
    """Many-to-many link between a department and a specialty of the SAME provider.

    Both composite foreign keys carry `provider_id`, so the database rejects a
    link that crosses tenants on either side.
    """

    __tablename__ = "department_specialties"

    __table_args__ = (
        UniqueConstraint(
            "department_id",
            "specialty_id",
            name="UQ_department_specialties_department_specialty",
        ),
        ForeignKeyConstraint(
            ["department_id", "provider_id"],
            ["departments.id", "departments.provider_id"],
            name="FK_department_specialties_department_provider",
        ),
        ForeignKeyConstraint(
            ["specialty_id", "provider_id"],
            ["specialties.id", "specialties.provider_id"],
            name="FK_department_specialties_specialty_provider",
        ),
        Index("IX_department_specialties_provider_specialty", "provider_id", "specialty_id"),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        primary_key=True,
        server_default=func.newid(),
    )
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("providers.id", name="FK_department_specialties_provider"),
    )
    department_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
    )
    specialty_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.sysutcdatetime(),
    )
