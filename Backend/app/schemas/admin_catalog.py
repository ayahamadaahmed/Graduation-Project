from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AdminDoctorCreate(BaseModel):
    specialty_id: UUID

    full_name_ar: str = Field(min_length=2, max_length=200)
    full_name_en: str = Field(min_length=2, max_length=200)

    license_number: str | None = Field(default=None, max_length=100)
    consultation_fee: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    experience_years: int | None = Field(default=None, ge=0, le=80)
    gender: Literal["male", "female"] | None = None

    # The first branch is the primary one.
    branch_ids: list[UUID] = Field(min_length=1, max_length=20)
    service_ids: list[UUID] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def reject_duplicates(self) -> "AdminDoctorCreate":
        if len(set(self.branch_ids)) != len(self.branch_ids):
            raise ValueError("branch_ids must be unique")

        if len(set(self.service_ids)) != len(self.service_ids):
            raise ValueError("service_ids must be unique")

        return self


class AdminDoctorUpdate(BaseModel):
    is_active: bool | None = None
    accepting_new_patients: bool | None = None
    consultation_fee: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)

    @model_validator(mode="after")
    def require_change(self) -> "AdminDoctorUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")

        return self


# Same limit as the appointment cancellation reason. Counted in UTF-16 code
# units, as NVARCHAR(500) counts them: an emoji or other character outside
# the Basic Multilingual Plane takes two.
DOCTOR_REJECTION_REASON_MAX_LENGTH = 500


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


class DoctorVerificationRequest(BaseModel):
    """A verification decision. A rejection needs a reason (1-500 UTF-16
    code units after trimming); an approval takes none."""

    decision: Literal["verified", "rejected"]
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def check_reason(self) -> "DoctorVerificationRequest":
        reason = (self.reason or "").strip()

        if self.decision == "rejected":
            if not reason:
                raise ValueError("reason is required to reject a doctor")

            if _utf16_length(reason) > DOCTOR_REJECTION_REASON_MAX_LENGTH:
                raise ValueError(
                    f"reason must be at most {DOCTOR_REJECTION_REASON_MAX_LENGTH} characters"
                )

        elif reason:
            raise ValueError("reason is only accepted when rejecting")

        self.reason = reason or None

        return self


class AdminDoctorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_id: UUID
    specialty_id: UUID
    full_name_ar: str
    full_name_en: str
    license_number: str | None
    consultation_fee: Decimal | None
    experience_years: int | None
    gender: str | None
    accepting_new_patients: bool
    verification_status: str
    is_active: bool

    branch_ids: list[UUID] = []
    service_ids: list[UUID] = []


class AdminServiceCreate(BaseModel):
    code: str = Field(
        min_length=2,
        max_length=50,
        pattern=r"^[A-Z0-9][A-Z0-9_-]*$",
    )
    name_ar: str = Field(min_length=2, max_length=150)
    name_en: str = Field(min_length=2, max_length=150)

    service_type: Literal[
        "consultation",
        "follow_up",
        "teleconsultation",
        "procedure",
        "surgery",
        "diagnostic",
    ] = "consultation"

    duration_minutes: int = Field(ge=5, le=480)
    price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)

    requires_preparation: bool = False
    preparation_instructions_ar: str | None = Field(default=None, max_length=2000)
    preparation_instructions_en: str | None = Field(default=None, max_length=2000)

    specialty_ids: list[UUID] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def reject_duplicates(self) -> "AdminServiceCreate":
        if len(set(self.specialty_ids)) != len(self.specialty_ids):
            raise ValueError("specialty_ids must be unique")

        return self
