from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models.clinical_note import ClinicalNote
from app.repositories.ehr_record_repository import EHRRecordRepository
from app.schemas.staff_ehr import (
    AllergyOut,
    AssessmentOut,
    ClinicalNoteCreateRequest,
    ClinicalNoteListResponse,
    ClinicalNoteOut,
    ConditionOut,
    LabReportDetailResponse,
    LabResultOut,
    MedicalHistoryResponse,
    MedicationOut,
    RadiologyReportDetailResponse,
    ReportListResponse,
    ReportSummaryOut,
    VisitListResponse,
    VisitOut,
)
from app.security.staff_context import StaffContext


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _json_dict(raw: str | None) -> dict[str, float]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}

    if not isinstance(value, dict):
        return {}

    return {str(k): float(v) for k, v in value.items() if isinstance(v, (int, float))}


def _json_list(raw: str | None) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []

    if not isinstance(value, list):
        return []

    return [str(item) for item in value]


def _as_float(value) -> float | None:
    return None if value is None else float(value)


class EHRRecordService:
    """Business rules for reading and writing a patient's medical record.

    Tenant isolation: every call uses ``staff.provider_id`` (taken from the
    verified token, never from the request body) and the patient must be
    registered at that provider. Anything else answers 404, so the API never
    reveals whether a patient or record exists at another provider.

    Role checks (which roles may call which endpoint) live in the router, like
    the other staff endpoints; this service enforces the record-level rules.
    """

    def __init__(self, repository: EHRRecordRepository) -> None:
        self.repository = repository

    # ========================================================
    # PATIENT ACCESS
    # ========================================================
    def _require_patient(self, staff: StaffContext, patient_id: UUID) -> None:
        profile = self.repository.get_active_profile(
            patient_id=patient_id,
            provider_id=staff.provider_id,
        )

        if profile is None:
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "PATIENT_NOT_FOUND",
                "No patient with this id is registered at this provider.",
            )

    def _require_read_access(self, staff: StaffContext, patient_id: UUID) -> None:
        """Patient check for record READS, plus the treating-doctor rule.

        A doctor may read only patients they have an encounter with, or a
        non-cancelled appointment with, at this provider. Anyone else gets the
        same 404 as an unregistered patient. Other roles are unchanged here
        (the router decides which roles reach each endpoint).
        """
        self._require_patient(staff, patient_id)

        if staff.role != "doctor":
            return

        if staff.doctor_id is None or not self.repository.doctor_has_care_relationship(
            provider_id=staff.provider_id,
            patient_id=patient_id,
            doctor_id=staff.doctor_id,
        ):
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "PATIENT_NOT_FOUND",
                "No patient with this id is registered at this provider.",
            )

    # ========================================================
    # MEDICAL HISTORY
    # ========================================================
    def get_medical_history(
        self,
        *,
        staff: StaffContext,
        patient_id: UUID,
    ) -> MedicalHistoryResponse:
        self._require_read_access(staff, patient_id)

        kwargs = {"provider_id": staff.provider_id, "patient_id": patient_id}

        return MedicalHistoryResponse(
            patient_id=patient_id,
            conditions=[
                ConditionOut.model_validate(row)
                for row in self.repository.list_conditions(**kwargs)
            ],
            allergies=[
                AllergyOut.model_validate(row)
                for row in self.repository.list_allergies(**kwargs)
            ],
            medications=[
                MedicationOut.model_validate(row)
                for row in self.repository.list_medications(**kwargs)
            ],
        )

    # ========================================================
    # PREVIOUS VISITS
    # ========================================================
    def list_visits(
        self,
        *,
        staff: StaffContext,
        patient_id: UUID,
        limit: int,
        offset: int,
    ) -> VisitListResponse:
        self._require_read_access(staff, patient_id)

        rows, total = self.repository.list_visits(
            provider_id=staff.provider_id,
            patient_id=patient_id,
            limit=limit,
            offset=offset,
        )

        items = [
            VisitOut(
                encounter_id=row.EHREncounter.id,
                encounter_type=row.EHREncounter.encounter_type,
                status=row.EHREncounter.status,
                started_at=row.EHREncounter.started_at,
                ended_at=row.EHREncounter.ended_at,
                doctor_id=row.EHREncounter.doctor_id,
                doctor_name_en=row.doctor_name_en,
                doctor_name_ar=row.doctor_name_ar,
                branch_id=row.EHREncounter.branch_id,
                branch_name_en=row.branch_name_en,
                branch_name_ar=row.branch_name_ar,
                appointment_id=row.EHREncounter.appointment_id,
            )
            for row in rows
        ]

        return VisitListResponse(
            patient_id=patient_id,
            total=total,
            limit=limit,
            offset=offset,
            items=items,
        )

    # ========================================================
    # DIAGNOSTIC REPORTS
    # ========================================================
    def list_reports(
        self,
        *,
        staff: StaffContext,
        patient_id: UUID,
        report_type: str | None,
        limit: int,
        offset: int,
    ) -> ReportListResponse:
        self._require_read_access(staff, patient_id)

        rows, total = self.repository.list_reports(
            provider_id=staff.provider_id,
            patient_id=patient_id,
            report_type=report_type,
            limit=limit,
            offset=offset,
        )

        return ReportListResponse(
            patient_id=patient_id,
            total=total,
            limit=limit,
            offset=offset,
            items=[
                ReportSummaryOut(
                    report_id=row.report_id,
                    report_type=row.report_type,
                    category=row.category,
                    status=row.status,
                    encounter_id=row.encounter_id,
                    created_at=row.created_at,
                )
                for row in rows
            ],
        )

    def get_lab_report(
        self,
        *,
        staff: StaffContext,
        patient_id: UUID,
        report_id: UUID,
    ) -> LabReportDetailResponse:
        self._require_read_access(staff, patient_id)

        found = self.repository.get_lab_report(
            provider_id=staff.provider_id,
            patient_id=patient_id,
            report_id=report_id,
        )

        if found is None:
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "REPORT_NOT_FOUND",
                "No lab report with this id exists for this patient.",
            )

        report, results = found

        return LabReportDetailResponse(
            report_id=report.id,
            patient_id=patient_id,
            encounter_id=report.encounter_id,
            document_type=report.document_type,
            status=report.status,
            unreadable_fields=_json_list(report.unreadable_fields_json),
            created_at=report.created_at,
            results=[
                LabResultOut(
                    result_index=row.result_index,
                    panel=row.panel,
                    raw_name=row.raw_name,
                    canonical_name=row.canonical_name,
                    value=_as_float(row.value),
                    unit=row.unit,
                    reference_min=_as_float(row.reference_min),
                    reference_max=_as_float(row.reference_max),
                    reference_text=row.reference_text,
                    flag=row.flag,
                    mapping_status=row.mapping_status,
                )
                for row in results
            ],
        )

    def get_radiology_report(
        self,
        *,
        staff: StaffContext,
        patient_id: UUID,
        report_id: UUID,
    ) -> RadiologyReportDetailResponse:
        self._require_read_access(staff, patient_id)

        found = self.repository.get_radiology_report(
            provider_id=staff.provider_id,
            patient_id=patient_id,
            report_id=report_id,
        )

        if found is None:
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "REPORT_NOT_FOUND",
                "No radiology report with this id exists for this patient.",
            )

        report, assessments = found

        return RadiologyReportDetailResponse(
            report_id=report.id,
            patient_id=patient_id,
            encounter_id=report.encounter_id,
            modality=report.modality,
            status=report.status,
            created_at=report.created_at,
            assessments=[
                AssessmentOut(
                    assessment_type=row.assessment_type,
                    classification=row.classification,
                    confidence=float(row.confidence),
                    probabilities=_json_dict(row.probabilities_json),
                    model_name=row.model_name,
                    model_version=row.model_version,
                    limitations=_json_list(row.limitations_json),
                    created_at=row.created_at,
                )
                for row in assessments
            ],
        )

    # ========================================================
    # CLINICAL NOTES
    # ========================================================
    @staticmethod
    def _note_out(row) -> ClinicalNoteOut:
        note = row.ClinicalNote

        return ClinicalNoteOut(
            note_id=note.id,
            patient_id=note.patient_id,
            encounter_id=note.encounter_id,
            doctor_id=note.doctor_id,
            doctor_name_en=row.doctor_name_en,
            doctor_name_ar=row.doctor_name_ar,
            note_type=note.note_type,
            title=note.title,
            note_text=note.note_text,
            status=note.status,
            signed_at=note.signed_at,
            addendum_to_note_id=note.addendum_to_note_id,
            created_at=note.created_at,
            updated_at=note.updated_at,
        )

    def list_notes(
        self,
        *,
        staff: StaffContext,
        patient_id: UUID,
        encounter_id: UUID | None,
        limit: int,
        offset: int,
    ) -> ClinicalNoteListResponse:
        self._require_read_access(staff, patient_id)

        rows, total = self.repository.list_notes(
            provider_id=staff.provider_id,
            patient_id=patient_id,
            encounter_id=encounter_id,
            limit=limit,
            offset=offset,
        )

        return ClinicalNoteListResponse(
            patient_id=patient_id,
            total=total,
            limit=limit,
            offset=offset,
            items=[self._note_out(row) for row in rows],
        )

    def get_note(
        self,
        *,
        staff: StaffContext,
        patient_id: UUID,
        note_id: UUID,
    ) -> ClinicalNoteOut:
        self._require_read_access(staff, patient_id)

        row = self.repository.get_note(
            provider_id=staff.provider_id,
            patient_id=patient_id,
            note_id=note_id,
        )

        if row is None:
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "NOTE_NOT_FOUND",
                "No clinical note with this id exists for this patient.",
            )

        return self._note_out(row)

    def create_note(
        self,
        *,
        staff: StaffContext,
        patient_id: UUID,
        data: ClinicalNoteCreateRequest,
    ) -> ClinicalNoteOut:
        # Only a doctor account can author notes (the author is always the
        # caller; it can never be supplied in the request body).
        if staff.role != "doctor" or staff.doctor_id is None:
            raise _error(
                status.HTTP_403_FORBIDDEN,
                "NOTE_AUTHOR_REQUIRED",
                "Only a doctor can write clinical notes.",
            )

        self._require_patient(staff, patient_id)

        encounter = self.repository.get_encounter(
            provider_id=staff.provider_id,
            patient_id=patient_id,
            encounter_id=data.encounter_id,
        )

        if encounter is None:
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "ENCOUNTER_NOT_FOUND",
                "No visit with this id exists for this patient.",
            )

        # Only the doctor assigned to the visit may document it.
        if encounter.doctor_id != staff.doctor_id:
            raise _error(
                status.HTTP_403_FORBIDDEN,
                "NOTE_NOT_ALLOWED",
                "Only the doctor assigned to this visit can write notes for it.",
            )

        if data.note_type == "addendum":
            original = self.repository.get_note_for_update(
                provider_id=staff.provider_id,
                patient_id=patient_id,
                note_id=data.addendum_to_note_id,
            )

            if original is None or original.encounter_id != encounter.id:
                raise _error(
                    status.HTTP_404_NOT_FOUND,
                    "NOTE_NOT_FOUND",
                    "The note being corrected was not found for this visit.",
                )

            if original.status != "signed":
                raise _error(
                    status.HTTP_409_CONFLICT,
                    "NOTE_NOT_SIGNED",
                    "Only a signed note needs an addendum; edit the draft instead.",
                )

        now = datetime.now(timezone.utc)

        note = ClinicalNote(
            id=uuid4(),
            provider_id=staff.provider_id,
            patient_id=patient_id,
            encounter_id=encounter.id,
            doctor_id=staff.doctor_id,
            note_type=data.note_type,
            title=data.title,
            note_text=data.note_text,
            status="signed" if data.sign else "draft",
            signed_at=now if data.sign else None,
            addendum_to_note_id=data.addendum_to_note_id,
            created_at=now,
            updated_at=now,
        )

        try:
            self.repository.add_note(note)
            self.repository.session.commit()
        except IntegrityError as exc:
            self.repository.session.rollback()

            raise _error(
                status.HTTP_409_CONFLICT,
                "NOTE_CONFLICT",
                "The note conflicts with the patient's record and was not saved.",
            ) from exc
        except SQLAlchemyError:
            self.repository.session.rollback()
            raise

        return self.get_note(staff=staff, patient_id=patient_id, note_id=note.id)

    def sign_note(
        self,
        *,
        staff: StaffContext,
        patient_id: UUID,
        note_id: UUID,
    ) -> ClinicalNoteOut:
        if staff.role != "doctor" or staff.doctor_id is None:
            raise _error(
                status.HTTP_403_FORBIDDEN,
                "NOTE_AUTHOR_REQUIRED",
                "Only a doctor can sign clinical notes.",
            )

        self._require_patient(staff, patient_id)

        note = self.repository.get_note_for_update(
            provider_id=staff.provider_id,
            patient_id=patient_id,
            note_id=note_id,
        )

        if note is None:
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "NOTE_NOT_FOUND",
                "No clinical note with this id exists for this patient.",
            )

        if note.doctor_id != staff.doctor_id:
            raise _error(
                status.HTTP_403_FORBIDDEN,
                "NOTE_NOT_ALLOWED",
                "Only the author of a note can sign it.",
            )

        if note.status == "signed":
            raise _error(
                status.HTTP_409_CONFLICT,
                "NOTE_ALREADY_SIGNED",
                "This note is already signed and cannot be changed.",
            )

        now = datetime.now(timezone.utc)

        try:
            note.status = "signed"
            note.signed_at = now
            note.updated_at = now
            self.repository.session.commit()
        except SQLAlchemyError:
            self.repository.session.rollback()
            raise

        return self.get_note(staff=staff, patient_id=patient_id, note_id=note_id)
