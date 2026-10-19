from datetime import date, time
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ORMResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProviderOut(ORMResponse):
    id: UUID
    tenant_key: str
    name: str
    slug: str
    org_type: str
    verification_status: str
    default_language: str
    timezone: str
    currency_code: str
    phone: str | None
    email: str | None
    address: str | None
    is_active: bool


class BranchOut(ORMResponse):
    id: UUID
    provider_id: UUID
    code: str
    name_ar: str
    name_en: str
    voice_label_ar: str | None = None
    voice_label_en: str | None = None
    voice_featured_rank: int | None = None
    address_ar: str | None
    address_en: str | None
    governorate: str | None
    phone: str | None
    whatsapp: str | None
    timezone: str
    is_active: bool


class DepartmentOut(ORMResponse):
    id: UUID
    provider_id: UUID
    branch_id: UUID | None
    code: str
    name_ar: str
    name_en: str
    description_ar: str | None
    description_en: str | None
    phone: str | None
    is_active: bool


class DepartmentSpecialtyLinkIn(BaseModel):
    specialty_id: UUID


class SpecialtyOut(ORMResponse):
    id: UUID
    provider_id: UUID
    code: str
    name_ar: str
    name_en: str
    description_ar: str | None
    description_en: str | None
    is_active: bool

class ServiceOut(ORMResponse):
    id: UUID
    provider_id: UUID
    code: str
    name_ar: str
    name_en: str

    voice_label_ar: str | None = None
    voice_label_en: str | None = None
    voice_featured_rank: int | None = None

    duration_minutes: int
    price: Decimal | None
    service_type: str
    requires_preparation: bool
    preparation_instructions_ar: str | None
    preparation_instructions_en: str | None
    is_active: bool

class DoctorOut(ORMResponse):
    id: UUID
    provider_id: UUID
    specialty_id: UUID

    full_name_ar: str
    full_name_en: str

    specialty_name_ar: str | None = None
    specialty_name_en: str | None = None

    consultation_fee: Decimal | None
    experience_years: int | None
    gender: str | None

    rating_avg: Decimal | None
    review_count: int

    accepting_new_patients: bool
    verification_status: str
    is_active: bool


class SlotOut(ORMResponse):
    id: UUID
    provider_id: UUID
    # None = branch-level lab slot (no doctor).
    doctor_id: UUID | None = None
    branch_id: UUID
    # Lets callers tell same-time slots at different branches apart.
    branch_name_ar: str | None = None
    branch_name_en: str | None = None
    slot_date: date
    start_time: time
    end_time: time
    status: str

    @classmethod
    def from_slot(cls, slot, branch=None) -> "SlotOut":
        item = cls.model_validate(slot)

        if branch is not None:
            item.branch_name_ar = branch.name_ar
            item.branch_name_en = branch.name_en

        return item
