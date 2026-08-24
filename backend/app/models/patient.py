from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    LargeBinary,
    String,
    Unicode,
    func,
    text,
)
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("NEWID()"),
    )

    patient_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    # Deterministic value used for patient lookup.
    national_id_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    # Encrypted national ID. Never expose it in responses.
    national_id_encrypted: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
    )

    national_id_last4: Mapped[str] = mapped_column(
        String(4),
        nullable=False,
    )

    full_name_ar: Mapped[str] = mapped_column(
        Unicode(200),
        nullable=False,
    )

    full_name_en: Mapped[str | None] = mapped_column(
        Unicode(200),
        nullable=True,
    )

    date_of_birth: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    gender: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
    )

    phone: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    email: Mapped[str | None] = mapped_column(
        String(254),
        nullable=True,
    )

    preferred_language: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    location: Mapped[str | None] = mapped_column(
        Unicode(150),
        nullable=True,
    )

    digital_literacy_flag: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.sysutcdatetime(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.sysutcdatetime(),
        onupdate=func.sysutcdatetime(),
    )

    @property
    def masked_national_id(self) -> str:
        return f"{'*' * 10}{self.national_id_last4}"