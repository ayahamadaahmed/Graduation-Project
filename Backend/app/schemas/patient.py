from __future__ import annotations
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    model_validator,
    Field,
)


class PatientResolveRequest(BaseModel):
    national_id: str = Field(
        min_length=14,
        max_length=14,
    )

    patient_name: str = Field(
        min_length=2,
        max_length=200,
    )

    phone: str = Field(
        min_length=8,
        max_length=30,
    )

    preferred_language: Literal[
        "ar",
        "en",
    ] = "ar"

    channel: Literal[
        "voice",
        "whatsapp",
        "web",
        "mobile",
    ] 


class PatientLookupRequest(BaseModel):
    national_id: str = Field(
        min_length=14,
        max_length=14,
    )

    language: Literal[
        "ar",
        "en",
    ] = "ar"


class PatientRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    patient_code: str

    masked_national_id: str

    full_name_ar: str
    full_name_en: str | None = None

    phone: str
    email: str | None = None

    date_of_birth: date | None = None
    gender: str | None = None

    preferred_language: str
    location: str | None = None

    is_active: bool

    created_at: datetime
    updated_at: datetime


class PatientResolution(BaseModel):
    patient: PatientRead

    provider_profile_id: UUID

    patient_created: bool
    provider_profile_created: bool


class PatientLookupResult(BaseModel):
    patient_id: UUID
    patient_code: str

    display_name: str
    masked_national_id: str

    phone: str

    existing_patient: bool = True


class PatientLookupResponse(BaseModel):
    found: bool

    patient: PatientLookupResult | None = None

class PatientProfileUpdateRequest(
    BaseModel
):

    patient_name: str | None = Field(
        default=None,
        min_length=2,
        max_length=200,
    )

    phone: str | None = None

    language: Literal[
        "ar",
        "en",
    ]

    channel: Literal[
        "web",
        "mobile",
        "voice",
        "whatsapp",
    ]

    @model_validator(
        mode="after"
    )
    def validate_changes(
        self,
    ):
        if (
            self.patient_name is None
            and
            self.phone is None
        ):

            raise ValueError(
                "At least one patient field "
                "must be provided."
            )

        return self


class PatientProfileUpdateResponse(
    BaseModel
):

    patient_id: UUID

    display_name: str

    phone: str

    updated_fields: list[str]