from __future__ import annotations

import logging
from uuid import UUID
from typing import Annotated

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
    DiagnosticAttachmentServiceDependency,
    
)

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
                        "The diagnostic image exceeds "
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
                        "The diagnostic image exceeds "
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
                        "Only JPEG and PNG diagnostic "
                        "images are currently supported."
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
