from logging.config import fileConfig

from alembic import context

from app.core.config import get_settings
from app.core.db_target import ensure_safe_migration_target
from app.db.base import Base

# Important:
# Import ORM models so Base.metadata
# knows about all mapped tables.
import app.models  # noqa: F401


config = context.config

settings = get_settings()

# Refuse an unintended target before any migration step (online or
# offline): APP_ENV=staging in the process environment and an explicit,
# approved DB_NAME are required (app/core/db_target.py).
ensure_safe_migration_target(settings)


if config.config_file_name is not None:
    fileConfig(
        config.config_file_name
    )


target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations without creating
    a live database connection.
    """

    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={
            "paramstyle": "named",
        },
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations using the existing
    SQLAlchemy SQL Server engine.
    """

    # Imported only after the target guard above has passed.
    from app.db.session import engine

    with engine.connect() as connection:

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=False,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()