"""SQLAlchemy mappings for the existing MedMind_Booking_DB tables."""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    Unicode,
    UnicodeText,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Appointment(Base):
    """A booked appointment."""

    __tablename__ = "appointments"

    __table_args__ = (
        UniqueConstraint("provider_id", "appointment_reference", name="UQ_appointments_provider_reference"),
        # Lets ehr_encounters prove the appointment belongs to the same provider.
        UniqueConstraint("id", "provider_id", name="UQ_appointments_id_provider"),
        CheckConstraint((
            "status='cancelled' "
            'AND cancelled_at IS NOT NULL '
            "OR status<>'cancelled' "
            'AND cancelled_at IS NULL '
            'AND cancellation_reason IS NULL'
        ), name="CK_appointments_cancellation"),
        CheckConstraint((
            "channel='ai_agent' "
            "OR channel='staff' "
            "OR channel='mobile' "
            "OR channel='web' "
            "OR channel='whatsapp' "
            "OR channel='voice'"
        ), name="CK_appointments_channel"),
        CheckConstraint((
            "(status='no_show' "
            "OR status='completed' "
            "OR status='confirmed') "
            'AND confirmed_at IS NOT NULL '
            "OR status='pending' "
            'AND confirmed_at IS NULL '
            "OR status='cancelled'"
        ), name="CK_appointments_confirmation"),
        CheckConstraint((
            "created_by_type='system' "
            "OR created_by_type='ai_agent' "
            "OR created_by_type='staff' "
            "OR created_by_type='patient'"
        ), name="CK_appointments_created_by_type"),
        CheckConstraint('reschedule_count>=(0)', name="CK_appointments_reschedule_count"),
        CheckConstraint((
            "status='no_show' "
            "OR status='completed' "
            "OR status='cancelled' "
            "OR status='confirmed' "
            "OR status='pending'"
        ), name="CK_appointments_status"),
        CheckConstraint('end_time>start_time', name="CK_appointments_time_range"),
        Index("IX_appointments_doctor_date", "doctor_id", "scheduled_date"),
        Index("IX_appointments_patient", "patient_id"),
        Index("IX_appointments_provider_date_status", "provider_id", "scheduled_date", "status"),
        Index("IX_appointments_provider_reference", "provider_id", "appointment_reference"),
        Index("UX_appointments_active_slot", "slot_id", unique=True, mssql_where=text("status<>'cancelled'")),
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
    appointment_reference: Mapped[str] = mapped_column(
        String(40),
    )
    patient_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("patients.id"),
    )
    patient_name: Mapped[str] = mapped_column(
        Unicode(200),
    )
    phone: Mapped[str] = mapped_column(
        String(30),
    )
    slot_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("doctor_availability_slots.id"),
    )
    # NULL for lab appointments booked against a branch-level slot.
    doctor_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("doctors.id", name="FK_appointments_doctor"),
    )
    branch_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("branches.id"),
    )
    service_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("services.id"),
    )
    scheduled_date: Mapped[date] = mapped_column(
        Date,
    )
    start_time: Mapped[time] = mapped_column(
        Time,
    )
    end_time: Mapped[time] = mapped_column(
        Time,
    )
    channel: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'web'"),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'pending'"),
    )
    notes: Mapped[str | None] = mapped_column(
        UnicodeText(),
    )
    cancellation_reason: Mapped[str | None] = mapped_column(
        Unicode(500),
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DATETIMEOFFSET,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
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
    created_by_type: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'system'"),
    )
    created_by_reference: Mapped[str | None] = mapped_column(
        String(150),
    )
    reschedule_count: Mapped[int] = mapped_column(
        Integer,
        server_default=text("0"),
    )


class AppointmentStatusHistory(Base):
    """Audit trail of appointment status changes."""

    __tablename__ = "appointment_status_history"

    __table_args__ = (
        CheckConstraint((
            "changed_by='ai_agent' "
            "OR changed_by='staff' "
            "OR changed_by='patient' "
            "OR changed_by='system'"
        ), name="CK_appointment_history_changed_by"),
        CheckConstraint((
            "event_type='no_show' "
            "OR event_type='completed' "
            "OR event_type='rescheduled' "
            "OR event_type='cancelled' "
            "OR event_type='confirmed' "
            "OR event_type='created'"
        ), name="CK_appointment_history_event_type"),
        CheckConstraint((
            "new_status='no_show' "
            "OR new_status='completed' "
            "OR new_status='cancelled' "
            "OR new_status='confirmed' "
            "OR new_status='pending'"
        ), name="CK_appointment_history_new_status"),
        CheckConstraint((
            "event_type='created' "
            'AND previous_status IS NULL '
            "OR event_type<>'created' "
            'AND previous_status IS NOT NULL'
        ), name="CK_appointment_history_previous_required"),
        CheckConstraint((
            'previous_status IS NULL '
            "OR (previous_status='no_show' "
            "OR previous_status='completed' "
            "OR previous_status='cancelled' "
            "OR previous_status='confirmed' "
            "OR previous_status='pending')"
        ), name="CK_appointment_history_previous_status"),
        Index("IX_appointment_history_appointment_date", "appointment_id", "changed_at"),
        Index("IX_appointment_history_provider_date", "provider_id", "changed_at"),
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
    event_type: Mapped[str] = mapped_column(
        String(20),
    )
    previous_status: Mapped[str | None] = mapped_column(
        String(20),
    )
    new_status: Mapped[str] = mapped_column(
        String(20),
    )
    old_slot_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("doctor_availability_slots.id"),
    )
    new_slot_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("doctor_availability_slots.id"),
    )
    changed_by: Mapped[str] = mapped_column(
        String(20),
    )
    actor_reference: Mapped[str | None] = mapped_column(
        String(100),
    )
    reason: Mapped[str | None] = mapped_column(
        Unicode(500),
    )
    changed_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
