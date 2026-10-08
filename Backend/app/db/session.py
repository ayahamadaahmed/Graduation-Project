from collections.abc import Generator

from sqlalchemy import (
    create_engine,
    text,
)
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)

def warm_db_pool() -> None:
    """
    Open and validate one database connection
    during application startup.

    This moves the first SQL Server connection
    cost out of the first patient request.
    """

    with engine.connect() as connection:

        connection.execute(
            text("SELECT 1")
        ).scalar_one()

def get_db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
