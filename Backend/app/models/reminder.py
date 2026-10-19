"""SQLAlchemy mappings for the existing MedMind_Booking_DB tables."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Unicode,
    UnicodeText,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Reminder(Base):
    """A scheduled appointment reminder."""

    __tablename__ = "reminders"

    __table_args__ = (
        UniqueConstraint("appointment_id", "reminder_type", "channel", name="UQ_reminders_appointment_type_channel"),
        CheckConstraint('attempt_count>=(0)', name="CK_reminders_attempt_count"),
        CheckConstraint((
            "channel='push_notification' "
            "OR channel='voice_call' "
            "OR channel='whatsapp' "
            "OR channel='sms'"
        ), name="CK_reminders_channel"),
        CheckConstraint((
            "delivery_status='cancelled' "
            "OR delivery_status='failed' "
            "OR delivery_status='delivered' "
            "OR delivery_status='sent' "
            "OR delivery_status='pending'"
        ), name="CK_reminders_delivery_status"),
        CheckConstraint((
            'patient_response IS NULL '
            "OR (patient_response='no_response' "
            "OR patient_response='cancelled' "
            "OR patient_response='confirmed')"
        ), name="CK_reminders_patient_response"),
        CheckConstraint((
            "reminder_type='pre_session_task' "
            "OR reminder_type='2h_reminder' "
            "OR reminder_type='24h_reminder' "
            "OR reminder_type='confirmation'"
        ), name="CK_reminders_type"),
        Index("IX_reminders_appointment", "appointment_id"),
        Index("IX_reminders_pending_schedule", "delivery_status", "scheduled_for"),
        Index("IX_reminders_provider_schedule", "provider_id", "scheduled_for"),
    )

    id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        primary_key=True,
        server_default=func.newid(),
    )
    provider_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("providers.id"),
    )
    appointment_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("appointments.id"),
    )
    patient_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("patients.id"),
    )
    recipient_phone: Mapped[str] = mapped_column(
        String(30),
    )
    recipient_name: Mapped[str | None] = mapped_column(
        Unicode(200),
    )
    channel: Mapped[str] = mapped_column(
        String(30),
    )
    reminder_type: Mapped[str] = mapped_column(
        String(30),
    )
    template_key: Mapped[str | None] = mapped_column(
        String(100),
    )
    content: Mapped[str | None] = mapped_column(
        UnicodeText(),
    )
    scheduled_for: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
    )
    delivery_status: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'pending'"),
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        server_default=text("0"),
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DATETIMEOFFSET,
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DATETIMEOFFSET,
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DATETIMEOFFSET,
    )
    provider_message_id: Mapped[str | None] = mapped_column(
        String(200),
    )
    last_error: Mapped[str | None] = mapped_column(
        UnicodeText(),
    )
    patient_response: Mapped[str | None] = mapped_column(
        String(20),
    )
    response_at: Mapped[datetime | None] = mapped_column(
        DATETIMEOFFSET,
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
