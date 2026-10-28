from __future__ import annotations
import asyncio
import logging
import re
import time
import asyncio
from medmind.diagnostic_attachment import (
    TrustedDiagnosticAttachment,
)

from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    Request,
    status,
)

from app.api.dependencies import (
    CurrentProvider,
    DiagnosticAttachmentServiceDependency,
    PathologyPersistenceAdapterDependency,
    RadiologyPersistenceAdapterDependency,
)

from app.services.diagnostic_attachment_service import (
    DiagnosticAttachmentNotFoundError,
    InvalidDiagnosticAttachmentError,
)

from medmind.tenancy.factory import (
    build_tenant_context,
)
from app.schemas.ai_chat import (
    AIChatRequest,
    AIChatResponse,
)

from app.services.medmind_registry import (
    MedMindServiceRegistry,
)
from app.schemas.radiology_persistence import (
    RadiologyPersistenceRequest,
)

from app.services.radiology_persistence_adapter import (
    DuplicateRadiologyPersistenceError,
)

from app.services.radiology_persistence_service import (
    RadiologyPersistenceError,
)

from app.schemas.pathology_persistence import (
    PathologyPersistenceRequest,
)

from app.services.pathology_persistence_adapter import (
    DuplicatePathologyPersistenceError,
)

from app.services.lab_persistence_service import (
    LabPersistenceError,
)

logger = logging.getLogger(
    __name__
)


router = APIRouter(
    prefix="/ai",
    tags=[
        "ai"
    ],
)


TENANT_PATTERN = re.compile(
    r"^[A-Za-z0-9]"
    r"[A-Za-z0-9._-]{0,63}$"
)


def _validate_tenant_id(
    tenant_id: str,
) -> str:

    value = (
        tenant_id.strip()
    )

    if not TENANT_PATTERN.fullmatch(
        value
    ):

        raise HTTPException(
            status_code=400,
            detail={
                "code":
                    "INVALID_TENANT_ID",

                "message":
                    (
                        "X-Tenant-ID has "
                        "an invalid format."
                    ),
            },
        )

    return value


def _get_registry(
    request: Request,
) -> MedMindServiceRegistry:

    registry = getattr(
        request.app.state,
        "medmind_registry",
        None,
    )

    if registry is None:

        registry = (
            MedMindServiceRegistry()
        )

        request.app.state.medmind_registry = (
            registry
        )

    return registry


@router.get(
    "/debug/router",
    include_in_schema=False,
)
async def debug_semantic_router(
    request: Request,
    message: str = "عايز أحجز كشف جلدية",
):

    semantic_router = getattr(
        request.app.state,
        "medmind_semantic_router",
        None,
    )

    if semantic_router is None:

        raise HTTPException(
            status_code=503,
            detail=(
                "Semantic router "
                "is not available."
            ),
        )

    started = (
        time.perf_counter()
    )

    matches = (
        semantic_router.route(
            message,
            top_k=8,
        )
    )

    total_ms = (
        (
            time.perf_counter()
            - started
        )
        * 1000
    )

    logger.info(
        "semantic_router_http_debug "
        "message_length=%s "
        "result_count=%s "
        "total_ms=%.2f",
        len(message),
        len(matches),
        total_ms,
    )

    return {
        "message": message,

        "total_ms": round(
            total_ms,
            2,
        ),

        "results": [
            {
                "capability":
                    match.name,

                "score":
                    round(
                        float(
                            match.score
                        ),
                        4,
                    ),
            }
            for match in matches
        ],
    }

# ========================================================
# MEDMIND WARM-UP
# ========================================================

@router.post(
    "/warmup",
    include_in_schema=False,
)
async def warmup(
    request: Request,
    provider: CurrentProvider,
    x_tenant_id: str = Header(
        ...,
        alias="X-Tenant-ID",
    ),
):
    started = time.perf_counter()

    tenant_id = _validate_tenant_id(
        x_tenant_id
    )

    # Same tenant/provider security check
    # used by the real chat endpoint.
    if provider.tenant_key != tenant_id:

        logger.error(
            "warmup_provider_tenant_mismatch "
            "requested_tenant=%s "
            "resolved_tenant=%s",
            tenant_id,
            provider.tenant_key,
        )

        raise HTTPException(
            status_code=500,
            detail={
                "code":
                    "TENANT_CONTEXT_MISMATCH",

                "message":
                    (
                        "Tenant context could not "
                        "be resolved safely."
                    ),
            },
        )

    try:

        tenant_context = build_tenant_context(
            provider
        )

    except ValueError:

        logger.warning(
            "warmup_unsupported_provider_type "
            "tenant_id=%s "
            "org_type=%s",
            tenant_id,
            provider.org_type,
        )

        raise HTTPException(
            status_code=403,
            detail={
                "code":
                    "PROVIDER_TYPE_UNSUPPORTED",

                "message":
                    (
                        "This provider type is not "
                        "enabled for MedMind."
                    ),
            },
        )

    registry = _get_registry(
        request
    )

    qwen_planner = getattr(
        request.app.state,
        "medmind_qwen_planner",
        None,
    )

    try:

        tenant_warmup = registry.get(
            tenant_id=tenant_id,
            tenant_context=tenant_context,
        )

        if qwen_planner is not None:

            _, qwen_ready = await asyncio.gather(
                tenant_warmup,
                qwen_planner.warmup(),
            )

        else:

            await tenant_warmup
            qwen_ready = False

    except Exception:

        logger.exception(
            "medmind_warmup_failed "
            "tenant_id=%s",
            tenant_id,
        )

        raise HTTPException(
            status_code=503,
            detail={
                "code":
                    "MEDMIND_WARMUP_FAILED",

                "message":
                    (
                        "MedMind warm-up "
                        "could not be completed."
                    ),
            },
        )

    except Exception:

        logger.exception(
            "medmind_warmup_failed "
            "tenant_id=%s",
            tenant_id,
        )

        raise HTTPException(
            status_code=503,
            detail={
                "code":
                    "MEDMIND_WARMUP_FAILED",

                "message":
                    (
                        "MedMind warm-up "
                        "could not be completed."
                    ),
            },
        )

    elapsed_ms = (
        time.perf_counter()
        - started
    ) * 1000

    logger.info(
        "medmind_warmup_timing "
        "tenant_id=%s "
        "qwen_ready=%s "
        "total_ms=%.2f "
        "status=success",
        tenant_id,
        qwen_ready,
        elapsed_ms,
    )

    return {
        "status": "ready",
        "tenant_id": tenant_id,
        "qwen_ready": qwen_ready,
        "elapsed_ms": round(
            elapsed_ms,
            2,
        ),
    }

# ========================================================
# MEDMIND CHAT
# ========================================================

@router.post(
    "/chat",
    response_model=AIChatResponse,
    status_code=status.HTTP_200_OK,
)
@router.post(
    "/chat-v2",
    response_model=AIChatResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)

async def chat(
    payload: AIChatRequest,
    request: Request,
    provider: CurrentProvider,

    attachment_service:
        DiagnosticAttachmentServiceDependency,

    radiology_persistence_adapter:
        RadiologyPersistenceAdapterDependency,

    pathology_persistence_adapter:
        PathologyPersistenceAdapterDependency,    

    x_tenant_id: str = Header(
        ...,
        alias="X-Tenant-ID",
    ),
) -> AIChatResponse:

    tenant_id = (
        _validate_tenant_id(
            x_tenant_id
        )
    )

    if (
        provider.tenant_key
        != tenant_id
    ):
        logger.error(
            "provider_tenant_mismatch "
            "requested_tenant=%s "
            "resolved_tenant=%s",
            tenant_id,
            provider.tenant_key,
        )

        raise HTTPException(
            status_code=500,
            detail={
                "code":
                    "TENANT_CONTEXT_MISMATCH",

                "message":
                    (
                        "Tenant context could not "
                        "be resolved safely."
                    ),
            },
        )


    try:
        tenant_context = (
            build_tenant_context(
                provider
            )
        )

    except ValueError:

        logger.warning(
            "unsupported_provider_type "
            "tenant_id=%s "
            "org_type=%s",
            tenant_id,
            provider.org_type,
        )

        raise HTTPException(
            status_code=403,
            detail={
                "code":
                    "PROVIDER_TYPE_UNSUPPORTED",

                "message":
                    (
                        "This provider type is not "
                        "enabled for MedMind."
                    ),
            },
        )

    registry = (
        _get_registry(
            request
        )
    )

    trusted_attachment_ids: list[str] = []

    trusted_attachments: list[
        TrustedDiagnosticAttachment
    ] = []

    for attachment_id in payload.attachment_ids:

        try:

            attachment = attachment_service.get(
                provider_id=provider.id,
                attachment_id=attachment_id,
            )

        except InvalidDiagnosticAttachmentError as exc:

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code":
                        "INVALID_DIAGNOSTIC_ATTACHMENT",

                    "message":
                        "Invalid diagnostic attachment.",
                },
            ) from exc

        except DiagnosticAttachmentNotFoundError as exc:

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code":
                        "DIAGNOSTIC_ATTACHMENT_NOT_FOUND",

                    "message":
                        "Diagnostic attachment was not found.",
                },
            ) from exc

        # The attachment must belong to the same chat session.
        # Return 404 rather than exposing that another session
        # owns the attachment.
        if (
            attachment.session_id
            != payload.session_id
        ):

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code":
                        "DIAGNOSTIC_ATTACHMENT_NOT_FOUND",

                    "message":
                        "Diagnostic attachment was not found.",
                },
            )

        try:

            attachment_path = (
                attachment_service.resolve_path(
                    provider_id=provider.id,
                    attachment_id=(
                        attachment.attachment_id
                    ),
                )
            )

            attachment_bytes = await (
                asyncio.to_thread(
                    attachment_path.read_bytes
                )
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
                            "Diagnostic attachment "
                            "was not found."
                        ),
                },
            ) from exc

        trusted_attachments.append(
            TrustedDiagnosticAttachment(
                attachment_id=(
                    attachment.attachment_id
                ),

                provider_id=(
                    attachment.provider_id
                ),

                session_id=(
                    attachment.session_id
                ),

                original_filename=(
                    attachment.original_filename
                ),

                content_type=(
                    attachment.content_type
                ),

                data=attachment_bytes,

                patient_id=(
                    attachment.patient_id
                ),

                encounter_id=(
                    attachment.encounter_id
                ),
            )
        )

        trusted_attachment_ids.append(
            attachment.attachment_id
        )

    try:

        service = await registry.get(
            tenant_id=
                tenant_id,

            tenant_context=
                tenant_context,
        )

        result = await service.chat(
            session_id=
                payload.session_id,

            message=
                payload.message,

            channel=
                payload.channel,

            diagnostic_mode=
                payload.diagnostic_mode,

            attachment_ids=
                trusted_attachment_ids,

            trusted_attachments=
                trusted_attachments,
        )

    except Exception:

        logger.exception(
            "MedMind chat request failed."
        )

        raise HTTPException(
            status_code=503,
            detail={
                "code":
                    "AI_AGENT_UNAVAILABLE",

                "message":
                    (
                        "The booking assistant "
                        "could not process the "
                        "request right now."
                    ),
            },
        )

    if not isinstance(
        result,
        dict,
    ):

        raise HTTPException(
            status_code=503,
            detail={
                "code":
                    "INVALID_AGENT_RESPONSE",

                "message":
                    (
                        "The booking assistant "
                        "returned an invalid "
                        "response."
                    ),
            },
        )

    # ========================================================
    # RADIOLOGY RESULT PERSISTENCE
    # ========================================================

    diagnostic_result = (
        result.get(
            "diagnostic_result"
        )
    )

    if (
        isinstance(
            diagnostic_result,
            dict,
        )
        and
        diagnostic_result.get(
            "kind"
        )
        == "radiology"
    ):

        try:

            persistence_request = (
                RadiologyPersistenceRequest(
                    schema_version=(
                        diagnostic_result[
                            "schema_version"
                        ]
                    ),

                    attachment_id=(
                        diagnostic_result[
                            "attachment_id"
                        ]
                    ),

                    modality=(
                        diagnostic_result[
                            "modality"
                        ]
                    ),

                    classification=(
                        diagnostic_result[
                            "classification"
                        ]
                    ),

                    probabilities=(
                        diagnostic_result[
                            "probabilities"
                        ]
                    ),

                    confidence=(
                        diagnostic_result[
                            "confidence"
                        ]
                    ),

                    inference_latency_ms=(
                        diagnostic_result[
                            "inference_latency_ms"
                        ]
                    ),

                    model_name=(
                        diagnostic_result[
                            "model_name"
                        ]
                    ),

                    model_version=(
                        diagnostic_result[
                            "model_version"
                        ]
                    ),

                    limitations=(
                        diagnostic_result[
                            "limitations"
                        ]
                    ),
                )
            )

            radiology_report = (
                radiology_persistence_adapter
                .persist(
                    provider_id=(
                        provider.id
                    ),

                    request=(
                        persistence_request
                    ),
                )
            )

            logger.info(
                "medmind_radiology_persisted "
                "tenant_id=%s "
                "attachment_id=%s "
                "radiology_report_id=%s",
                tenant_id,
                persistence_request.attachment_id,
                radiology_report.id,
            )

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

        except (
            RadiologyPersistenceError,
            ValueError,
            KeyError,
            TypeError,
        ) as exc:

            logger.exception(
                "medmind_radiology_persistence_failed "
                "tenant_id=%s",
                tenant_id,
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

    # ========================================================
    # PATHOLOGY PERSISTENCE
    # ========================================================

    if (
        isinstance(
            diagnostic_result,
            dict,
        )
        and
        diagnostic_result.get(
            "kind"
        )
        == "pathology"
    ):

        try:

            persistence_request = (
                PathologyPersistenceRequest(
                    schema_version=(
                        diagnostic_result[
                            "schema_version"
                        ]
                    ),

                    attachment_id=(
                        diagnostic_result[
                            "attachment_id"
                        ]
                    ),

                    document_type=(
                        (
                            str(
                                diagnostic_result.get(
                                    "document_type"
                                )
                                or ""
                            ).strip()[:50]
                            or None
                        )
                    ),

                    unreadable_fields=(
                        diagnostic_result.get(
                            "unreadable_fields"
                        )
                        or []
                    ),

                    results=(
                        diagnostic_result[
                            "results"
                        ]
                    ),
                )
            )

            lab_report = (
                pathology_persistence_adapter
                .persist(
                    provider_id=(
                        provider.id
                    ),
                    request=(
                        persistence_request
                    ),
                )
            )

            logger.info(
                "medmind_pathology_persisted "
                "tenant_id=%s "
                "attachment_id=%s "
                "lab_report_id=%s "
                "result_count=%s",
                tenant_id,
                persistence_request
                .attachment_id,
                lab_report.id,
                len(
                    persistence_request
                    .results
                ),
            )

        except (
            DuplicatePathologyPersistenceError
        ) as exc:

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

        except (
            LabPersistenceError,
            ValueError,
            KeyError,
            TypeError,
        ) as exc:

            logger.exception(
                "medmind_pathology_persistence_failed "
                "tenant_id=%s",
                tenant_id,
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
        
    state = (
        result.get(
            "state"
        )
        or {}
    )

    reply = str(
        result.get(
            "reply"
        )
        or ""
    ).strip()

    language = (
        result.get(
            "language"
        )
        or
        state.get(
            "language"
        )
    )

    if not reply:

        if language == "en":

            reply = (
                "I couldn't process "
                "that request."
            )

        else:

            reply = (
                "مقدرتش أنفذ الطلب ده دلوقتي."
            )

    return AIChatResponse(
        session_id=
            payload.session_id,

        reply=
            reply,

        stage=str(
            state.get(
                "stage"
            )
            or
            "unknown"
        ),

        intent=(
            result.get(
                "intent"
            )
        ),

        language=
            language,

        awaiting_confirmation=bool(
            state.get(
                "awaiting_confirmation",
                False,
            )
        ),

        appointment_reference=(
            state.get(
                "appointment_reference"
            )
        ),

        operation_type=(
            state.get(
                "operation_type"
            )
        ),

        operation_status=None,

        response_type=(
            result.get(
                "response_type"
            )
        ),

        route=(
            result.get(
                "route"
            )
        ),

        error_code=None,

        nlu_source=None,
        nlu_provider=None,

        operation_id=None,

        nlg_source=None,
        nlg_guard_passed=None,
        nlg_violations=[],
        nlg_fallback_reason=None,
    )
