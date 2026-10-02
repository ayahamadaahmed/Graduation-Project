from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, Integer, Numeric, String, Text
from sqlalchemy.dialects.mssql import NVARCHAR, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Service(Base):
    __tablename__ = "services"

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        primary_key=True,
    )
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER(as_uuid=True),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name_ar: Mapped[str] = mapped_column(NVARCHAR(300), nullable=False)
    name_en: Mapped[str] = mapped_column(NVARCHAR(300), nullable=False)
    voice_label_ar: Mapped[str | None] = mapped_column(
        NVARCHAR(160),
        nullable=True,
    )

    voice_label_en: Mapped[str | None] = mapped_column(
        NVARCHAR(160),
        nullable=True,
    )

    voice_featured_rank: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    description_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    service_type: Mapped[str] = mapped_column(String(30), nullable=False)
    requires_preparation: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    preparation_instructions_ar: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    preparation_instructions_en: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
