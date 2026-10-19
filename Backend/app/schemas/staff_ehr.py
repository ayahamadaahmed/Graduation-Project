"""Request / response schemas for the staff-facing patient medical record APIs."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NoteType = Literal["progress", "consultation", "soap", "discharge", "addendum"]


class EHRBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ============================================================
# MEDICAL HISTORY
# ============================================================
class ConditionOut(EHRBase):
    id: UUID
    condition_name: str
    icd10_code: str | None = None
    clinical_status: str
    severity: str | None = None
    onset_date: date | None = None
    resolved_date: date | None = None
    notes: str | None = None
    encounter_id: UUID | None = None
    recorded_by_doctor_id: UUID | None = None
    created_at: datetime


class AllergyOut(EHRBase):
    id: UUID
    allergen: str
    allergen_type: str
    reaction: str | None = None
    severity: str
    status: str
    noted_date: date | None = None
    encounter_id: UUID | None = None
    recorded_by_doctor_id: UUID | None = None
    created_at: datetime


class MedicationOut(EHRBase):
    id: UUID
    medication_name: str
    dosage: str | None = None
    frequency: str | None = None
    route: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: str
    notes: str | None = None
    encounter_id: UUID | None = None
    prescribed_by_doctor_id: UUID | None = None
    created_at: datetime


class MedicalHistoryResponse(BaseModel):
    patient_id: UUID
    conditions: list[ConditionOut]
    allergies: list[AllergyOut]
    medications: list[MedicationOut]


# ============================================================
# PREVIOUS VISITS
# ============================================================
class VisitOut(BaseModel):
    encounter_id: UUID
    encounter_type: str
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    doctor_id: UUID | None = None
    doctor_name_en: str | None = None
    doctor_name_ar: str | None = None
    branch_id: UUID | None = None
    branch_name_en: str | None = None
    branch_name_ar: str | None = None
    appointment_id: UUID | None = None


class VisitListResponse(BaseModel):
    patient_id: UUID
    total: int
    limit: int
    offset: int
    items: list[VisitOut]


# ============================================================
# DIAGNOSTIC REPORTS
# ============================================================
class ReportSummaryOut(BaseModel):
    report_id: UUID
    report_type: Literal["lab", "radiology"]
    # lab: document type (for example "cbc"); radiology: modality
    category: str | None = None
    status: str
    encounter_id: UUID | None = None
    created_at: datetime


class ReportListResponse(BaseModel):
    patient_id: UUID
    total: int
    limit: int
    offset: int
    items: list[ReportSummaryOut]


class LabResultOut(BaseModel):
    result_index: int
    panel: str | None = None
    raw_name: str
    canonical_name: str | None = None
    value: float | None = None
    unit: str | None = None
    reference_min: float | None = None
    reference_max: float | None = None
    reference_text: str | None = None
    flag: str
    mapping_status: str


class LabReportDetailResponse(BaseModel):
    report_id: UUID
    patient_id: UUID
    encounter_id: UUID | None = None
    document_type: str | None = None
    status: str
    unreadable_fields: list[str]
    created_at: datetime
    results: list[LabResultOut]


class AssessmentOut(BaseModel):
    assessment_type: str
    classification: str
    confidence: float
    probabilities: dict[str, float]
    model_name: str
    model_version: str
    limitations: list[str]
    created_at: datetime


class RadiologyReportDetailResponse(BaseModel):
    report_id: UUID
    patient_id: UUID
    encounter_id: UUID | None = None
    modality: str
    status: str
    created_at: datetime
    assessments: list[AssessmentOut]


# ============================================================
# CLINICAL NOTES
# ============================================================
class ClinicalNoteOut(BaseModel):
    note_id: UUID
    patient_id: UUID
    encounter_id: UUID
    doctor_id: UUID
    doctor_name_en: str | None = None
    doctor_name_ar: str | None = None
    note_type: str
    title: str | None = None
    note_text: str
    status: str
    signed_at: datetime | None = None
    addendum_to_note_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class ClinicalNoteListResponse(BaseModel):
    patient_id: UUID
    total: int
    limit: int
    offset: int
    items: list[ClinicalNoteOut]


MAX_NOTE_LENGTH = 20000


class ClinicalNoteCreateRequest(BaseModel):
    encounter_id: UUID
    note_type: NoteType = "progress"
    title: str | None = Field(default=None, max_length=200)
    note_text: str = Field(min_length=1, max_length=MAX_NOTE_LENGTH)
    # True saves the note already signed (immutable); False keeps it as a draft.
    sign: bool = False
    # Required for note_type "addendum": the signed note being corrected.
    addendum_to_note_id: UUID | None = None

    @field_validator("note_text")
    @classmethod
    def note_text_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("note_text must not be blank.")
        return value

    @field_validator("title")
    @classmethod
    def title_blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def addendum_rules(self) -> "ClinicalNoteCreateRequest":
        if self.note_type == "addendum" and self.addendum_to_note_id is None:
            raise ValueError("addendum_to_note_id is required for an addendum.")

        if self.note_type != "addendum" and self.addendum_to_note_id is not None:
            raise ValueError("addendum_to_note_id is only allowed for an addendum.")

        return self
