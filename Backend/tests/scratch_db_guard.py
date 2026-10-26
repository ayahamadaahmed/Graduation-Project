"""
Fail-closed target guard for the SCRATCH concurrency database only.

Committed concurrency fixtures may run only on a disposable restored copy
named MedMind_ConcScratch_<YYYYMMDD>_<6 lowercase hex>, never on the
approved audit database or any protected database. This module is separate
from the MedMind_Audit_Final2 guards (test_lab_booking_without_doctor_db,
test_doctor_verification_concurrency_db), which are not changed; it only
reuses their ODBC connection-string parser, read-only.

Every check must pass, or the test fails before anything is written:

  before connecting
    - MEDMIND_DB_INTEGRATION=1 and MEDMIND_SCRATCH_CONCURRENCY=1
    - APP_ENV=staging (so no .env file can supply the target)
    - MEDMIND_SCRATCH_DB_NAME: exactly the scratch pattern, ASCII only, and
      not a protected name (MedMind_Booking_DB, MedMind_Audit_Final2,
      MedMind_Audit_Final, or anything starting with MedMind_Audit or
      MedMind_Booking, in any letter case)
    - MEDMIND_SCRATCH_TOKEN: 32-128 lowercase hex characters
    - settings: server localhost\\SQLEXPRESS, DB_NAME equal to the scratch
      name, Windows trusted connection
    - the engine's own ODBC string: the same server, DATABASE equal to the
      scratch name, trusted connection, only the expected keys
  after connecting
    - SELECT DB_NAME() equals the scratch name
    - sys.databases: not read-only, not a database snapshot
    - dbo.zz_scratch_marker exists with exactly one row: scratch_name equal
      to DB_NAME(), source_db MedMind_Audit_Final2, token_sha256 equal to
      SHA-256(MEDMIND_SCRATCH_TOKEN). The marker is created only in the
      scratch copy (G5), so the source database can never pass.
    - alembic_version equals the expected revision

Logical file names are never read: the copy keeps the source's logical
names (MedMind_Booking_DB / MedMind_Booking_DB_log), and they must neither
allow nor block anything. Only database names and the marker decide.
"""

import hashlib
import os
import re
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings, staging_selected
from tests.test_lab_booking_without_doctor_db import (
    APPROVED_SERVER,
    _ALLOWED_ODBC_KEYS,
    _odbc_pairs,
)

SCRATCH_NAME_PATTERN = re.compile(r"MedMind_ConcScratch_[0-9]{8}_[0-9a-f]{6}", re.ASCII)
PROTECTED_DATABASES = frozenset({"medmind_booking_db", "medmind_audit_final2", "medmind_audit_final"})
PROTECTED_PREFIXES = ("medmind_audit", "medmind_booking")
TOKEN_PATTERN = re.compile(r"[0-9a-f]{32,128}", re.ASCII)
SOURCE_DATABASE = "MedMind_Audit_Final2"
EXPECTED_REVISION = "c3d9e6a2f8b1"
MARKER_TABLE = "dbo.zz_scratch_marker"


# ============================================================ pure checks (no I/O)


def scratch_name_problem(name) -> str | None:
    """Why `name` may not be used as the scratch database, or None."""
    if not isinstance(name, str) or not name:
        return "no scratch database name"
    if name != name.strip():
        return "the name has surrounding whitespace"
    folded = name.casefold()
    if folded in PROTECTED_DATABASES or folded.startswith(PROTECTED_PREFIXES):
        return "a protected database name"
    if not SCRATCH_NAME_PATTERN.fullmatch(name):
        return "not a MedMind_ConcScratch_<YYYYMMDD>_<6 lowercase hex> name"
    return None


def token_sha256(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def scratch_engine_problem(engine, name: str) -> str | None:
    """Why this engine's own target is not the scratch database, or None.
    Reads engine.url only; never connects. Mirrors unsafe_engine_target."""
    url = engine.url
    if url.drivername != "mssql+pyodbc":
        return "not an mssql+pyodbc engine"
    if url.host or url.port or url.database or url.username or url.password or set(url.query) != {"odbc_connect"}:
        return "the engine URL must carry only odbc_connect"
    raw = url.query["odbc_connect"]
    if not isinstance(raw, str):
        return "odbc_connect must appear once"
    try:
        pairs = _odbc_pairs(raw)
    except ValueError:
        return "unparseable ODBC connection string"
    keys = [key.upper() for key, _ in pairs]
    if len(keys) != len(set(keys)):
        return "duplicate ODBC keys"
    if set(keys) - _ALLOWED_ODBC_KEYS:
        return "unexpected ODBC keys"
    values = {key.upper(): value for key, value in pairs}
    if values.get("SERVER") != APPROVED_SERVER:
        return "not the approved server"
    database = values.get("DATABASE", "")
    if scratch_name_problem(database) is not None:
        return "the engine does not target a scratch database"
    if database != name:
        return "the engine targets a different scratch database"
    if values.get("TRUSTED_CONNECTION", "").lower() != "yes":
        return "not a Windows Trusted Connection"
    return None


def connected_problem(db_name, database_row, marker_exists, marker_rows, revision, name, token_hash) -> str | None:
    """Why a connected database is not the prepared scratch copy, or None.
    Pure: the values come from _verify_connected's read-only queries."""
    if db_name != name:
        return "connected to a different database"
    if database_row is None:
        return "the database is not listed in sys.databases"
    is_read_only, source_database_id = database_row
    if is_read_only or source_database_id is not None:
        return "a read-only database or a database snapshot"
    if not marker_exists:
        return "no scratch marker: not a prepared scratch database"
    if len(marker_rows) != 1:
        return "the scratch marker must hold exactly one row"
    marker_name, marker_source, marker_hash = marker_rows[0]
    if marker_name != name or marker_source != SOURCE_DATABASE or marker_hash != token_hash:
        return "the scratch marker does not match this run"
    if revision != EXPECTED_REVISION:
        return "unexpected alembic revision"
    return None


# ============================================================ guarded connections


def _fail(reason):
    pytest.fail(f"SCRATCH SAFETY STOP: {reason}.")


def require_scratch_target():
    """All checks before connecting. Returns (engine, name, token_hash)."""
    if os.getenv("MEDMIND_DB_INTEGRATION") != "1" or os.getenv("MEDMIND_SCRATCH_CONCURRENCY") != "1":
        _fail("MEDMIND_DB_INTEGRATION=1 and MEDMIND_SCRATCH_CONCURRENCY=1 are both required")
    if not staging_selected():
        _fail("APP_ENV=staging is required")
    name = os.getenv("MEDMIND_SCRATCH_DB_NAME")
    problem = scratch_name_problem(name)
    if problem:
        _fail(f"MEDMIND_SCRATCH_DB_NAME: {problem}")
    token = os.getenv("MEDMIND_SCRATCH_TOKEN", "")
    if not TOKEN_PATTERN.fullmatch(token):
        _fail("MEDMIND_SCRATCH_TOKEN must be 32-128 lowercase hex characters")
    settings = get_settings()
    if settings.db_server != APPROVED_SERVER or settings.db_name != name or not settings.db_trusted_connection:
        _fail("settings must name localhost\\SQLEXPRESS, the scratch database and a trusted connection")

    from app.db.session import engine

    problem = scratch_engine_problem(engine, name)
    if problem:
        _fail(problem)
    return engine, name, token_sha256(token)


def _verify_connected(connection, name, token_hash):
    db_name = connection.execute(text("SELECT DB_NAME()")).scalar_one()
    database_row = connection.execute(
        text("SELECT is_read_only, source_database_id FROM sys.databases WHERE name = DB_NAME()")
    ).first()
    marker_exists = connection.execute(
        text("SELECT OBJECT_ID(N'dbo.zz_scratch_marker', N'U')")
    ).scalar() is not None
    marker_rows = []
    if marker_exists:
        marker_rows = [tuple(row) for row in connection.execute(
            text("SELECT scratch_name, source_db, token_sha256 FROM dbo.zz_scratch_marker")
        ).all()]
    revision = connection.execute(text("SELECT TOP 1 version_num FROM dbo.alembic_version")).scalar()
    problem = connected_problem(db_name, database_row, marker_exists, marker_rows, revision, name, token_hash)
    if problem:
        _fail(problem)


def _quietly(cleanup):
    try:
        cleanup()
    except SQLAlchemyError:
        pass


@contextmanager
def scratch_connection(lock_timeout_ms):
    """A verified scratch connection with no open transaction; the caller
    decides what to begin, commit or roll back. Always discarded."""
    engine, name, token_hash = require_scratch_target()
    connection = engine.connect()
    try:
        _verify_connected(connection, name, token_hash)
        connection.rollback()
        connection.execute(text(f"SET LOCK_TIMEOUT {int(lock_timeout_ms)}"))
        connection.commit()  # ends the transaction that statement auto-began
        try:
            yield connection
        finally:
            _quietly(connection.rollback)
    finally:
        _quietly(connection.invalidate)
        _quietly(connection.close)


@contextmanager
def scratch_open_transaction(lock_timeout_ms):
    """An outer transaction held open (locks kept) with a savepoint-mode
    Session: a service's commit() only releases a SAVEPOINT. The caller ends
    it with .commit() or .rollback() at a chosen moment; anything not
    committed is rolled back."""
    with scratch_connection(lock_timeout_ms) as connection:
        outer = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint",
                          autoflush=False, expire_on_commit=False)
        try:
            yield SimpleNamespace(connection=connection, session=session,
                                  commit=outer.commit, rollback=outer.rollback)
        finally:
            _quietly(session.close)
            if outer.is_active:
                _quietly(outer.rollback)


@contextmanager
def scratch_committing_session(lock_timeout_ms):
    """A Session whose commit() really commits (scratch database only)."""
    with scratch_connection(lock_timeout_ms) as connection:
        session = Session(bind=connection, autoflush=False, expire_on_commit=False)
        try:
            yield SimpleNamespace(connection=connection, session=session)
        finally:
            _quietly(session.close)
