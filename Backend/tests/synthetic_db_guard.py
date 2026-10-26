"""
Fail-closed target guard for the SYNTHETIC concurrency database only.

Separate from tests/scratch_db_guard.py (restored scratch copies), which is
not changed. A synthetic database is created empty (S1), given the schema
generated from the models (S2) and seeded with the fake fixture
(tests/synthetic_fixture.py, S3). It never contains a copy of any data.

Every check must pass, or the test fails before anything is written:

  before connecting
    - MEDMIND_DB_INTEGRATION=1 and MEDMIND_SYNTHETIC_CONCURRENCY=1
    - APP_ENV=staging (so no .env file can supply the target)
    - MEDMIND_SYNTHETIC_DB_NAME: exactly MedMind_SynthConc_<YYYYMMDD>_<6
      lowercase hex>, ASCII only, and not a protected name or restored
      scratch name (MedMind_Booking_DB, MedMind_Audit_Final2,
      MedMind_Audit_Final, MedMind_Audit*, MedMind_Booking*,
      MedMind_ConcScratch*, in any letter case)
    - MEDMIND_SYNTHETIC_TOKEN: exactly 64 lowercase hex characters
    - settings and the engine's own ODBC string: server localhost\\SQLEXPRESS,
      the synthetic database, Windows trusted connection, expected keys only
  after connecting (positive proof that it IS the synthetic database)
    - every guard query runs under SET LOCK_TIMEOUT GUARD_LOCK_TIMEOUT_MS, so
      a lock held elsewhere ends in a refusal, never an indefinite wait; the
      caller's LOCK_TIMEOUT is set only after every check has passed; any
      error from a guard query is a refusal
    - @@SERVERNAME is the server every gate script pins
      (generate_synthetic_sql.SERVER_NAME)
    - DB_NAME() equals the name; ONLINE, writable, not a snapshot,
      READ_COMMITTED_SNAPSHOT OFF and snapshot isolation OFF
    - compatibility level 170 and collation SQL_Latin1_General_CP1_CI_AS,
      as S1 sets them (generate_synthetic_sql.SYNTHETIC_COMPATIBILITY_LEVEL,
      SYNTHETIC_COLLATION)
    - exactly two files, at exactly the paths S1 creates:
      <InstanceDefaultDataPath>\\<name>_data.mdf and
      <InstanceDefaultLogPath>\\<name>_log.ldf (sys.database_files)
    - msdb has never restored into this name (a synthetic database is never
      restored, so a restored copy can never pass)
    - dbo.zz_synthetic_marker: exactly one row, this name, kind synthetic,
      this fixture version, SHA-256(token), this fixture's manifest SHA-256
    - alembic_version: exactly one row, the expected revision
    - the schema's table.column set equals the generated schema exactly
    - every seeded table holds exactly its fixture rows and every other
      non-test table is empty (no foreign data)

These per-connection queries never read a table the tests write to (those
may be locked by a concurrent session); S4 checks those tables once, before
the run.
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
from tests import synthetic_fixture as fx
from tests.test_lab_booking_without_doctor_db import (
    APPROVED_SERVER,
    _ALLOWED_ODBC_KEYS,
    _odbc_pairs,
)
from tools import generate_synthetic_sql as generator

SYNTHETIC_NAME_PATTERN = re.compile(r"MedMind_SynthConc_[0-9]{8}_[0-9a-f]{6}", re.ASCII)
PROTECTED_DATABASES = frozenset({"medmind_booking_db", "medmind_audit_final2", "medmind_audit_final"})
PROTECTED_PREFIXES = ("medmind_audit", "medmind_booking", "medmind_concscratch")
TOKEN_PATTERN = re.compile(r"[0-9a-f]{64}", re.ASCII)
EXPECTED_SERVER_NAME = generator.SERVER_NAME
EXPECTED_COMPATIBILITY_LEVEL = generator.SYNTHETIC_COMPATIBILITY_LEVEL  # as S1 sets it
EXPECTED_COLLATION = generator.SYNTHETIC_COLLATION  # as S1 sets it
# The per-connection guard queries only take shared locks on catalog views,
# msdb, the marker and seeded/empty tables; nothing on the tested paths
# blocks them. If that ever changes, they fail after this long instead of
# hanging a worker.
GUARD_LOCK_TIMEOUT_MS = 5000
EXPECTED_COLUMNS = tuple(generator.schema_column_lines())
EXPECTED_COUNTS = generator.guard_expected_counts()
COUNTS_SQL = generator.guard_counts_sql()


# ============================================================ pure checks (no I/O)


def synthetic_name_problem(name) -> str | None:
    """Why `name` may not be used as the synthetic database, or None."""
    if not isinstance(name, str) or not name:
        return "no synthetic database name"
    if name != name.strip():
        return "the name has surrounding whitespace"
    folded = name.casefold()
    if folded in PROTECTED_DATABASES or folded.startswith(PROTECTED_PREFIXES):
        return "a protected or restored-copy database name"
    if not SYNTHETIC_NAME_PATTERN.fullmatch(name):
        return "not a MedMind_SynthConc_<YYYYMMDD>_<6 lowercase hex> name"
    return None


def token_sha256(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def synthetic_engine_problem(engine, name: str) -> str | None:
    """Why this engine's own target is not the synthetic database, or None.
    Reads engine.url only; never connects."""
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
    if synthetic_name_problem(database) is not None:
        return "the engine does not target a synthetic database"
    if database != name:
        return "the engine targets a different synthetic database"
    if values.get("TRUSTED_CONNECTION", "").lower() != "yes":
        return "not a Windows Trusted Connection"
    return None


def s1_file_paths(data_dir, log_dir, name):
    """The (data, log) paths S1 creates, built exactly as S1 builds them, or
    None when the instance reports no default path."""
    if not data_dir or not log_dir:
        return None
    data_dir = data_dir if data_dir.endswith("\\") else data_dir + "\\"
    log_dir = log_dir if log_dir.endswith("\\") else log_dir + "\\"
    return data_dir + name + "_data.mdf", log_dir + name + "_log.ldf"


def file_problem(files, default_paths, name) -> str | None:
    """Why the database files are not exactly the S1 files, or None. Compared
    case-insensitively, as S1 and S6 compare them (LOWER)."""
    expected = s1_file_paths(*default_paths, name) if default_paths else None
    if expected is None:
        return "the instance reports no default data or log path"
    actual = sorted((int(kind), str(path).lower()) for kind, path in files)
    if actual != [(0, expected[0].lower()), (1, expected[1].lower())]:
        return "the database files are not exactly the S1 paths"
    return None


def identity_problem(facts, name) -> str | None:
    """Why the connected server/database is not the synthetic database's
    identity (server, name, state, files, restore history), or None. Pure.
    Decided before anything inside the database is read."""
    if facts.server_name != EXPECTED_SERVER_NAME:
        return "not the expected SQL Server instance (@@SERVERNAME)"
    if facts.db_name != name:
        return "connected to a different database"
    if facts.database_row is None:
        return "the database is not listed in sys.databases"
    state, is_read_only, source_database_id, rcsi, snapshot, level, collation = facts.database_row
    if state != "ONLINE" or is_read_only or source_database_id is not None:
        return "not an ONLINE, writable, non-snapshot database"
    if rcsi or snapshot:
        return "READ_COMMITTED_SNAPSHOT and snapshot isolation must be OFF"
    if level != EXPECTED_COMPATIBILITY_LEVEL:
        return f"the compatibility level must be {EXPECTED_COMPATIBILITY_LEVEL}, as S1 sets it"
    if collation != EXPECTED_COLLATION:
        return f"the collation must be {EXPECTED_COLLATION}, as S1 sets it"
    problem = file_problem(facts.files, facts.default_paths, name)
    if problem:
        return problem
    if facts.restore_history_rows != 0:
        return "this name was the target of a RESTORE: never a synthetic database"
    return None


def connected_problem(facts, name, token_hash) -> str | None:
    """Why a connected database is not the prepared synthetic database, or
    None. Pure: `facts` come from _read_facts' read-only queries."""
    problem = identity_problem(facts, name)
    if problem:
        return problem
    if not facts.marker_exists:
        return "no synthetic marker: not a prepared synthetic database"
    if len(facts.marker_rows) != 1:
        return "the synthetic marker must hold exactly one row"
    marker_name, kind, version, marker_token, manifest = facts.marker_rows[0]
    if (marker_name, kind, version) != (name, fx.MARKER_KIND, fx.FIXTURE_VERSION):
        return "the synthetic marker does not describe this database and fixture"
    if marker_token != token_hash:
        return "the synthetic marker does not match this run's token"
    if manifest != fx.MANIFEST_SHA256:
        return "the synthetic marker's fixture manifest does not match"
    if list(facts.revisions) != [fx.EXPECTED_REVISION]:
        return "unexpected alembic revision"
    if tuple(facts.columns) != EXPECTED_COLUMNS:
        return "the schema is not exactly the generated synthetic schema"
    if dict(facts.counts) != EXPECTED_COUNTS:
        return "row counts do not match the synthetic fixture manifest (foreign or missing rows)"
    return None


# ============================================================ guarded connections


def _fail(reason):
    pytest.fail(f"SYNTHETIC SAFETY STOP: {reason}.")


def require_synthetic_target():
    """All checks before connecting. Returns (engine, name, token_hash)."""
    if os.getenv("MEDMIND_DB_INTEGRATION") != "1" or os.getenv("MEDMIND_SYNTHETIC_CONCURRENCY") != "1":
        _fail("MEDMIND_DB_INTEGRATION=1 and MEDMIND_SYNTHETIC_CONCURRENCY=1 are both required")
    if not staging_selected():
        _fail("APP_ENV=staging is required")
    name = os.getenv("MEDMIND_SYNTHETIC_DB_NAME")
    problem = synthetic_name_problem(name)
    if problem:
        _fail(f"MEDMIND_SYNTHETIC_DB_NAME: {problem}")
    token = os.getenv("MEDMIND_SYNTHETIC_TOKEN", "")
    if not TOKEN_PATTERN.fullmatch(token):
        _fail("MEDMIND_SYNTHETIC_TOKEN must be exactly 64 lowercase hex characters")
    settings = get_settings()
    if settings.db_server != APPROVED_SERVER or settings.db_name != name or not settings.db_trusted_connection:
        _fail("settings must name localhost\\SQLEXPRESS, the synthetic database and a trusted connection")

    from app.db.session import engine

    problem = synthetic_engine_problem(engine, name)
    if problem:
        _fail(problem)
    return engine, name, token_sha256(token)


def _read_facts(connection, name):
    """Read-only, in two stages. Stage 1 reads only server and catalog
    identity (no table inside the database). Stage 2 (marker, revision,
    schema, row counts) runs only if identity_problem() found nothing and the
    marker table exists; otherwise its facts stay empty and are never read."""
    db_name, server_name, data_dir, log_dir = connection.execute(text(
        "SELECT DB_NAME(), @@SERVERNAME, CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(260)), "
        "CAST(SERVERPROPERTY('InstanceDefaultLogPath') AS nvarchar(260))"
    )).one()
    database_row = connection.execute(text(
        "SELECT state_desc, is_read_only, source_database_id, is_read_committed_snapshot_on, "
        "snapshot_isolation_state, compatibility_level, collation_name FROM sys.databases WHERE name = DB_NAME()"
    )).first()
    files = [tuple(row) for row in connection.execute(
        text("SELECT type, physical_name FROM sys.database_files")).all()]
    restore_history_rows = connection.execute(text(
        "SELECT COUNT(*) FROM msdb.dbo.restorehistory WHERE destination_database_name = DB_NAME()"
    )).scalar_one()
    facts = SimpleNamespace(db_name=db_name, server_name=server_name, default_paths=(data_dir, log_dir),
                            database_row=tuple(database_row) if database_row else None, files=files,
                            restore_history_rows=restore_history_rows, marker_exists=False,
                            marker_rows=[], revisions=[], columns=[], counts={})
    if identity_problem(facts, name):
        return facts  # not this synthetic database: nothing inside it is read
    facts.marker_exists = connection.execute(
        text(f"SELECT OBJECT_ID(N'dbo.{fx.MARKER_TABLE}', N'U')")
    ).scalar() is not None
    if not facts.marker_exists:
        return facts  # nothing else is read from an unmarked database
    facts.marker_rows = [tuple(row) for row in connection.execute(text(
        f"SELECT database_name, marker_kind, fixture_version, token_sha256, manifest_sha256 FROM dbo.{fx.MARKER_TABLE}"
    )).all()]
    facts.revisions = [row[0] for row in connection.execute(
        text("SELECT version_num FROM dbo.alembic_version")).all()]
    facts.columns = sorted(row[0] for row in connection.execute(text(
        "SELECT t.name + N'.' + c.name FROM sys.tables AS t JOIN sys.columns AS c ON c.object_id = t.object_id "
        f"WHERE t.schema_id = SCHEMA_ID(N'dbo') AND t.is_ms_shipped = 0 AND t.name <> N'{fx.MARKER_TABLE}'"
    )).all())
    facts.counts = dict(connection.execute(text(COUNTS_SQL)).mappings().one())
    return facts


def _verify_connected(connection, name, token_hash):
    try:
        facts = _read_facts(connection, name)
    # SQLAlchemyError: query errors, lock timeout 1222, missing or extra rows;
    # ValueError/TypeError: a row of the wrong shape. Never proceed unverified.
    except (SQLAlchemyError, ValueError, TypeError) as error:
        _fail(f"a guard query failed ({type(error).__name__}); the database was not verified")
    problem = connected_problem(facts, name, token_hash)
    if problem:
        _fail(problem)


def _quietly(cleanup):
    try:
        cleanup()
    except SQLAlchemyError:
        pass


@contextmanager
def synthetic_connection(lock_timeout_ms):
    """A verified synthetic connection with no open transaction. Always discarded."""
    engine, name, token_hash = require_synthetic_target()
    connection = engine.connect()
    try:
        connection.execute(text(f"SET LOCK_TIMEOUT {GUARD_LOCK_TIMEOUT_MS}"))  # before any guard query
        connection.commit()
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
def synthetic_open_transaction(lock_timeout_ms):
    """An outer transaction held open (locks kept) with a savepoint-mode
    Session; the caller ends it with .commit() or .rollback()."""
    with synthetic_connection(lock_timeout_ms) as connection:
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
def synthetic_committing_session(lock_timeout_ms):
    """A Session whose commit() really commits (synthetic database only)."""
    with synthetic_connection(lock_timeout_ms) as connection:
        session = Session(bind=connection, autoflush=False, expire_on_commit=False)
        try:
            yield SimpleNamespace(connection=connection, session=session)
        finally:
            _quietly(session.close)
