from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AppointmentCountRow(BaseModel):
    status: str
    channel: str
    count: int


class AppointmentAnalyticsOut(BaseModel):
    provider_id: UUID
    date_from: date
    date_to: date

    total: int
    by_status: dict[str, int]
    by_channel: dict[str, int]
    rows: list[AppointmentCountRow]


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_id: UUID
    user_id: UUID
    membership_id: UUID
    patient_id: UUID | None
    action: str
    resource_type: str
    resource_id: str | None
    outcome: str
    created_at: datetime
