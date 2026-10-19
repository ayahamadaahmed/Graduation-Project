"""Staff-facing patient medical record APIs.

Every endpoint requires a staff bearer token, the X-Tenant-ID header (which must
match the token's provider) and a permitted role, and every access is written to
the staff audit log.

Role policy (least privilege):
    medical history, visits, clinical notes ... doctor
    diagnostic reports ........................ doctor, lab_staff
    writing / signing clinical notes .......... doctor (the visit's own doctor)
Receptionists and provider admins have no access to clinical data here.
"""

import logging
from collections.abc import Callable
from typing import Annotated, Literal, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import (
    CurrentProvider,
    EHRRecordServiceDependency,
    StaffAuditServiceDependency,
)
from app.schemas.staff_ehr import (
    ClinicalNoteCreateRequest,
    ClinicalNoteListResponse,
    ClinicalNoteOut,
    LabReportDetailResponse,
    MedicalHistoryResponse,
    RadiologyReportDetailResponse,
    ReportListResponse,
    VisitListResponse,
)
from app.security.rbac import require_staff_roles
from app.security.staff_context import StaffContext

logger = logging.getLogger("uvicorn.error")

router = APIRouter(
    prefix="/staff/patients/{patient_id}",
    tags=["staff patient records"],
)

ClinicalReader = Annotated[
    StaffContext,
    Depends(require_staff_roles("doctor")),
]

ReportReader = Annotated[
    StaffContext,
    Depends(require_staff_roles("doctor", "lab_staff")),
]

Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]

T = TypeVar("T")


def _audited(
    *,
    audit: StaffAuditServiceDependency,
    staff: StaffContext,
    action: str,
    resource_type: str,
    patient_id: UUID,
    call: Callable[[], T],
    resource_id: Callable[[T], str | None] | None = None,
    fixed_resource_id: str | None = None,
) -> T:
    """Run ``call`` and record the access in the staff audit log.

    A failure (denied / not found / error) is logged too. If the audit row of a
    SUCCESSFUL access cannot be written, the request fails instead of returning
    clinical data that left no trace.
    """

    def record(outcome: str, rid: str | None) -> None:
        audit.record(
            provider_id=staff.provider_id,
            user_id=staff.user_id,
            membership_id=staff.membership_id,
            patient_id=patient_id,
            action=action,
            resource_type=resource_type,
            resource_id=rid,
            outcome=outcome,
        )

    try:
        result = call()
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            outcome = "not_found"
        elif exc.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ):
            outcome = "denied"
        else:
            outcome = "error"

        try:
            record(outcome, fixed_resource_id)
        except Exception:  # never hide the real error behind an audit failure
            logger.exception("staff audit write failed (action=%s)", action)

        raise
    except Exception:
        try:
            record("error", fixed_resource_id)
        except Exception:
            logger.exception("staff audit write failed (action=%s)", action)

        raise

    record(
        "success",
        resource_id(result) if resource_id is not None else fixed_resource_id,
    )

    return result


# ============================================================
# MEDICAL HISTORY
# ============================================================
@router.get("/medical-history", response_model=MedicalHistoryResponse)
def get_medical_history(
    patient_id: UUID,
    provider: CurrentProvider,
    staff: ClinicalReader,
    service: EHRRecordServiceDependency,
    audit: StaffAuditServiceDependency,
) -> MedicalHistoryResponse:
    return _audited(
        audit=audit,
        staff=staff,
        action="ehr.medical_history.read",
        resource_type="patient",
        patient_id=patient_id,
        call=lambda: service.get_medical_history(staff=staff, patient_id=patient_id),
    )


# ============================================================
# PREVIOUS VISITS
# ============================================================
@router.get("/visits", response_model=VisitListResponse)
def list_visits(
    patient_id: UUID,
    provider: CurrentProvider,
    staff: ClinicalReader,
    service: EHRRecordServiceDependency,
    audit: StaffAuditServiceDependency,
    limit: Limit = 50,
    offset: Offset = 0,
) -> VisitListResponse:
    return _audited(
        audit=audit,
        staff=staff,
        action="ehr.visits.list",
        resource_type="encounter",
        patient_id=patient_id,
        call=lambda: service.list_visits(
            staff=staff,
            patient_id=patient_id,
            limit=limit,
            offset=offset,
        ),
    )


# ============================================================
# DIAGNOSTIC REPORTS
# ============================================================
@router.get("/reports", response_model=ReportListResponse)
def list_reports(
    patient_id: UUID,
    provider: CurrentProvider,
    staff: ReportReader,
    service: EHRRecordServiceDependency,
    audit: StaffAuditServiceDependency,
    report_type: Literal["lab", "radiology"] | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> ReportListResponse:
    return _audited(
        audit=audit,
        staff=staff,
        action="ehr.reports.list",
        resource_type="report",
        patient_id=patient_id,
        call=lambda: service.list_reports(
            staff=staff,
            patient_id=patient_id,
            report_type=report_type,
            limit=limit,
            offset=offset,
        ),
    )


@router.get("/reports/lab/{report_id}", response_model=LabReportDetailResponse)
def get_lab_report(
    patient_id: UUID,
    report_id: UUID,
    provider: CurrentProvider,
    staff: ReportReader,
    service: EHRRecordServiceDependency,
    audit: StaffAuditServiceDependency,
) -> LabReportDetailResponse:
    return _audited(
        audit=audit,
        staff=staff,
        action="ehr.report.read",
        resource_type="lab_report",
        patient_id=patient_id,
        fixed_resource_id=str(report_id),
        call=lambda: service.get_lab_report(
            staff=staff,
            patient_id=patient_id,
            report_id=report_id,
        ),
    )


@router.get(
    "/reports/radiology/{report_id}",
    response_model=RadiologyReportDetailResponse,
)
def get_radiology_report(
    patient_id: UUID,
    report_id: UUID,
    provider: CurrentProvider,
    staff: ReportReader,
    service: EHRRecordServiceDependency,
    audit: StaffAuditServiceDependency,
) -> RadiologyReportDetailResponse:
    return _audited(
        audit=audit,
        staff=staff,
        action="ehr.report.read",
        resource_type="radiology_report",
        patient_id=patient_id,
        fixed_resource_id=str(report_id),
        call=lambda: service.get_radiology_report(
            staff=staff,
            patient_id=patient_id,
            report_id=report_id,
        ),
    )


# ============================================================
# CLINICAL NOTES
# ============================================================
@router.get("/clinical-notes", response_model=ClinicalNoteListResponse)
def list_clinical_notes(
    patient_id: UUID,
    provider: CurrentProvider,
    staff: ClinicalReader,
    service: EHRRecordServiceDependency,
    audit: StaffAuditServiceDependency,
    encounter_id: UUID | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> ClinicalNoteListResponse:
    return _audited(
        audit=audit,
        staff=staff,
        action="ehr.notes.list",
        resource_type="clinical_note",
        patient_id=patient_id,
        call=lambda: service.list_notes(
            staff=staff,
            patient_id=patient_id,
            encounter_id=encounter_id,
            limit=limit,
            offset=offset,
        ),
    )


@router.get("/clinical-notes/{note_id}", response_model=ClinicalNoteOut)
def get_clinical_note(
    patient_id: UUID,
    note_id: UUID,
    provider: CurrentProvider,
    staff: ClinicalReader,
    service: EHRRecordServiceDependency,
    audit: StaffAuditServiceDependency,
) -> ClinicalNoteOut:
    return _audited(
        audit=audit,
        staff=staff,
        action="ehr.note.read",
        resource_type="clinical_note",
        patient_id=patient_id,
        fixed_resource_id=str(note_id),
        call=lambda: service.get_note(
            staff=staff,
            patient_id=patient_id,
            note_id=note_id,
        ),
    )


@router.post(
    "/clinical-notes",
    response_model=ClinicalNoteOut,
    status_code=status.HTTP_201_CREATED,
)
def create_clinical_note(
    patient_id: UUID,
    data: ClinicalNoteCreateRequest,
    provider: CurrentProvider,
    staff: ClinicalReader,
    service: EHRRecordServiceDependency,
    audit: StaffAuditServiceDependency,
) -> ClinicalNoteOut:
    return _audited(
        audit=audit,
        staff=staff,
        action="ehr.note.create",
        resource_type="clinical_note",
        patient_id=patient_id,
        resource_id=lambda note: str(note.note_id),
        call=lambda: service.create_note(
            staff=staff,
            patient_id=patient_id,
            data=data,
        ),
    )


@router.post(
    "/clinical-notes/{note_id}/sign",
    response_model=ClinicalNoteOut,
)
def sign_clinical_note(
    patient_id: UUID,
    note_id: UUID,
    provider: CurrentProvider,
    staff: ClinicalReader,
    service: EHRRecordServiceDependency,
    audit: StaffAuditServiceDependency,
) -> ClinicalNoteOut:
    return _audited(
        audit=audit,
        staff=staff,
        action="ehr.note.sign",
        resource_type="clinical_note",
        patient_id=patient_id,
        fixed_resource_id=str(note_id),
        call=lambda: service.sign_note(
            staff=staff,
            patient_id=patient_id,
            note_id=note_id,
        ),
    )
