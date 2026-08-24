from uuid import UUID

from sqlalchemy import Boolean, Numeric, String
from sqlalchemy.dialects.mssql import NVARCHAR, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        primary_key=True,
    )
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name_ar: Mapped[str] = mapped_column(NVARCHAR(400), nullable=False)
    name_en: Mapped[str] = mapped_column(NVARCHAR(400), nullable=False)
    address_ar: Mapped[str | None] = mapped_column(
        NVARCHAR(1000),
        nullable=True,
    )
    address_en: Mapped[str | None] = mapped_column(
        NVARCHAR(1000),
        nullable=True,
    )
    governorate: Mapped[str | None] = mapped_column(
        NVARCHAR(200),
        nullable=True,
    )
    latitude: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(30), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
