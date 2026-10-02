from __future__ import annotations
import os
from dotenv import (
  load_dotenv,
)
from app.api.routers import (
    staff_patients,
)
from langchain_openai import (
    ChatOpenAI,
)
import httpx
from app.api.routers import auth
import logging
import time

from contextlib import (
    asynccontextmanager,
)
from app.db.session import (
    warm_db_pool,
)
from fastapi import (
    FastAPI,
    Request,
)

from fastapi.responses import (
    JSONResponse,
)

from sqlalchemy.exc import (
    SQLAlchemyError,
)

from app.api.routers import (
    admin_working_hours,
    appointments,
    catalog,
    health,
    patients,
    post_call,
    public_catalog,
    medmind_ai,
)
from medmind.response_verbalizer import (
    QwenResponseVerbalizer,
)
from app.core.config import (
    get_settings,
)

from app.services.medmind_registry import (
    MedMindServiceRegistry,
)

from medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)
from medmind.understanding.qwen_tool_planner import (
    QwenToolPlanner,
)

from medmind.understanding.fallback_tool_planner import (
    FallbackToolPlanner,
)

from medmind.understanding.tool_planner import (
    ToolPlanner,
)
from rag.embeddings import (    
    get_embedding_model,
)
# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger(
    "uvicorn.error"
)


# ============================================================
# SETTINGS
# ============================================================

settings = get_settings()


# ============================================================
# APPLICATION LIFESPAN
# ============================================================

@asynccontextmanager
async def lifespan(
    app: FastAPI,
):

    startup_started = (
        time.perf_counter()
    )

    load_dotenv(
        override=True
    )

    rag_warmup_started = (
        time.perf_counter()
    )

    rag_embedding_model = (
        get_embedding_model()
    )

    rag_embedding_model.encode(
        "What is the cancellation policy?",
        normalize_embeddings=True,
    )

    rag_warmup_ms = (
        (
            time.perf_counter()
            - rag_warmup_started
        )
        * 1000
    )

    logger.info(
        "rag_embedding_warmup "
        "total_ms=%.2f "
        "status=success",
        rag_warmup_ms,
    )

    # ========================================================
    # DATABASE POOL WARM-UP
    # ========================================================

    db_warmup_started = (
        time.perf_counter()
    )

    warm_db_pool()

    db_warmup_ms = (
        (
            time.perf_counter()
            - db_warmup_started
        )
        * 1000
    )

    logger.info(
        "database_pool_warmup "
        "total_ms=%.2f "
        "status=success",
        db_warmup_ms,
    )

    router_started = (
        time.perf_counter()
    )

    shared_router = (
        SemanticCapabilityRouter()
    )

    # ========================================================
    # SEMANTIC ROUTER WARM-UP
    #
    # Pay the first-inference CPU cost during application
    # startup instead of making the first user wait for it.
    # ========================================================

    router_warmup_started = time.perf_counter()

    shared_router.route(
        "عايزة أحجز كشف",
        top_k=1,
    )

    router_warmup_ms = (
        time.perf_counter()
        - router_warmup_started
    ) * 1000

    logger.info(
        "semantic_router_warmup "
        "total_ms=%.2f "
        "status=success",
        router_warmup_ms,
    )

    router_ms = (
        time.perf_counter()
        - router_started
    ) * 1000

    model_started = (
        time.perf_counter()
    )

    model_name = os.getenv(
        "OPENAI_MODEL",
        "gpt-4.1",
    )

    # ========================================================
    # SHARED GPT MODEL
    #
    # Used by the existing MedMind LLM paths and remains
    # available as the final legacy safety layer.
    # ========================================================

    shared_model = ChatOpenAI(
        model=model_name,
        temperature=0,
        timeout=60,
    )


    # ========================================================
    # QWEN PRIMARY PLANNER
    # ========================================================

    groq_api_key = os.getenv(
        "GROQ_API_KEY"
    )

    if not groq_api_key:
        raise RuntimeError(
            "GROQ_API_KEY is required for "
            "the Qwen primary planner."
        )

    qwen_planner_model = os.getenv(
        "QWEN_PLANNER_MODEL",
        "qwen/qwen3.6-27b",
    )

    qwen_service_tier = os.getenv(
        "QWEN_SERVICE_TIER",
        "on_demand",
    ).strip().lower()

    qwen_planner_timeout = float(
        os.getenv(
            "QWEN_PLANNER_TIMEOUT",
            "3",
        )
    )

    qwen_primary_budget = float(
        os.getenv(
            "QWEN_PRIMARY_BUDGET",
            "1.5",
        )
    )

    if qwen_primary_budget <= 0:

        raise RuntimeError(
            "QWEN_PRIMARY_BUDGET "
            "must be greater than zero."
        )

    qwen_fallback_hedge_delay = float(
        os.getenv(
            "QWEN_FALLBACK_HEDGE_DELAY",
            "0.9",
        )
    )

    if qwen_fallback_hedge_delay <= 0:

        raise RuntimeError(
            "QWEN_FALLBACK_HEDGE_DELAY "
            "must be greater than zero."
        )

    if (
        qwen_fallback_hedge_delay
        >= qwen_primary_budget
    ):

        raise RuntimeError(
            "QWEN_FALLBACK_HEDGE_DELAY "
            "must be lower than "
            "QWEN_PRIMARY_BUDGET."
        )

    qwen_planner_max_tokens = int(
        os.getenv(
            "QWEN_PLANNER_MAX_TOKENS",
            "160",
        )
    )

    async def qwen_http_request_hook(
        request: httpx.Request,
    ) -> None:
        request.extensions[
            "medmind_started_at"
        ] = time.perf_counter()


    async def qwen_http_response_hook(
        response: httpx.Response,
    ) -> None:
        started_at = response.request.extensions.get(
            "medmind_started_at"
        )

        if started_at is None:
            return

        headers_ms = (
            time.perf_counter() - started_at
        ) * 1000

        logger.info(
            "qwen_http_timing "
            "method=%s "
            "path=%s "
            "headers_ms=%.2f "
            "status_code=%s",
            response.request.method,
            response.request.url.path,
            headers_ms,
            response.status_code,
        )

    qwen_http_client = httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20,
            keepalive_expiry=60.0,
        ),
        timeout=httpx.Timeout(
            qwen_planner_timeout,
        ),
        event_hooks={
            "request": [
                qwen_http_request_hook,
            ],
            "response": [
                qwen_http_response_hook,
            ],
        },
    )

    qwen_planner = QwenToolPlanner(
        api_key=groq_api_key,
        model=qwen_planner_model,
        timeout=qwen_planner_timeout,
        max_tokens=qwen_planner_max_tokens,
        http_client=qwen_http_client,
        service_tier=qwen_service_tier,
    )

    await qwen_planner.warmup()

    # ========================================================
    # SHARED RESPONSE VERBALIZER
    # ========================================================

    response_verbalizer = (
        QwenResponseVerbalizer(
            client=qwen_planner.client,
            model=qwen_planner.model,
            service_tier=(
                qwen_planner.service_tier
            ),
            timeout_seconds=float(
                os.getenv(
                    "QWEN_VERBALIZER_TIMEOUT",
                    "0.8",
                )
            ),
            max_tokens=int(
                os.getenv(
                    "QWEN_VERBALIZER_MAX_TOKENS",
                    "100",
                )
            ),
        )
    )

    # ========================================================
    # GPT-4.1 FALLBACK PLANNER
    # ========================================================

    fallback_planner_model_name = os.getenv(
        "PLANNER_FALLBACK_MODEL",
        "gpt-4.1",
    )

    gpt_planner_timeout = float(
        os.getenv(
            "GPT_PLANNER_TIMEOUT",
            "4",
        )
    )

    if gpt_planner_timeout <= 0:
        raise RuntimeError(
            "GPT_PLANNER_TIMEOUT must be greater than zero."
        )

    shared_planner_model = ChatOpenAI(
        model=fallback_planner_model_name,
        temperature=0,
        timeout=gpt_planner_timeout,
        max_retries=0,
    )

    gpt_fallback_planner = ToolPlanner(
        model=shared_planner_model,
    )


    # ========================================================
    # PRIMARY + FALLBACK
    # ========================================================

    shared_planner = FallbackToolPlanner(
        primary=qwen_planner,
        fallback=gpt_fallback_planner,
        primary_timeout_seconds=(
            qwen_primary_budget
        ),
        fallback_hedge_delay_seconds=(
            qwen_fallback_hedge_delay
        ),
    )

    model_ms = (
        time.perf_counter()
        - model_started
    ) * 1000

    registry_started = (
        time.perf_counter()
    )

    registry = MedMindServiceRegistry(
        shared_router=shared_router,
        shared_model=shared_model,
        shared_planner_model=shared_planner_model,
        shared_planner=shared_planner,
        shared_response_verbalizer=(
            response_verbalizer
        ),
    )

    registry_ms = (
        time.perf_counter()
        - registry_started
    ) * 1000

    # ========================================================
    # APPLICATION STATE
    # ========================================================

    app.state.medmind_semantic_router = (
        shared_router
    )

    app.state.medmind_model = shared_model

    app.state.medmind_planner_model = (
        shared_planner_model
    )

    app.state.medmind_planner = (
        shared_planner
    )

    app.state.medmind_qwen_planner = (
        qwen_planner
    )

    app.state.medmind_registry = registry


    total_ms = (
        time.perf_counter()
        - startup_started
    ) * 1000

    logger.info(
        "medmind_ai_startup_timing "
        "semantic_router_ms=%.2f "
        "model_ms=%.2f "
        "registry_ms=%.2f "
        "total_ms=%.2f",
        router_ms,
        model_ms,
        registry_ms,
        total_ms,
    )


    # ========================================================
    # APPLICATION READY
    # ========================================================

    yield



    # ========================================================
    # SHUTDOWN
    # ========================================================

    await registry.close()

    await qwen_http_client.aclose()

    app.state.medmind_registry = None
    app.state.medmind_semantic_router = None
    app.state.medmind_model = None
    app.state.medmind_planner_model = None
    app.state.medmind_planner = None
    app.state.medmind_qwen_planner = None

# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title=settings.app_name,

    version="0.1.0",

    description=(
        "Clean FastAPI backend for the "
        "MedMind healthcare platform."
    ),

    lifespan=lifespan,
)


# ============================================================
# DATABASE ERROR HANDLER
# ============================================================

@app.exception_handler(
    SQLAlchemyError
)
async def sqlalchemy_exception_handler(
    request: Request,
    exc: SQLAlchemyError,
) -> JSONResponse:

    return JSONResponse(
        status_code=503,

        content={
            "detail": {
                "code":
                    "DATABASE_ERROR",

                "message":
                    (
                        "The database operation "
                        "could not be completed."
                    ),
            }
        },
    )


# ============================================================
# LIVE HEALTH
# ============================================================

@app.get(
    "/health/live"
)
def health_live():

    return {
        "status":
            "ok"
    }


# ============================================================
# ROOT
# ============================================================

@app.get(
    "/",
    tags=[
        "root"
    ],
)
def root() -> dict[
    str,
    str,
]:

    return {
        "service":
            settings.app_name,

        "status":
            "running",

        "docs":
            "/docs",
    }


# ============================================================
# ROUTERS
# ============================================================

app.include_router(
    health.router
)

app.include_router(
    catalog.router,
    prefix="/api/v1",
)

app.include_router(
    public_catalog.router,
    prefix="/api/v1",
)

app.include_router(
    admin_working_hours.router,
    prefix="/api/v1",
)

app.include_router(
    patients.router,
    prefix="/api/v1",
)

app.include_router(
    appointments.router,
    prefix="/api/v1",
)

app.include_router(
    medmind_ai.router,
    prefix="/api/v1",
)

app.include_router(
    post_call.router,
    prefix="/api/v1",
)

app.include_router(
    auth.router,
    prefix="/api/v1",
)

app.include_router(
    staff_patients.router,
    prefix="/api/v1",
)