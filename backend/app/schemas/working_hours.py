from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WorkingHourCreate(BaseModel):
    doctor_id: UUID
    branch_id: UUID

    # 0 = Monday, 6 = Sunday
    day_of_week: int = Field(
        ge=0,
        le=6,
    )

    start_time: time
    end_time: time

    slot_duration_minutes: int = Field(
        default=30,
        ge=5,
        le=240,
    )

    @model_validator(mode="after")
    def validate_time_range(self) -> "WorkingHourCreate":
        if self.end_time <= self.start_time:
            raise ValueError(
                "end_time must be after start_time"
            )

        return self


class WorkingHourOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_id: UUID
    doctor_id: UUID
    branch_id: UUID

    day_of_week: int
    start_time: time
    end_time: time
    slot_duration_minutes: int

    is_active: bool
    created_at: datetime
    updated_at: datetime


class SlotGenerationRequest(BaseModel):
    date_from: date
    date_to: date

    doctor_id: UUID | None = None
    branch_id: UUID | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> "SlotGenerationRequest":
        if self.date_to < self.date_from:
            raise ValueError(
                "date_to must be on or after date_from"
            )

        days_count = (
            self.date_to - self.date_from
        ).days

        if days_count > 90:
            raise ValueError(
                "The generation range cannot exceed 90 days"
            )

        return self


class SlotGenerationResult(BaseModel):
    provider_id: UUID
    date_from: date
    date_to: date

    working_hours_used: int
    created_slots: int
    skipped_existing_slots: int
