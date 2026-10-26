"""SQLAlchemy mappings for the existing MedMind_Booking_DB tables."""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    Unicode,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.mssql import DATETIMEOFFSET, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DoctorWorkingHour(Base):
    """Weekly working-hours template for a doctor at a branch."""

    __tablename__ = "doctor_working_hours"

    __table_args__ = (
        # doctor_id IS NULL = branch-level lab schedule (diagnostic_lab providers only).
        Index("UX_working_hours_doctor_branch_day_start", "doctor_id", "branch_id", "day_of_week", "start_time", unique=True, mssql_where=text("doctor_id IS NOT NULL")),
        Index("UX_working_hours_branch_day_start", "branch_id", "day_of_week", "start_time", unique=True, mssql_where=text("doctor_id IS NULL")),
        CheckConstraint('day_of_week>=(0) AND day_of_week<=(6)', name="CK_working_hours_day_of_week"),
        CheckConstraint('slot_duration_minutes>=(5) AND slot_duration_minutes<=(240)', name="CK_working_hours_slot_duration"),
        CheckConstraint('end_time>start_time', name="CK_working_hours_time_range"),
        Index("IX_working_hours_branch_day", "branch_id", "day_of_week", "is_active"),
        Index("IX_working_hours_doctor_day", "doctor_id", "day_of_week", "is_active"),
        Index("IX_working_hours_provider_active", "provider_id", "is_active"),
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
    doctor_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("doctors.id", name="FK_working_hours_doctor"),
    )
    branch_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("branches.id"),
    )
    day_of_week: Mapped[int] = mapped_column(
        Integer,
    )
    start_time: Mapped[time] = mapped_column(
        Time,
    )
    end_time: Mapped[time] = mapped_column(
        Time,
    )
    slot_duration_minutes: Mapped[int] = mapped_column(
        Integer,
        server_default=text("30"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )


class DoctorScheduleException(Base):
    """A one-off day off or custom-hours exception."""

    __tablename__ = "doctor_schedule_exceptions"

    __table_args__ = (
        UniqueConstraint("doctor_id", "branch_id", "exception_date", name="UQ_schedule_exceptions_doctor_branch_date"),
        CheckConstraint((
            "exception_type='unavailable' "
            'AND start_time IS NULL '
            'AND end_time IS NULL '
            "OR exception_type='custom_hours' "
            'AND start_time IS NOT NULL '
            'AND end_time IS NOT NULL '
            'AND end_time>start_time'
        ), name="CK_schedule_exceptions_time_values"),
        CheckConstraint("exception_type='custom_hours' OR exception_type='unavailable'", name="CK_schedule_exceptions_type"),
        Index("IX_schedule_exceptions_doctor_date", "doctor_id", "exception_date", "is_active"),
        Index("IX_schedule_exceptions_provider_date", "provider_id", "exception_date", "is_active"),
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
    doctor_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("doctors.id"),
    )
    branch_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("branches.id"),
    )
    exception_date: Mapped[date] = mapped_column(
        Date,
    )
    exception_type: Mapped[str] = mapped_column(
        String(20),
    )
    start_time: Mapped[time | None] = mapped_column(
        Time,
    )
    end_time: Mapped[time | None] = mapped_column(
        Time,
    )
    reason: Mapped[str | None] = mapped_column(
        Unicode(300),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )


class DoctorAvailabilitySlot(Base):
    """A generated bookable time slot."""

    __tablename__ = "doctor_availability_slots"

    __table_args__ = (
        # doctor_id IS NULL = branch-level lab slot (diagnostic_lab providers only).
        Index("UX_availability_slots_doctor_date_time", "doctor_id", "slot_date", "start_time", unique=True, mssql_where=text("doctor_id IS NOT NULL")),
        Index("UX_availability_slots_branch_date_time", "branch_id", "slot_date", "start_time", unique=True, mssql_where=text("doctor_id IS NULL")),
        CheckConstraint((
            "status='held' "
            'AND hold_expires_at IS NOT NULL '
            "OR status<>'held' "
            'AND hold_expires_at IS NULL'
        ), name="CK_availability_slots_hold"),
        CheckConstraint((
            "status='blocked' "
            "OR status='booked' "
            "OR status='held' "
            "OR status='available'"
        ), name="CK_availability_slots_status"),
        CheckConstraint('end_time>start_time', name="CK_availability_slots_time_range"),
        Index("IX_availability_slots_branch_date", "branch_id", "slot_date", "status"),
        Index("IX_availability_slots_doctor_date", "doctor_id", "slot_date", "start_time"),
        Index("IX_availability_slots_provider_date_status", "provider_id", "slot_date", "status"),
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
    doctor_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("doctors.id", name="FK_availability_slots_doctor"),
    )
    branch_id: Mapped[UUID] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("branches.id"),
    )
    working_hours_id: Mapped[UUID | None] = mapped_column(
        UNIQUEIDENTIFIER,
        ForeignKey("doctor_working_hours.id"),
    )
    slot_date: Mapped[date] = mapped_column(
        Date,
    )
    start_time: Mapped[time] = mapped_column(
        Time,
    )
    end_time: Mapped[time] = mapped_column(
        Time,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'available'"),
    )
    hold_expires_at: Mapped[datetime | None] = mapped_column(
        DATETIMEOFFSET,
    )
    hold_reference: Mapped[str | None] = mapped_column(
        String(100),
    )
    is_waitlist_fill: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("0"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIMEOFFSET,
        server_default=func.sysutcdatetime(),
    )
