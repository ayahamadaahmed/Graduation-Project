import logging
import re

from typing import Any

from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    Request,
    status,
)

# ============================================================
# FALLBACK GRAPH
# ============================================================
#
# Keep this import for:
#
# 1. Unit tests that monkeypatch booking_graph.ainvoke
# 2. Direct router tests where FastAPI lifespan
#    may not have been started.
#
# Production FastAPI runtime uses:
#
# request.app.state.booking_graph
#
# which is the persistent graph.

from ai_agent.graph import (
    booking_graph,
)

from app.schemas.ai_chat import (
    AIChatRequest,
    AIChatResponse,
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


# ============================================================
# TENANT VALIDATION
# ============================================================

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


# ============================================================
# THREAD ID
# ============================================================

def _build_thread_id(
    *,
    tenant_id: str,
    session_id: str,
) -> str:
    """
    Build a tenant-scoped LangGraph thread.

    Examples:

        tenant:
            clinic-001

        session:
            conversation-123

        result:
            clinic-001:conversation-123

    If the caller already sends:

        clinic-001:conversation-123

    do not prefix it twice.
    """

    session = (
        session_id.strip()
    )

    tenant_prefix = (
        f"{tenant_id}:"
    )

    if session.startswith(
        tenant_prefix
    ):

        return session

    return (
        f"{tenant_prefix}"
        f"{session}"
    )


# ============================================================
# GRAPH RESOLUTION
# ============================================================

def _get_booking_graph(
    request: Request,
) -> Any:
    """
    Prefer the persistent graph created during
    FastAPI lifespan.

    Fall back to the module-level in-memory graph
    for unit tests / direct router execution.
    """

    persistent_graph = getattr(
        request.app.state,
        "booking_graph",
        None,
    )

    if persistent_graph is not None:

        return persistent_graph

    return booking_graph


# ============================================================
# CHAT
# ============================================================

@router.post(
    "/chat",
    response_model=AIChatResponse,
    status_code=status.HTTP_200_OK,
)
async def chat(
    payload: AIChatRequest,

    request: Request,

    x_tenant_id: str = Header(
        ...,
        alias="X-Tenant-ID",
    ),
) -> AIChatResponse:

    # ========================================================
    # 1. TENANT
    # ========================================================

    tenant_id = (
        _validate_tenant_id(
            x_tenant_id
        )
    )

    # ========================================================
    # 2. TENANT-SAFE PERSISTENT THREAD
    # ========================================================

    thread_id = (
        _build_thread_id(
            tenant_id=tenant_id,

            session_id=(
                payload.session_id
            ),
        )
    )

    # ========================================================
    # 3. GRAPH
    # ========================================================

    graph = (
        _get_booking_graph(
            request
        )
    )

    # ========================================================
    # 4. INVOKE AGENT
    # ========================================================

    try:

        result = (
            await graph.ainvoke(
                {
                    "tenant_id":
                        tenant_id,

                    "session_id":
                        payload.session_id,

                    "user_message":
                        payload.message,
                },

                config={
                    "configurable": {
                        "thread_id":
                            thread_id,
                    }
                },
            )
        )

    except Exception:

        logger.exception(
            "AI booking agent "
            "request failed."
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

    # ========================================================
    # 5. VALIDATE AGENT RESULT
    # ========================================================

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
    # 6. REPLY
    # ========================================================

    reply = str(
        result.get(
            "reply"
        )
        or ""
    ).strip()

    if not reply:

        if (
            result.get(
                "language"
            )
            ==
            "en"
        ):

            reply = (
                "I couldn't process "
                "that request."
            )

        else:

            reply = (
                "مقدرتش أنفذ الطلب "
                "ده دلوقتي."
            )

    # ========================================================
    # 7. RESPONSE
    # ========================================================

    return AIChatResponse(
        session_id=(
            payload.session_id
        ),

        reply=reply,

        stage=str(
            result.get(
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

        language=(
            result.get(
                "language"
            )
        ),

        awaiting_confirmation=bool(
            result.get(
                "awaiting_confirmation",
                False,
            )
        ),

        appointment_reference=(
            result.get(
                "appointment_reference"
            )
        ),
        nlu_source=(
            result.get(
                "nlu_source"
            )
        ),

        nlu_provider=(
            result.get(
                "nlu_provider"
            )
        ),

        marbert_mode=(
            result.get(
                "marbert_mode"
            )
        ),

        error_code=(
            result.get(
                "error_code"
            )
        ),
        operation_id=(
            result.get(
                "operation_id"
            )
        ),

        operation_type=(
            result.get(
                "operation_type"
            )
        ),

        operation_status=(
            result.get(
                "operation_status"
            )
        ),

        response_type=(
            result.get(
                "response_type"
            )
        ),

        nlg_source=(
            result.get(
                "nlg_source"
            )
        ),

        nlg_guard_passed=(
            result.get(
                "nlg_guard_passed"
            )
        ),

        nlg_violations=list(
            result.get(
                "nlg_violations"
            )
            or []
        ),

        nlg_fallback_reason=(
            result.get(
                "nlg_fallback_reason"
            )
        ),
    )
