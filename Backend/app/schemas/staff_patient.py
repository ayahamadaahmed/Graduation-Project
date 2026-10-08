from uuid import UUID

from pydantic import BaseModel


class StaffPatientLookupResult(
    BaseModel
):

    patient_id: UUID

    patient_code: str

    display_name: str

    masked_national_id: str

    phone: str


class StaffPatientLookupResponse(
    BaseModel
):

    found: bool

    patient: (
        StaffPatientLookupResult
        | None
    ) = None