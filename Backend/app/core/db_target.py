"""Staging guard for the database the backend connects to.

Only active when APP_ENV=staging (trimmed, case-insensitive). There DB_NAME
must be configured explicitly (process environment or .env; the code default
does not count), and is refused when it is:

- empty or only whitespace (SQL Server would use the login's default
  database);
- MedMind_Booking_DB, in any letter case, after trimming;
- the .env.example placeholder, in any letter case, after trimming;
- holding ";", "=", "{" or "}": the name is placed into the ODBC connection
  string unescaped, so such values are refused rather than escaped.

Development and every other APP_ENV value are unchanged. Errors name the
field and the reason only, never the value or the connection string.

It inspects settings only: it never creates an engine or opens a connection.
The backend lifespan calls it before warm_db_pool(), the first connection,
and the no-connection preflight (app/core/preflight.py) reports it.
"""

from __future__ import annotations

from app.core.config import Settings, staging_selected

STAGING_APP_ENV = "staging"
PRODUCTION_DB_NAME = "MedMind_Booking_DB"
# The DB_NAME value shipped in .env.example.
EXAMPLE_PLACEHOLDER_DB_NAME = "<set-the-approved-database-name>"
CONNECTION_STRING_CHARACTERS = frozenset(";={}")


class UnsafeDatabaseTargetError(RuntimeError):
    """The configured database is not allowed for this APP_ENV."""


def is_staging(settings: Settings) -> bool:
    return settings.app_env.strip().lower() == STAGING_APP_ENV


def ensure_safe_database_target(settings: Settings) -> None:
    """Raise UnsafeDatabaseTargetError for an unsafe staging database target."""
    if not is_staging(settings):
        return

    # model_fields_set holds the fields given by the environment or .env,
    # never the class default.
    if "db_name" not in settings.model_fields_set:
        raise UnsafeDatabaseTargetError(
            "APP_ENV=staging requires DB_NAME to be set explicitly "
            "to the approved staging database."
        )

    name = settings.db_name.strip()

    if not name:
        raise UnsafeDatabaseTargetError(
            "APP_ENV=staging requires a non-empty DB_NAME."
        )

    if CONNECTION_STRING_CHARACTERS & set(name):
        raise UnsafeDatabaseTargetError(
            "APP_ENV=staging refuses a DB_NAME containing ';', '=', '{' or '}'."
        )

    if name.casefold() == PRODUCTION_DB_NAME.casefold():
        raise UnsafeDatabaseTargetError(
            "APP_ENV=staging must not use the production database "
            f"{PRODUCTION_DB_NAME}."
        )

    if name.casefold() == EXAMPLE_PLACEHOLDER_DB_NAME.casefold():
        raise UnsafeDatabaseTargetError(
            "APP_ENV=staging requires DB_NAME to be replaced: it still holds "
            "the .env.example placeholder."
        )


def ensure_safe_migration_target(settings: Settings, environ=None) -> None:
    """Raise UnsafeDatabaseTargetError unless Alembic may migrate this target.

    Called by migrations/env.py before any migration step, online or offline.
    Migrations run only with APP_ENV=staging in the PROCESS environment (a
    .env file cannot select it, see staging_selected), so DB_NAME must be set
    explicitly there and the code default MedMind_Booking_DB can never be
    migrated by accident; the staging rules above then apply unchanged.
    """
    if not staging_selected(environ):
        raise UnsafeDatabaseTargetError(
            "Migrations require APP_ENV=staging in the process environment "
            "and an explicit, approved DB_NAME."
        )

    ensure_safe_database_target(settings)
