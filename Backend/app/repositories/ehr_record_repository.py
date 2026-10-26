from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    exists,
    func,
    literal_column,
    select,
    union_all,
)
from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.models.branch import Branch
from app.models.clinical_note import ClinicalNote
from app.models.diagnostic_assessment import DiagnosticAssessment
from app.models.doctor import Doctor
from app.models.ehr_encounter import EHREncounter
from app.models.lab_report import LabReport
from app.models.lab_result import LabResult
from app.models.patient_allergy import PatientAllergy
from app.models.patient_condition import PatientCondition
from app.models.patient_medication import PatientMedication
from app.models.patient_provider_profile import PatientProviderProfile
from app.models.radiology_report import RadiologyReport


# Appointment statuses that prove a doctor-patient relationship for EHR reads.
CARE_RELATIONSHIP_APPOINTMENT_STATUSES = ("confirmed", "completed")


class EHRRecordRepository:
    """Read/write access to a patient's medical record.

    Every query is scoped by BOTH provider_id and patient_id, so a row from
    another provider can never be returned, even if its id is guessed.
    This repository never commits; the service owns the transaction.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    # ========================================================
    # PATIENT ACCESS
    # ========================================================
    def get_active_profile(
        self,
        *,
        patient_id: UUID,
        provider_id: UUID,
    ) -> PatientProviderProfile | None:
        statement = select(PatientProviderProfile).where(
            PatientProviderProfile.patient_id == patient_id,
            PatientProviderProfile.provider_id == provider_id,
            PatientProviderProfile.is_active == True,  # noqa: E712
        )

        return self.session.scalar(statement)

    def doctor_has_care_relationship(
        self,
        *,
        provider_id: UUID,
        patient_id: UUID,
        doctor_id: UUID,
    ) -> bool:
        """True if, at this provider, the doctor has an encounter with the
        patient or an accepted (confirmed / completed) appointment with them.

        pending (never confirmed), cancelled and no_show appointments do not
        qualify on their own; an encounter still does.
        """
        encounter = exists().where(
            EHREncounter.provider_id == provider_id,
            EHREncounter.patient_id == patient_id,
            EHREncounter.doctor_id == doctor_id,
        )
        appointment = exists().where(
            Appointment.provider_id == provider_id,
            Appointment.patient_id == patient_id,
            Appointment.doctor_id == doctor_id,
            Appointment.status.in_(CARE_RELATIONSHIP_APPOINTMENT_STATUSES),
        )
        return bool(self.session.scalar(select(encounter | appointment)))

    # ========================================================
    # MEDICAL HISTORY
    # ========================================================
    def list_conditions(
        self,
        *,
        provider_id: UUID,
        patient_id: UUID,
    ) -> list[PatientCondition]:
        statement = (
            select(PatientCondition)
            .where(
                PatientCondition.provider_id == provider_id,
                PatientCondition.patient_id == patient_id,
            )
            .order_by(
                PatientCondition.created_at.desc(),
                PatientCondition.id,
            )
        )

        return list(self.session.scalars(statement))

    def list_allergies(
        self,
        *,
        provider_id: UUID,
        patient_id: UUID,
    ) -> list[PatientAllergy]:
        statement = (
            select(PatientAllergy)
            .where(
                PatientAllergy.provider_id == provider_id,
                PatientAllergy.patient_id == patient_id,
            )
            .order_by(
                PatientAllergy.created_at.desc(),
                PatientAllergy.id,
            )
        )

        return list(self.session.scalars(statement))

    def list_medications(
        self,
        *,
        provider_id: UUID,
        patient_id: UUID,
    ) -> list[PatientMedication]:
        statement = (
            select(PatientMedication)
            .where(
                PatientMedication.provider_id == provider_id,
                PatientMedication.patient_id == patient_id,
            )
            .order_by(
                PatientMedication.created_at.desc(),
                PatientMedication.id,
            )
        )

        return list(self.session.scalars(statement))

    # ========================================================
    # PREVIOUS VISITS
    # ========================================================
    def list_visits(
        self,
        *,
        provider_id: UUID,
        patient_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list, int]:
        filters = (
            EHREncounter.provider_id == provider_id,
            EHREncounter.patient_id == patient_id,
        )

        statement = (
            select(
                EHREncounter,
                Doctor.full_name_en.label("doctor_name_en"),
                Doctor.full_name_ar.label("doctor_name_ar"),
                Branch.name_en.label("branch_name_en"),
                Branch.name_ar.label("branch_name_ar"),
            )
            .outerjoin(Doctor, Doctor.id == EHREncounter.doctor_id)
            .outerjoin(Branch, Branch.id == EHREncounter.branch_id)
            .where(*filters)
            .order_by(EHREncounter.started_at.desc(), EHREncounter.id)
            .limit(limit)
            .offset(offset)
        )

        total = self.session.scalar(
            select(func.count()).select_from(EHREncounter).where(*filters)
        )

        return list(self.session.execute(statement).all()), int(total or 0)

    def get_encounter(
        self,
        *,
        provider_id: UUID,
        patient_id: UUID,
        encounter_id: UUID,
    ) -> EHREncounter | None:
        statement = select(EHREncounter).where(
            EHREncounter.id == encounter_id,
            EHREncounter.provider_id == provider_id,
            EHREncounter.patient_id == patient_id,
        )

        return self.session.scalar(statement)

    # ========================================================
    # DIAGNOSTIC REPORTS
    # ========================================================
    def list_reports(
        self,
        *,
        provider_id: UUID,
        patient_id: UUID,
        report_type: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list, int]:
        selects = []

        if report_type in (None, "lab"):
            selects.append(
                select(
                    LabReport.id.label("report_id"),
                    literal_column("'lab'").label("report_type"),
                    LabReport.document_type.label("category"),
                    LabReport.status.label("status"),
                    LabReport.encounter_id.label("encounter_id"),
                    LabReport.created_at.label("created_at"),
                ).where(
                    LabReport.provider_id == provider_id,
                    LabReport.patient_id == patient_id,
                )
            )

        if report_type in (None, "radiology"):
            selects.append(
                select(
                    RadiologyReport.id.label("report_id"),
                    literal_column("'radiology'").label("report_type"),
                    RadiologyReport.modality.label("category"),
                    RadiologyReport.status.label("status"),
                    RadiologyReport.encounter_id.label("encounter_id"),
                    RadiologyReport.created_at.label("created_at"),
                ).where(
                    RadiologyReport.provider_id == provider_id,
                    RadiologyReport.patient_id == patient_id,
                )
            )

        if not selects:
            return [], 0

        combined = union_all(*selects).subquery()

        total = self.session.scalar(select(func.count()).select_from(combined))

        statement = (
            select(combined)
            .order_by(combined.c.created_at.desc(), combined.c.report_id)
            .limit(limit)
            .offset(offset)
        )

        return list(self.session.execute(statement).all()), int(total or 0)

    def get_lab_report(
        self,
        *,
        provider_id: UUID,
        patient_id: UUID,
        report_id: UUID,
    ) -> tuple[LabReport, list[LabResult]] | None:
        report = self.session.scalar(
            select(LabReport).where(
                LabReport.id == report_id,
                LabReport.provider_id == provider_id,
                LabReport.patient_id == patient_id,
            )
        )

        if report is None:
            return None

        results = list(
            self.session.scalars(
                select(LabResult)
                .where(LabResult.lab_report_id == report.id)
                .order_by(LabResult.result_index)
            )
        )

        return report, results

    def get_radiology_report(
        self,
        *,
        provider_id: UUID,
        patient_id: UUID,
        report_id: UUID,
    ) -> tuple[RadiologyReport, list[DiagnosticAssessment]] | None:
        report = self.session.scalar(
            select(RadiologyReport).where(
                RadiologyReport.id == report_id,
                RadiologyReport.provider_id == provider_id,
                RadiologyReport.patient_id == patient_id,
            )
        )

        if report is None:
            return None

        assessments = list(
            self.session.scalars(
                select(DiagnosticAssessment)
                .where(DiagnosticAssessment.radiology_report_id == report.id)
                .order_by(DiagnosticAssessment.created_at)
            )
        )

        return report, assessments

    # ========================================================
    # CLINICAL NOTES
    # ========================================================
    def list_notes(
        self,
        *,
        provider_id: UUID,
        patient_id: UUID,
        encounter_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list, int]:
        filters = [
            ClinicalNote.provider_id == provider_id,
            ClinicalNote.patient_id == patient_id,
        ]

        if encounter_id is not None:
            filters.append(ClinicalNote.encounter_id == encounter_id)

        statement = (
            select(
                ClinicalNote,
                Doctor.full_name_en.label("doctor_name_en"),
                Doctor.full_name_ar.label("doctor_name_ar"),
            )
            .join(Doctor, Doctor.id == ClinicalNote.doctor_id)
            .where(*filters)
            .order_by(ClinicalNote.created_at.desc(), ClinicalNote.id)
            .limit(limit)
            .offset(offset)
        )

        total = self.session.scalar(
            select(func.count()).select_from(ClinicalNote).where(*filters)
        )

        return list(self.session.execute(statement).all()), int(total or 0)

    def get_note(
        self,
        *,
        provider_id: UUID,
        patient_id: UUID,
        note_id: UUID,
    ):
        statement = (
            select(
                ClinicalNote,
                Doctor.full_name_en.label("doctor_name_en"),
                Doctor.full_name_ar.label("doctor_name_ar"),
            )
            .join(Doctor, Doctor.id == ClinicalNote.doctor_id)
            .where(
                ClinicalNote.id == note_id,
                ClinicalNote.provider_id == provider_id,
                ClinicalNote.patient_id == patient_id,
            )
        )

        return self.session.execute(statement).first()

    def get_note_for_update(
        self,
        *,
        provider_id: UUID,
        patient_id: UUID,
        note_id: UUID,
    ) -> ClinicalNote | None:
        statement = select(ClinicalNote).where(
            ClinicalNote.id == note_id,
            ClinicalNote.provider_id == provider_id,
            ClinicalNote.patient_id == patient_id,
        )

        return self.session.scalar(statement)

    def add_note(self, note: ClinicalNote) -> ClinicalNote:
        self.session.add(note)
        self.session.flush()

        return note
