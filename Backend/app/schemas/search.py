from datetime import date, time
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SearchProviderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    org_type: str
    default_language: str


class SearchDoctorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_id: UUID
    provider_name: str
    provider_org_type: str

    specialty_id: UUID
    specialty_code: str
    specialty_name_ar: str
    specialty_name_en: str

    full_name_ar: str
    full_name_en: str

    consultation_fee: Decimal | None
    experience_years: int | None
    gender: str | None
    rating_avg: Decimal | None
    review_count: int
    accepting_new_patients: bool


class SearchSlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_id: UUID
    provider_name: str
    provider_org_type: str

    branch_id: UUID
    branch_name_ar: str
    branch_name_en: str
    governorate: str | None

    # None = branch-level lab slot (no doctor).
    doctor_id: UUID | None = None
    doctor_name_ar: str | None = None
    doctor_name_en: str | None = None
    specialty_code: str | None = None
    specialty_name_ar: str | None = None
    specialty_name_en: str | None = None

    slot_date: date
    start_time: time
    end_time: time
