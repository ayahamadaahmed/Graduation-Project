from uuid import UUID

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.mssql import NVARCHAR, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Specialty(Base):
    __tablename__ = "specialties"

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        primary_key=True,
    )
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name_ar: Mapped[str] = mapped_column(NVARCHAR(300), nullable=False)
    name_en: Mapped[str] = mapped_column(NVARCHAR(300), nullable=False)
    description_ar: Mapped[str | None] = mapped_column(
        NVARCHAR(2000),
        nullable=True,
    )
    description_en: Mapped[str | None] = mapped_column(
        NVARCHAR(2000),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
