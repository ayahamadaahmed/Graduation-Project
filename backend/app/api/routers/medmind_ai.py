from __future__ import annotations

import logging
import re

from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    Request,
    status,
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

    registry = (
        _get_registry(
            request
        )
    )

    try:

        service = await registry.get(
            tenant_id=
                tenant_id,
        )

        result = await service.chat(
            session_id=
                payload.session_id,

            message=
                payload.message,
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
        marbert_mode=None,

        operation_id=None,

        nlg_source=None,
        nlg_guard_passed=None,
        nlg_violations=[],
        nlg_fallback_reason=None,
    )