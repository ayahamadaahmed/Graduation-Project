from __future__ import annotations

import logging
import json
from uuid import UUID
from typing import Annotated

from sqlalchemy import select

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)

from app.api.dependencies import (
    CurrentProvider,
    DatabaseSession,
    DiagnosticAttachmentServiceDependency,
    
)
from app.models.diagnostic_case import DiagnosticCase
from app.schemas.diagnostic_case import DiagnosticCaseResponse, DiagnosticCaseSaveRequest

from app.schemas.diagnostic_attachment import (
    DiagnosticAttachmentUploadResponse,
)

from app.services.diagnostic_attachment_service import (
    DiagnosticAttachmentError,
    DiagnosticFileTooLargeError,
    InvalidDiagnosticAttachmentError,
    UnsupportedDiagnosticFileTypeError,
)
from app.api.dependencies import (
    CurrentProvider,
    DiagnosticAttachmentServiceDependency,
    PathologyPersistenceAdapterDependency,
    RadiologyPersistenceAdapterDependency,
    DiagnosticAttachmentBindingServiceDependency,
)
from app.schemas.radiology_persistence import (
    RadiologyPersistenceRequest,
    RadiologyPersistenceResponse,
)
from app.services.diagnostic_attachment_binding_service import (
    DiagnosticEncounterNotFoundError,
    DiagnosticEncounterRequiresPatientError,
    DiagnosticPatientNotFoundError,
    DiagnosticPatientProviderMismatchError,
)
from app.services.radiology_persistence_service import (
    RadiologyPersistenceError,
)

from app.services.radiology_persistence_adapter import (
    DuplicateRadiologyPersistenceError,
)
from app.schemas.pathology_persistence import (
    PathologyPersistenceRequest,
    PathologyPersistenceResponse,
)
from app.services.diagnostic_attachment_service import (
    DiagnosticAttachmentError,
    DiagnosticAttachmentNotFoundError,
    DiagnosticFileTooLargeError,
    InvalidDiagnosticAttachmentError,
    UnsupportedDiagnosticFileTypeError,
)

from app.services.lab_persistence_service import (
    LabPersistenceError,
)

from app.services.pathology_persistence_adapter import (
    DuplicatePathologyPersistenceError,
)

logger = logging.getLogger(
    "medmind.diagnostics"
)


router = APIRouter(
    prefix="/diagnostics",
    tags=["diagnostics"],
)


@router.put("/cases/{session_id}", response_model=DiagnosticCaseResponse)
def save_diagnostic_case(
    session_id: str,
    payload: DiagnosticCaseSaveRequest,
    provider: CurrentProvider,
    session: DatabaseSession,
    binding_service: DiagnosticAttachmentBindingServiceDependency,
) -> DiagnosticCaseResponse:
    """Create/update a case under the authenticated tenant/provider."""
    session_id = session_id.strip()
    if not session_id or len(session_id) > 128:
        raise HTTPException(status_code=400, detail="Invalid session_id.")
    try:
        binding = binding_service.resolve(
            provider_id=provider.id,
            patient_id=payload.patient_id,
            encounter_id=payload.encounter_id,
        )
    except (
        DiagnosticEncounterNotFoundError,
        DiagnosticEncounterRequiresPatientError,
        DiagnosticPatientNotFoundError,
        DiagnosticPatientProviderMismatchError,
    ) as exc:
        raise HTTPException(status_code=404, detail="Patient or encounter was not found for this provider.") from exc

    case = session.scalar(select(DiagnosticCase).where(
        DiagnosticCase.provider_id == provider.id,
        DiagnosticCase.session_id == session_id,
    ))
    if case is None:
        case = DiagnosticCase(provider_id=provider.id, session_id=session_id)
        session.add(case)
    elif case.patient_id and binding.patient_id and case.patient_id != binding.patient_id:
        raise HTTPException(status_code=409, detail="This chat session is already linked to another patient.")

    if binding.patient_id is not None:
        case.patient_id = binding.patient_id
    if binding.encounter_id is not None:
        case.encounter_id = binding.encounter_id
    case.complaint = payload.complaint.strip()
    case.answers_json = json.dumps(payload.answers, ensure_ascii=False)
    case.summary_json = json.dumps(payload.summary.model_dump(mode="json"), ensure_ascii=False) if payload.summary is not None else None
    case.status = "complete" if payload.summary is not None else "in_progress"
    session.commit()
    session.refresh(case)
    return DiagnosticCaseResponse(
        id=case.id, session_id=case.session_id, patient_id=case.patient_id,
        encounter_id=case.encounter_id, complaint=case.complaint,
        answers=json.loads(case.answers_json or "{}"),
        summary=json.loads(case.summary_json) if case.summary_json else None,
        status=case.status, created_at=case.created_at, updated_at=case.updated_at,
    )


@router.get("/cases", response_model=list[DiagnosticCaseResponse])
def list_diagnostic_cases(
    patient_id: UUID,
    provider: CurrentProvider,
    session: DatabaseSession,
) -> list[DiagnosticCaseResponse]:
    """List cases visible to this provider for a validated patient."""
    statement = select(DiagnosticCase).where(
        DiagnosticCase.provider_id == provider.id,
        DiagnosticCase.patient_id == patient_id,
    ).order_by(DiagnosticCase.created_at.desc()).limit(100)
    return [DiagnosticCaseResponse(
        id=case.id, session_id=case.session_id, patient_id=case.patient_id,
        encounter_id=case.encounter_id, complaint=case.complaint,
        answers=json.loads(case.answers_json or "{}"),
        summary=json.loads(case.summary_json) if case.summary_json else None,
        status=case.status, created_at=case.created_at, updated_at=case.updated_at,
    ) for case in session.scalars(statement).all()]


@router.post(
    "/attachments",
    response_model=(
        DiagnosticAttachmentUploadResponse
    ),
    status_code=status.HTTP_201_CREATED,
)

async def upload_diagnostic_attachment(
    session_id: Annotated[
        str,
        Form(
            min_length=1,
            max_length=128,
        ),
    ],

    file: Annotated[
        UploadFile,
        File(),
    ],

    provider: CurrentProvider,

    service:
        DiagnosticAttachmentServiceDependency,

    binding_service:
        DiagnosticAttachmentBindingServiceDependency,

    patient_id: Annotated[
        UUID | None,
        Form(),
    ] = None,

    encounter_id: Annotated[
        UUID | None,
        Form(),
    ] = None,

) -> DiagnosticAttachmentUploadResponse:

    # ========================================================
    # Resolve trusted patient / encounter binding
    # ========================================================

    try:

        binding = binding_service.resolve(
            provider_id=provider.id,
            patient_id=patient_id,
            encounter_id=encounter_id,
        )

    except (
        DiagnosticEncounterRequiresPatientError
    ) as exc:

        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail={
                "code":
                    "DIAGNOSTIC_PATIENT_REQUIRED",

                "message":
                    (
                        "A patient is required when "
                        "an encounter is provided."
                    ),
            },
        ) from exc

    except (
        DiagnosticPatientNotFoundError,
        DiagnosticPatientProviderMismatchError,
    ) as exc:

        # Do not reveal whether the patient exists
        # under another provider.
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail={
                "code":
                    "DIAGNOSTIC_PATIENT_NOT_FOUND",

                "message":
                    (
                        "The patient was not found "
                        "for this provider."
                    ),
            },
        ) from exc

    except (
        DiagnosticEncounterNotFoundError
    ) as exc:

        # Same rule: do not expose encounters
        # from another patient/provider.
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail={
                "code":
                    "DIAGNOSTIC_ENCOUNTER_NOT_FOUND",

                "message":
                    (
                        "The encounter was not found "
                        "for this patient and provider."
                    ),
            },
        ) from exc


    try:

        data = await file.read(
            service.max_upload_bytes
            + 1
        )

    finally:

        await file.close()

    # ========================================================
    # Early size rejection
    # ========================================================

    if (
        len(data)
        >
        service.max_upload_bytes
    ):

        raise HTTPException(
            status_code=(
                status.HTTP_413_CONTENT_TOO_LARGE
            ),
            detail={
                "code":
                    "DIAGNOSTIC_FILE_TOO_LARGE",

                "message":
                    (
                        "The diagnostic attachment exceeds "
                        "the allowed upload size."
                    ),
            },
        )

    # ========================================================
    # Store
    # ========================================================

    try:

        attachment = service.store(
            provider_id=provider.id,
            session_id=session_id,
            original_filename=(
                file.filename
                or ""
            ),
            content_type=(
                file.content_type
                or ""
            ),
            data=data,
            patient_id=(
                binding.patient_id
            ),
            encounter_id=(
                binding.encounter_id
            ),
        )

    except DiagnosticFileTooLargeError as exc:

        raise HTTPException(
            status_code=(
                status.HTTP_413_CONTENT_TOO_LARGE
            ),
            detail={
                "code":
                    "DIAGNOSTIC_FILE_TOO_LARGE",

                "message":
                    (
                        "The diagnostic attachment exceeds "
                        "the allowed upload size."
                    ),
            },
        ) from exc

    except UnsupportedDiagnosticFileTypeError as exc:

        raise HTTPException(
            status_code=(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
            ),
            detail={
                "code":
                    "UNSUPPORTED_DIAGNOSTIC_FILE_TYPE",

                "message":
                    (
                        "Only JPG, PNG, and PDF diagnostic "
                        "attachments are supported."
                    ),
            },
        ) from exc

    except InvalidDiagnosticAttachmentError as exc:

        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail={
                "code":
                    "INVALID_DIAGNOSTIC_ATTACHMENT",

                "message":
                    (
                        "The diagnostic attachment "
                        "is invalid."
                    ),
            },
        ) from exc

    except DiagnosticAttachmentError as exc:

        logger.exception(
            "diagnostic_attachment_store_failed "
            "tenant_id=%s",
            provider.tenant_key,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail={
                "code":
                    "DIAGNOSTIC_STORAGE_UNAVAILABLE",

                "message":
                    (
                        "The diagnostic attachment "
                        "could not be stored right now."
                    ),
            },
        ) from exc

    logger.info(
        "diagnostic_attachment_stored "
        "tenant_id=%s "
        "attachment_id=%s "
        "content_type=%s "
        "size_bytes=%s",
        provider.tenant_key,
        attachment.attachment_id,
        attachment.content_type,
        attachment.size_bytes,
    )

    return (
        DiagnosticAttachmentUploadResponse(
            attachment_id=(
                attachment
                .attachment_id
            ),
            content_type=(
                attachment
                .content_type
            ),
            size_bytes=(
                attachment
                .size_bytes
            ),
        )
    )

@router.post(
    "/pathology-results",
    response_model=(
        PathologyPersistenceResponse
    ),
    status_code=status.HTTP_201_CREATED,
)
def persist_pathology_results(
    request: PathologyPersistenceRequest,

    provider: CurrentProvider,

    adapter:
        PathologyPersistenceAdapterDependency,
) -> PathologyPersistenceResponse:

    try:

        report = adapter.persist(
            provider_id=(
                provider.id
            ),
            request=request,
        )

    except DiagnosticAttachmentNotFoundError as exc:

        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail={
                "code":
                    "DIAGNOSTIC_ATTACHMENT_NOT_FOUND",

                "message":
                    (
                        "The diagnostic attachment "
                        "was not found."
                    ),
            },
        ) from exc

    except InvalidDiagnosticAttachmentError as exc:

        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail={
                "code":
                    "INVALID_DIAGNOSTIC_ATTACHMENT",

                "message":
                    (
                        "The diagnostic attachment "
                        "identifier is invalid."
                    ),
            },
        ) from exc

    except DuplicatePathologyPersistenceError as exc:

        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
            ),
            detail={
                "code":
                    "PATHOLOGY_REPORT_ALREADY_EXISTS",

                "message":
                    (
                        "A pathology report already "
                        "exists for this attachment."
                    ),
            },
        ) from exc

    except LabPersistenceError as exc:

        logger.exception(
            "pathology_persistence_failed "
            "tenant_id=%s "
            "attachment_id=%s",
            provider.tenant_key,
            request.attachment_id,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail={
                "code":
                    "PATHOLOGY_PERSISTENCE_FAILED",

                "message":
                    (
                        "The pathology result could "
                        "not be stored right now."
                    ),
            },
        ) from exc

    logger.info(
        "pathology_result_stored "
        "tenant_id=%s "
        "attachment_id=%s "
        "lab_report_id=%s "
        "result_count=%s",
        provider.tenant_key,
        request.attachment_id,
        report.id,
        len(
            request.results
        ),
    )

    return PathologyPersistenceResponse(
        attachment_id=(
            request.attachment_id
        ),
        lab_report_id=str(
            report.id
        ),
        status="processed",
        result_count=len(
            request.results
        ),
    )    

@router.post(
    "/radiology-results",
    response_model=(
        RadiologyPersistenceResponse
    ),
    status_code=status.HTTP_201_CREATED,
)
def persist_radiology_results(
    request: RadiologyPersistenceRequest,

    provider: CurrentProvider,

    adapter:
        RadiologyPersistenceAdapterDependency,
) -> RadiologyPersistenceResponse:

    try:

        report = adapter.persist(
            provider_id=(
                provider.id
            ),
            request=request,
        )

    except DiagnosticAttachmentNotFoundError as exc:

        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail={
                "code":
                    "DIAGNOSTIC_ATTACHMENT_NOT_FOUND",

                "message":
                    (
                        "The diagnostic attachment "
                        "was not found."
                    ),
            },
        ) from exc

    except InvalidDiagnosticAttachmentError as exc:

        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail={
                "code":
                    "INVALID_DIAGNOSTIC_ATTACHMENT",

                "message":
                    (
                        "The diagnostic attachment "
                        "identifier is invalid."
                    ),
            },
        ) from exc

    except DuplicateRadiologyPersistenceError as exc:

        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
            ),
            detail={
                "code":
                    "RADIOLOGY_REPORT_ALREADY_EXISTS",

                "message":
                    (
                        "A radiology report already "
                        "exists for this attachment."
                    ),
            },
        ) from exc

    except RadiologyPersistenceError as exc:

        logger.exception(
            "radiology_persistence_failed "
            "tenant_id=%s "
            "attachment_id=%s",
            provider.tenant_key,
            request.attachment_id,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail={
                "code":
                    "RADIOLOGY_PERSISTENCE_FAILED",

                "message":
                    (
                        "The radiology result could "
                        "not be stored right now."
                    ),
            },
        ) from exc

    logger.info(
        "radiology_result_stored "
        "tenant_id=%s "
        "attachment_id=%s "
        "radiology_report_id=%s",
        provider.tenant_key,
        request.attachment_id,
        report.id,
    )

    return RadiologyPersistenceResponse(
        attachment_id=(
            request.attachment_id
        ),
        radiology_report_id=str(
            report.id
        ),
        status="processed",
    )
