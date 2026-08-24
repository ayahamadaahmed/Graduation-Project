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
    public_catalog,
    medmind_ai,
)

from app.core.config import (
    get_settings,
)


settings = get_settings()


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