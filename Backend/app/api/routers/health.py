from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import engine

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=None)
def readiness():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    except SQLAlchemyError:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "database": "disconnected",
            },
        )

    # Public and unauthenticated: report reachability only, never the
    # database name or other infrastructure details.
    return {
        "status": "ok",
        "database": "connected",
    }