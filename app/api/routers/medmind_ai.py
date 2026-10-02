from __future__ import annotations
import asyncio
import logging
import re
import time

from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    Request,
    status,
)
from app.api.dependencies import (
    CurrentProvider,
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