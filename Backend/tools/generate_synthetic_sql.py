"""
OFFLINE generator for the synthetic concurrency database scripts:

  S2_schema.sql   - the schema, compiled from the SQLAlchemy models
  S3_seed.sql     - the deterministic fake fixture (tests/synthetic_fixture.py)
  S4_verify_synthetic_readonly.sql - read-only proof that a database is
                    exactly the synthetic one

It only imports the ORM models (app.models registers tables on Base.metadata
and imports no settings, engine or .env) and compiles DDL text with the SQL
Server dialect. It never creates an engine or connects anywhere.

  python tools/generate_synthetic_sql.py --check   # compare with the pinned files
  python tools/generate_synthetic_sql.py --write   # rewrite them (then re-pin)

SCHEMA FIDELITY: the output reflects the models only. Anything that exists
only in a real database (triggers, named defaults, computed columns, views,
procedures, extra indexes, different column types) is NOT reproduced, and
the output is not claimed to match MedMind_Audit_Final2 (see README.md).
"""

import argparse
import hashlib
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
OUTPUT = BACKEND.parent / "Database_latest" / "synthetic_concurrency"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import sqlalchemy  # noqa: E402
from sqlalchemy import MetaData  # noqa: E402
from sqlalchemy.dialects import mssql  # noqa: E402
from sqlalchemy.schema import AddConstraint, CreateIndex, CreateTable  # noqa: E402

import app.models  # noqa: E402,F401  (registers every table)
from app.db.base import Base  # noqa: E402
from tests import synthetic_fixture as fx  # noqa: E402

SERVER_NAME = r"LAPTOP-FACHLL1N\SQLEXPRESS"
# Pinned by S1 (CREATE DATABASE ... COLLATE, SET COMPATIBILITY_LEVEL): option B
# of PROPOSED_S1_COMPATIBILITY_LEVEL.md, the values S0 reported for model.
# Re-checked by S4 and tests/synthetic_db_guard.py.
SYNTHETIC_COMPATIBILITY_LEVEL = 170
SYNTHETIC_COLLATION = "SQL_Latin1_General_CP1_CI_AS"
NAME_LIKE = ("N'MedMind[_]SynthConc[_][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]"
             "[_][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'")
NAME_BYTES = 66  # 33 characters, nvarchar
SQL_SERVER_VERSION = (16, 0, 0)  # compile as a modern server: DATE/TIME/NVARCHAR(max), not DATETIME/NTEXT
# sqlserver_dialect() and schema_metadata() use private SQLAlchemy APIs
# (_setup_version_attributes, _creation_order), so the output is only
# reviewed for this exact version (the pin in requirements-prod.txt).
SQLALCHEMY_VERSION = "2.0.51"

# Integer primary keys that the dialect would otherwise turn into IDENTITY.
# patient_number_sequences.year is a natural key (a calendar year); an
# IDENTITY there is an artifact of SQLAlchemy's autoincrement="auto".
NO_IDENTITY = {("patient_number_sequences", "year")}

ALEMBIC_TABLE = "alembic_version"
FILES = ("S2_schema.sql", "S3_seed.sql", "S4_verify_synthetic_readonly.sql")

# The schema fingerprint, computed inside the synthetic database: SHA-256
# over UTF-16LE "table.column" lines (dbo user tables, marker excluded),
# sorted by code point and joined with LF. schema_fingerprint() computes the
# same value offline. S6 embeds this exact expression (checked by a test).
FINGERPRINT_SQL = (
    "(SELECT HASHBYTES('SHA2_256', STRING_AGG(CAST(t.name + N'.' + c.name AS nvarchar(max)), NCHAR(10))\n"
    "        WITHIN GROUP (ORDER BY t.name + N'.' + c.name COLLATE Latin1_General_BIN2))\n"
    " FROM sys.tables AS t JOIN sys.columns AS c ON c.object_id = t.object_id\n"
    " WHERE t.schema_id = SCHEMA_ID(N'dbo') AND t.is_ms_shipped = 0 AND t.name <> N'zz_synthetic_marker')"
)


def sqlserver_dialect():
    dialect = mssql.dialect(deprecate_large_types=True)
    dialect.server_version_info = SQL_SERVER_VERSION
    dialect._setup_version_attributes()
    return dialect


_CONSTRAINT_KIND = {"PrimaryKeyConstraint": 0, "UniqueConstraint": 1, "CheckConstraint": 2,
                    "ForeignKeyConstraint": 3}


def _constraint_key(constraint):
    return (_CONSTRAINT_KIND.get(type(constraint).__name__, 9), constraint.name or "",
            tuple(c.name for c in getattr(constraint, "columns", ())), str(getattr(constraint, "sqltext", "")))


def schema_metadata():
    """A copy of the model metadata in schema dbo, with NO_IDENTITY applied.

    Table.constraints is a set, and to_metadata() copies it in set order,
    which depends on object identity and so differs between processes.
    CreateTable() orders constraints by their creation counter, so the
    copies are renumbered here in a stable order (kind, name, columns):
    the output is then byte-identical in every process."""
    metadata = MetaData()
    for table in sorted(Base.metadata.tables.values(), key=lambda t: t.name):
        copy = table.to_metadata(metadata, schema="dbo")
        for position, constraint in enumerate(sorted(copy.constraints, key=_constraint_key)):
            constraint._creation_order = position
    for table_name, column_name in NO_IDENTITY:
        metadata.tables[f"dbo.{table_name}"].c[column_name].autoincrement = False
    return metadata


def _clean(ddl):
    return "\n".join(line.rstrip() for line in str(ddl).strip().splitlines())


def schema_column_lines():
    metadata = schema_metadata()
    lines = [f"{t.name}.{c.name}" for t in metadata.tables.values() for c in t.columns]
    lines.append(f"{ALEMBIC_TABLE}.version_num")
    return sorted(lines)


def schema_fingerprint():
    return hashlib.sha256("\n".join(schema_column_lines()).encode("utf-16-le")).hexdigest()


def schema_tables():
    return sorted([t.name for t in schema_metadata().tables.values()] + [ALEMBIC_TABLE])


def empty_tables():
    """Tables that must hold no rows at all in a synthetic database."""
    return [t for t in schema_tables()
            if t not in fx.SYNTHETIC_SEED_TABLES and t not in fx.SYNTHETIC_TEST_WRITABLE_TABLES and t != ALEMBIC_TABLE]


# ------------------------------------------------------------------ shared SQL fragments


def _name_checks(code):
    return f"""IF @@SERVERNAME <> N'{SERVER_NAME}'
    THROW {code}, N'Refused: unexpected server.', 1;
IF @synthetic_name IS NULL
   OR DATALENGTH(@synthetic_name) <> {NAME_BYTES}
   OR @synthetic_name COLLATE Latin1_General_BIN NOT LIKE
      {NAME_LIKE}
    THROW {code + 1}, N'Refused: the name is not MedMind_SynthConc_<YYYYMMDD>_<6 lowercase hex>.', 1;
IF LOWER(@synthetic_name) IN (N'medmind_booking_db', N'medmind_audit_final2', N'medmind_audit_final')
   OR LOWER(@synthetic_name) LIKE N'medmind[_]audit%' OR LOWER(@synthetic_name) LIKE N'medmind[_]booking%'
   OR LOWER(@synthetic_name) LIKE N'medmind[_]concscratch%'
    THROW {code + 2}, N'Refused: protected or restored-copy database name.', 1;"""


def _in_synthetic_database_checks(code):
    return f"""{_name_checks(code)}
IF DB_NAME() COLLATE Latin1_General_BIN <> @synthetic_name COLLATE Latin1_General_BIN
    THROW {code + 3}, N'Refused: not connected to the named synthetic database.', 1;
IF NOT EXISTS (SELECT 1 FROM sys.databases
               WHERE name = DB_NAME() AND state_desc = N'ONLINE' AND is_read_only = 0
                 AND source_database_id IS NULL AND is_read_committed_snapshot_on = 0
                 AND snapshot_isolation_state = 0)
    THROW {code + 4}, N'Refused: database must be ONLINE, writable, not a snapshot, with RCSI and snapshot isolation OFF.', 1;
IF EXISTS (SELECT 1 FROM msdb.dbo.restorehistory WHERE destination_database_name = DB_NAME())
    THROW {code + 5}, N'Refused: this database name was the target of a RESTORE; a synthetic database is never restored.', 1;"""


def _level_and_collation_check(code):
    """The compatibility level and collation S1 pins (S4 only; S2/S3 run
    right after S1 and are unchanged)."""
    return f"""IF NOT EXISTS (SELECT 1 FROM sys.databases
               WHERE name = DB_NAME() AND compatibility_level = {SYNTHETIC_COMPATIBILITY_LEVEL}
                 AND collation_name = N'{SYNTHETIC_COLLATION}')
    THROW {code}, N'Refused: compatibility level must be {SYNTHETIC_COMPATIBILITY_LEVEL} and collation {SYNTHETIC_COLLATION}, as S1 sets them.', 1;"""


def _file_path_check(code):
    """Exactly two files, at exactly the paths S1 creates (as S1 and S6 build
    them). sys.database_files: the current database only, no master read."""
    return f"""DECLARE @data_dir nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(260));
DECLARE @log_dir nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultLogPath') AS nvarchar(260));
IF @data_dir IS NULL OR @log_dir IS NULL
    THROW {code}, N'Refused: the instance has no default data or log path.', 1;
IF RIGHT(@data_dir, 1) <> N'\\' SET @data_dir += N'\\';
IF RIGHT(@log_dir, 1) <> N'\\' SET @log_dir += N'\\';
IF (SELECT COUNT(*) FROM sys.database_files) <> 2
   OR NOT EXISTS (SELECT 1 FROM sys.database_files
                  WHERE type = 0 AND LOWER(physical_name) = LOWER(@data_dir + DB_NAME() + N'_data.mdf'))
   OR NOT EXISTS (SELECT 1 FROM sys.database_files
                  WHERE type = 1 AND LOWER(physical_name) = LOWER(@log_dir + DB_NAME() + N'_log.ldf'))
    THROW {code + 1}, N'Refused: the database files are not exactly the S1 paths.', 1;"""


def _fingerprint_check(code):
    return f"""IF ISNULL({FINGERPRINT_SQL.replace(chr(10), chr(10) + '          ')}, 0x00)
   <> 0x{schema_fingerprint().upper()}
    THROW {code}, N'Refused: the schema is not exactly the generated synthetic schema.', 1;"""


def _revision_check(code):
    return f"""IF OBJECT_ID(N'dbo.{ALEMBIC_TABLE}', N'U') IS NULL
   OR (SELECT COUNT(*) FROM dbo.{ALEMBIC_TABLE}) <> 1
   OR NOT EXISTS (SELECT 1 FROM dbo.{ALEMBIC_TABLE} WHERE version_num = '{fx.EXPECTED_REVISION}')
    THROW {code}, N'Refused: unexpected alembic revision.', 1;"""


def guard_counts_sql():
    """One read-only statement returning the row count of every seeded and
    every must-be-empty table. Used per connection by tests/synthetic_db_guard.py.
    It never reads a table the tests write to (those may be locked)."""
    tables = sorted(fx.SYNTHETIC_SEED_TABLES) + empty_tables()
    columns = ",\n       ".join(f"(SELECT COUNT_BIG(*) FROM dbo.{t}) AS {t}" for t in tables)
    return f"SELECT {columns}"


def guard_expected_counts():
    expected = dict(fx.SYNTHETIC_MANIFEST)
    expected.update({t: 0 for t in empty_tables()})
    return expected


def foreign_row_checks():
    """Rows in test-writable tables that could not have been created by the
    tests on this fixture. Run by S4 only (before tests, no locks held)."""
    p, u, pat = fx.PROVIDER_ID, fx.USER_ID, fx.PATIENT_ID
    like = fx.TEST_DOCTOR_LICENSE_PREFIX + "%"
    return [
        ("doctors", f"provider_id <> '{p}' OR license_number IS NULL OR license_number NOT LIKE N'{like}'"),
        ("doctor_branches", f"provider_id <> '{p}'"),
        ("doctor_services", f"provider_id <> '{p}'"),
        ("doctor_availability_slots", f"provider_id <> '{p}'"),
        ("appointments", f"provider_id <> '{p}' OR patient_id <> '{pat}'"),
        ("appointment_status_history", f"provider_id <> '{p}'"),
        ("doctor_verification_decisions", f"provider_id <> '{p}' OR reviewer_user_id <> '{u}'"),
        ("staff_audit_logs", f"provider_id <> '{p}' OR user_id <> '{u}'"),
    ]


# ------------------------------------------------------------------ S2: schema


def build_schema_sql():
    dialect = sqlserver_dialect()
    metadata = schema_metadata()
    tables = sorted(metadata.tables.values(), key=lambda t: t.name)
    creates = [_clean(CreateTable(t, include_foreign_key_constraints=[]).compile(dialect=dialect)) + ";"
               for t in tables]
    indexes = [_clean(CreateIndex(i).compile(dialect=dialect)) + ";"
               for t in tables for i in sorted(t.indexes, key=lambda i: i.name)]
    foreign_keys = [_clean(AddConstraint(fk).compile(dialect=dialect)) + ";"
                    for t in tables
                    for fk in sorted(t.foreign_key_constraints,
                                     key=lambda f: (f.name or "", tuple(c.name for c in f.columns)))]
    body = "\n\n".join(creates + indexes + foreign_keys)
    if "IDENTITY" in body:
        raise SystemExit("unexpected IDENTITY column in the generated schema")
    return f"""/* =====================================================================
   S2 - SCHEMA of a synthetic concurrency database. GENERATED, do not edit:
   Backend/tools/generate_synthetic_sql.py (then re-pin in the runner).
   WRITE-CAPABLE: creates tables in the (empty) synthetic database only.
   Run ONLY through Invoke-SyntheticGate.ps1 -Gate S2 -SynthName ... -Approved.

   Compiled from the SQLAlchemy models ({len(tables)} tables + {ALEMBIC_TABLE}),
   SQL Server dialect, schema dbo. NOT claimed to match MedMind_Audit_Final2:
   database-only objects (triggers, named defaults, computed columns, views,
   procedures, extra indexes, different column types) are absent.
   Refuses unless: expected server; connected to exactly the named
   MedMind_SynthConc_* database; ONLINE, writable, not a snapshot, RCSI and
   snapshot isolation OFF; never a RESTORE target; NO user object exists yet.
   All DDL runs in one transaction: either the whole schema or nothing.
   Schema fingerprint (SHA-256, see generator): {schema_fingerprint()}
   ===================================================================== */
SET NOCOUNT ON;
SET XACT_ABORT ON;

{_in_synthetic_database_checks(52200)}
IF EXISTS (SELECT 1 FROM sys.objects WHERE is_ms_shipped = 0)
    THROW 52206, N'Refused: the database is not empty.', 1;

BEGIN TRANSACTION;

{body}

CREATE TABLE dbo.{ALEMBIC_TABLE} (
	version_num VARCHAR(32) NOT NULL,
	CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
INSERT INTO dbo.{ALEMBIC_TABLE} (version_num) VALUES ('{fx.EXPECTED_REVISION}');

COMMIT TRANSACTION;

SELECT DB_NAME() AS synthetic_database,
       (SELECT COUNT(*) FROM sys.tables WHERE is_ms_shipped = 0) AS user_tables,
       (SELECT version_num FROM dbo.{ALEMBIC_TABLE}) AS alembic_version;
"""


# ------------------------------------------------------------------ S3: seed


def _literal(column, value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, bytes):
        return "0x" + value.hex().upper()
    text = str(value).replace("'", "''")
    unicode = str(column.type.compile(dialect=sqlserver_dialect())).startswith(("NVARCHAR", "NCHAR"))
    return f"N'{text}'" if unicode else f"'{text}'"


def build_seed_sql():
    metadata = schema_metadata()
    inserts = []
    for table_name, row in fx.SYNTHETIC_ROWS:
        table = metadata.tables[f"dbo.{table_name}"]
        columns = list(row)
        values = ", ".join(_literal(table.c[c], row[c]) for c in columns)
        inserts.append(f"INSERT INTO dbo.{table_name} ({', '.join(columns)})\nVALUES ({values});")
    all_empty = "\n   OR ".join(f"EXISTS (SELECT 1 FROM dbo.{t})" for t in schema_tables() if t != ALEMBIC_TABLE)
    return f"""/* =====================================================================
   S3 - SEED of a synthetic concurrency database. GENERATED, do not edit:
   Backend/tools/generate_synthetic_sql.py (then re-pin in the runner).
   WRITE-CAPABLE: inserts the fake fixture rows and the synthetic marker.
   Run ONLY through Invoke-SyntheticGate.ps1 -Gate S3 -SynthName ...
   -TokenSha256 ... -Approved.

   Every value is fake (tests/synthetic_fixture.py): nothing is copied from
   any database; the staff password hash is a sentinel that never verifies.
   Refuses unless: the S2 checks pass; the schema fingerprint equals the
   generated one; the revision is {fx.EXPECTED_REVISION}; no marker exists; every table is
   still empty. Rows and marker are written in one transaction.
   Fixture {fx.FIXTURE_VERSION}, manifest SHA-256 {fx.MANIFEST_SHA256}
   ===================================================================== */
SET NOCOUNT ON;
SET XACT_ABORT ON;

{_in_synthetic_database_checks(52300)}
IF @token_sha256 IS NULL
   OR DATALENGTH(@token_sha256) <> 128
   OR @token_sha256 COLLATE Latin1_General_BIN LIKE N'%[^0-9a-f]%'
    THROW 52306, N'Refused: the token hash must be 64 lowercase hex characters.', 1;
{_fingerprint_check(52307)}
{_revision_check(52308)}
IF OBJECT_ID(N'dbo.{fx.MARKER_TABLE}', N'U') IS NOT NULL
    THROW 52309, N'Refused: the synthetic marker already exists.', 1;
IF {all_empty}
    THROW 52310, N'Refused: a table already holds rows; seeding needs the empty S2 schema.', 1;

BEGIN TRANSACTION;

{chr(10).join(inserts)}

CREATE TABLE dbo.{fx.MARKER_TABLE} (
	database_name sysname NOT NULL,
	marker_kind VARCHAR(20) NOT NULL,
	fixture_version VARCHAR(40) NOT NULL,
	token_sha256 CHAR(64) NOT NULL,
	manifest_sha256 CHAR(64) NOT NULL,
	created_at DATETIMEOFFSET NOT NULL CONSTRAINT DF_zz_synthetic_marker_created DEFAULT SYSDATETIMEOFFSET()
);
INSERT INTO dbo.{fx.MARKER_TABLE} (database_name, marker_kind, fixture_version, token_sha256, manifest_sha256)
VALUES (DB_NAME(), '{fx.MARKER_KIND}', '{fx.FIXTURE_VERSION}', @token_sha256, '{fx.MANIFEST_SHA256}');

COMMIT TRANSACTION;

SELECT database_name, marker_kind, fixture_version, manifest_sha256 FROM dbo.{fx.MARKER_TABLE};
"""


# ------------------------------------------------------------------ S4: verify (read-only)


def build_verify_sql():
    counts = []
    code = 52420
    for table, expected in sorted(guard_expected_counts().items()):
        counts.append(f"IF (SELECT COUNT_BIG(*) FROM dbo.{table}) <> {expected}\n"
                      f"    THROW {code}, N'Refused: dbo.{table} must hold exactly {expected} row(s).', 1;")
        code += 1
    foreign = []
    for table, predicate in foreign_row_checks():
        foreign.append(f"IF EXISTS (SELECT 1 FROM dbo.{table} WHERE {predicate})\n"
                       f"    THROW {code}, N'Refused: dbo.{table} holds a row the synthetic tests could not have created.', 1;")
        code += 1
    return f"""/* =====================================================================
   S4 - READ-ONLY proof that a database is exactly the synthetic one.
   GENERATED, do not edit: Backend/tools/generate_synthetic_sql.py.
   SELECT/IF/THROW only. Run ONLY through Invoke-SyntheticGate.ps1 -Gate S4
   -SynthName ... -TokenSha256 ...

   Refuses (THROW) unless: expected server; connected to exactly the named
   MedMind_SynthConc_* database; ONLINE, writable, not a snapshot, RCSI and
   snapshot isolation OFF; never a RESTORE target; exactly two files, at
   exactly the S1 paths; compatibility level {SYNTHETIC_COMPATIBILITY_LEVEL} and collation
   {SYNTHETIC_COLLATION} (as S1 sets them); the marker holds exactly
   one row for this database, kind {fx.MARKER_KIND}, fixture {fx.FIXTURE_VERSION}, this token and the
   manifest SHA-256 below; the revision is {fx.EXPECTED_REVISION}; the schema fingerprint
   matches; every seeded table holds exactly its fixture rows; every other
   non-test table is empty; test-written tables hold only rows the tests
   could have created on this fixture.
   Fixture manifest SHA-256 {fx.MANIFEST_SHA256}
   ===================================================================== */
SET NOCOUNT ON;

{_in_synthetic_database_checks(52400)}
{_file_path_check(52411)}
{_level_and_collation_check(52413)}
IF @token_sha256 IS NULL
   OR DATALENGTH(@token_sha256) <> 128
   OR @token_sha256 COLLATE Latin1_General_BIN LIKE N'%[^0-9a-f]%'
    THROW 52406, N'Refused: the token hash must be 64 lowercase hex characters.', 1;
IF OBJECT_ID(N'dbo.{fx.MARKER_TABLE}', N'U') IS NULL
    THROW 52407, N'Refused: no synthetic marker.', 1;
IF (SELECT COUNT(*) FROM dbo.{fx.MARKER_TABLE}) <> 1
   OR NOT EXISTS (SELECT 1 FROM dbo.{fx.MARKER_TABLE}
                  WHERE database_name COLLATE Latin1_General_BIN = DB_NAME() COLLATE Latin1_General_BIN
                    AND marker_kind = '{fx.MARKER_KIND}' AND fixture_version = '{fx.FIXTURE_VERSION}'
                    AND token_sha256 = @token_sha256 AND manifest_sha256 = '{fx.MANIFEST_SHA256}')
    THROW 52408, N'Refused: the synthetic marker does not match this database, token or fixture.', 1;
{_revision_check(52409)}
{_fingerprint_check(52410)}
{chr(10).join(counts)}
{chr(10).join(foreign)}

SELECT DB_NAME() AS synthetic_database, 'SYNTHETIC VERIFIED' AS result,
       (SELECT fixture_version FROM dbo.{fx.MARKER_TABLE}) AS fixture_version;
"""


# ------------------------------------------------------------------ CLI


def generated():
    return {
        "S2_schema.sql": build_schema_sql(),
        "S3_seed.sql": build_seed_sql(),
        "S4_verify_synthetic_readonly.sql": build_verify_sql(),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="compare with the pinned files (exit 1 on drift)")
    mode.add_argument("--write", action="store_true", help="rewrite the generated files")
    args = parser.parse_args(argv)
    if sqlalchemy.__version__ != SQLALCHEMY_VERSION:
        print(f"SQLAlchemy {sqlalchemy.__version__} is not the reviewed {SQLALCHEMY_VERSION}; refusing to generate or check")
        return 2
    drift = []
    for name, text in generated().items():
        data = text.encode("ascii")  # raises on any non-ASCII byte
        path = OUTPUT / name
        if args.write:
            path.write_bytes(data)
            print(f"wrote {name} {hashlib.sha256(data).hexdigest()}")
        elif not path.is_file() or path.read_bytes() != data:
            drift.append(name)
    if drift:
        print("out of date: " + ", ".join(drift))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
