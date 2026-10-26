"""
Offline tests of the scratch-database guard (tests/scratch_db_guard.py) and
static checks of the scratch SQL scripts (Database_latest/scratch_concurrency).
No database: engines are built from URLs but never connected, and
Engine.connect is patched to fail if anything tries.

The SQL checks are static text checks: they look for required statements
and their textual order (refusals before the DROP, etc.). They do not parse
or execute T-SQL, so they cannot prove syntax, runtime behavior or the
correctness of each condition; that needs a reviewed live run.
"""

import inspect
import re
from pathlib import Path
from urllib.parse import quote_plus

import pytest
import sqlalchemy
from _pytest.outcomes import Failed

import app.db.session as db_session_module
from app.core.config import get_settings
from tests import scratch_db_guard as guard

SCRATCH = "MedMind_ConcScratch_20261026_a1b2c3"
TOKEN = "0123456789abcdef" * 4
SCRIPTS = Path(__file__).resolve().parents[2] / "Database_latest" / "scratch_concurrency"
PROTECTED = ["MedMind_Booking_DB", "MedMind_Audit_Final2", "MedMind_Audit_Final"]


def _engine(database, extra=""):
    odbc = (
        "DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\\SQLEXPRESS;"
        f"DATABASE={database};Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes{extra}"
    )
    return sqlalchemy.create_engine("mssql+pyodbc:///?odbc_connect=" + quote_plus(odbc))


@pytest.fixture(autouse=True)
def no_connections(monkeypatch):
    attempts = []

    def refuse(self, *args, **kwargs):
        attempts.append(1)
        raise AssertionError("a database connection was attempted")

    monkeypatch.setattr(sqlalchemy.engine.Engine, "connect", refuse)
    yield attempts
    assert attempts == []
    get_settings.cache_clear()


# ============================================================ names


@pytest.mark.parametrize("name", [SCRATCH, "MedMind_ConcScratch_20991231_000000"])
def test_scratch_names_are_accepted(name):
    assert guard.scratch_name_problem(name) is None


@pytest.mark.parametrize(
    "name",
    PROTECTED + [
        "medmind_booking_db", "MEDMIND_BOOKING_DB", "medmind_audit_final2", " MedMind_Audit_Final2",
        "MedMind_Audit_Final2_RestoreTest", "MedMind_Audit_Scratch_20261026_a1b2c3",
        "MedMind_Booking_DB_ConcScratch_20261026_a1b2c3",
        "MedMind_ConcScratch_20261026_A1B2C3",          # uppercase hex
        "MedMind_ConcScratch_2026102_a1b2c3",           # 7 digits
        "MedMind_ConcScratch_20261026_a1b2c3_x",        # suffix
        "MedMind_ConcScratch_20261026_a1b2c3 ",         # trailing space
        "MedMind_ConcScratch_٢٠٢٦١٠٢٦_a1b2c3",  # non-ASCII digits
        "MedMind_ConcScratch_20261026_a1b2c3;DATABASE=MedMind_Booking_DB",
        "", None,
    ],
)
def test_protected_and_malformed_names_are_refused(name):
    assert guard.scratch_name_problem(name) is not None


def test_logical_file_names_are_never_consulted():
    # The copy keeps the logical names MedMind_Booking_DB / _log: they must
    # neither allow nor block anything. Only database names and the marker do.
    for function in (guard.scratch_name_problem, guard.scratch_engine_problem, guard.connected_problem,
                     guard.require_scratch_target, guard._verify_connected, guard.scratch_connection):
        code = inspect.getsource(function)
        for term in ("master_files", "database_files", "logical", "physical_name"):
            assert term not in code, (function.__name__, term)


# ============================================================ engine URL


def test_the_scratch_engine_is_accepted():
    assert guard.scratch_engine_problem(_engine(SCRATCH), SCRATCH) is None


@pytest.mark.parametrize("database", PROTECTED + ["MedMind_ConcScratch_20261026_ffffff"])
def test_engines_for_other_databases_are_refused(database):
    assert guard.scratch_engine_problem(_engine(database), SCRATCH) is not None


@pytest.mark.parametrize("extra", [";UID=someone", ";DATABASE=MedMind_Booking_DB", ";Initial Catalog=MedMind_Audit_Final2"])
def test_redirecting_odbc_keys_are_refused(extra):
    assert guard.scratch_engine_problem(_engine(SCRATCH, extra), SCRATCH) is not None


# ============================================================ require_scratch_target


@pytest.fixture
def scratch_env(monkeypatch):
    values = {
        "APP_ENV": "staging", "MEDMIND_DB_INTEGRATION": "1", "MEDMIND_SCRATCH_CONCURRENCY": "1",
        "MEDMIND_SCRATCH_DB_NAME": SCRATCH, "MEDMIND_SCRATCH_TOKEN": TOKEN,
        "DB_SERVER": "localhost\\SQLEXPRESS", "DB_NAME": SCRATCH, "DB_TRUSTED_CONNECTION": "true",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(db_session_module, "engine", _engine(SCRATCH))
    get_settings.cache_clear()
    return monkeypatch


def test_the_exact_scratch_target_passes_without_connecting(scratch_env):
    engine, name, token_hash = guard.require_scratch_target()
    assert name == SCRATCH and token_hash == guard.token_sha256(TOKEN)


@pytest.mark.parametrize(
    "change",
    [
        {"MEDMIND_SCRATCH_CONCURRENCY": None},
        {"MEDMIND_DB_INTEGRATION": None},
        {"APP_ENV": None},
        {"MEDMIND_SCRATCH_DB_NAME": "MedMind_Audit_Final2", "DB_NAME": "MedMind_Audit_Final2"},
        {"MEDMIND_SCRATCH_DB_NAME": "MedMind_Booking_DB", "DB_NAME": "MedMind_Booking_DB"},
        {"MEDMIND_SCRATCH_DB_NAME": "MedMind_Audit_Final", "DB_NAME": "MedMind_Audit_Final"},
        {"DB_NAME": "MedMind_Audit_Final2"},
        {"DB_SERVER": "otherhost"},
        {"DB_TRUSTED_CONNECTION": "false"},
        {"MEDMIND_SCRATCH_TOKEN": "short"},
        {"MEDMIND_SCRATCH_TOKEN": TOKEN.upper()},
    ],
)
def test_any_wrong_setting_fails_closed_before_connecting(scratch_env, change):
    for key, value in change.items():
        if value is None:
            scratch_env.delenv(key, raising=False)
        else:
            scratch_env.setenv(key, value)
    get_settings.cache_clear()
    with pytest.raises(Failed, match="SCRATCH SAFETY STOP"):
        guard.require_scratch_target()


@pytest.mark.parametrize("database", PROTECTED)
def test_a_stale_engine_for_a_protected_database_fails_closed(scratch_env, database):
    scratch_env.setattr(db_session_module, "engine", _engine(database))
    with pytest.raises(Failed, match="SCRATCH SAFETY STOP"):
        guard.require_scratch_target()


# ============================================================ after connecting


GOOD = dict(db_name=SCRATCH, database_row=(False, None), marker_exists=True,
            marker_rows=[(SCRATCH, "MedMind_Audit_Final2", guard.token_sha256(TOKEN))],
            revision="c3d9e6a2f8b1", name=SCRATCH, token_hash=guard.token_sha256(TOKEN))


def test_the_prepared_scratch_copy_passes():
    assert guard.connected_problem(**GOOD) is None


@pytest.mark.parametrize(
    "change",
    [
        {"db_name": "MedMind_Audit_Final2"},
        {"db_name": "MedMind_Booking_DB"},
        {"database_row": None},
        {"database_row": (True, None)},
        {"database_row": (False, 7)},
        {"marker_exists": False, "marker_rows": []},
        {"marker_rows": []},
        {"marker_rows": GOOD["marker_rows"] * 2},
        {"marker_rows": [("MedMind_ConcScratch_20261026_ffffff", "MedMind_Audit_Final2", GOOD["token_hash"])]},
        {"marker_rows": [(SCRATCH, "MedMind_Booking_DB", GOOD["token_hash"])]},
        {"marker_rows": [(SCRATCH, "MedMind_Audit_Final2", "0" * 64)]},
        {"revision": "a8c2e5f1b7d4"},
    ],
)
def test_any_mismatch_after_connecting_is_refused(change):
    assert guard.connected_problem(**{**GOOD, **change}) is not None


# ============================================================ scratch SQL scripts (static)


def _script(name):
    return (SCRIPTS / name).read_text(encoding="utf-8")


WRITE_SCRIPTS = ["G3_backup_copy_only.sql", "G4_restore_scratch.sql", "G5_create_marker.sql",
                 "G7_drop_scratch.sql", "R2_drop_unmarked_scratch.sql"]
READ_ONLY_SCRIPTS = ["G3b_backup_header_readonly.sql", "G4b_verify_scratch_readonly.sql", "fingerprint_readonly.sql",
                     "R1_recovery_inspect_readonly.sql"]
SCRATCH_PARAMETER_SCRIPTS = [name for name in WRITE_SCRIPTS + READ_ONLY_SCRIPTS if name != "fingerprint_readonly.sql"]
PATTERN = ("N'MedMind[_]ConcScratch[_][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]"
           "[_][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'")


@pytest.mark.parametrize("name", WRITE_SCRIPTS + READ_ONLY_SCRIPTS)
def test_every_script_checks_the_exact_scratch_pattern(name):
    assert PATTERN in _script(name)


def test_every_sql_file_is_covered_by_these_checks():
    assert {path.name for path in SCRIPTS.glob("*.sql")} == set(WRITE_SCRIPTS + READ_ONLY_SCRIPTS)


@pytest.mark.parametrize("name", WRITE_SCRIPTS + READ_ONLY_SCRIPTS)
def test_no_script_uses_sqlcmd_variables_or_batch_separators(name):
    # Values arrive only as bound parameters through Invoke-ScratchGate.ps1.
    sql = _script(name)
    assert "$(" not in sql
    assert not re.search(r"(?im)^\s*(GO|:setvar|:r)\b", sql)


@pytest.mark.parametrize("name", WRITE_SCRIPTS + READ_ONLY_SCRIPTS)
def test_every_script_checks_the_server_first(name):
    code = _code(_script(name))
    assert "IF @@SERVERNAME <> N'LAPTOP-FACHLL1N\\SQLEXPRESS'" in code
    first_throw = re.search(r"THROW \d+", code).start()
    assert code.index("@@SERVERNAME") < first_throw


@pytest.mark.parametrize("name", SCRATCH_PARAMETER_SCRIPTS)
def test_scratch_name_parameter_rejects_null_and_wrong_length(name):
    code = _code(_script(name))
    assert "@scratch_name IS NULL" in code and "DATALENGTH(@scratch_name) <> 70" in code
    assert "$(SCRATCH_NAME)" not in _script(name)


@pytest.mark.parametrize("name", ["G5_create_marker.sql", "G7_drop_scratch.sql"])
def test_token_hash_parameter_rejects_null_and_wrong_length(name):
    code = _code(_script(name))
    assert "@token_sha256 IS NULL" in code and "DATALENGTH(@token_sha256) <> 128" in code


@pytest.mark.parametrize("name", ["G5_create_marker.sql", "G4b_verify_scratch_readonly.sql"])
def test_the_revision_check_cannot_pass_on_an_empty_table(name):
    code = _code(_script(name))
    assert "(SELECT COUNT(*) FROM dbo.alembic_version) <> 1" in code
    assert "NOT EXISTS (SELECT 1 FROM dbo.alembic_version WHERE version_num = 'c3d9e6a2f8b1')" in code


def test_r2_places_every_identity_refusal_before_the_drop():
    sql = _code(_script("R2_drop_unmarked_scratch.sql"))
    drop = sql.index("N'DROP DATABASE '")
    for refusal in ("THROW 51200", "THROW 51201", "THROW 51202", "THROW 51203", "THROW 51204", "THROW 51206",
                    "THROW 51207", "THROW 51208", "THROW 51209", "THROW 51210", "THROW 51211", "THROW 51212",
                    "THROW 51214"):
        assert sql.index(refusal) < drop, refusal
    assert "IF @state IS NULL OR @state NOT IN" in sql
    assert sql.count("DROP DATABASE") == 1
    assert "@scratch + N'_data.mdf'" in sql and "@scratch + N'_log.ldf'" in sql
    assert "msdb.dbo.restorehistory" in sql and "@restored_from <> @file" in sql
    assert "N'OFFLINE'" not in sql  # an OFFLINE database is refused, never dropped
    assert "N'DROP DATABASE ' + QUOTENAME(@scratch)" in sql


def test_r2_refuses_an_online_copy_whose_marker_cannot_be_read():
    sql = _code(_script("R2_drop_unmarked_scratch.sql"))
    # OBJECT_ID() returns NULL for a database it cannot open; it must not
    # decide whether a marker exists.
    assert "OBJECT_ID(" not in sql
    order = ["IF @state = N'ONLINE'", "BEGIN TRY", "EXEC sys.sp_executesql @probe", "BEGIN CATCH",
             "ERROR_NUMBER()", "END CATCH", "IF @probe_error IS NOT NULL", "THROW 51214, @probe_error",
             "IF @marker_tables IS NULL", "THROW 51214, N'", "IF @marker_tables <> 0", "THROW 51212",
             "N'DROP DATABASE '"]
    positions = [sql.index(marker) for marker in order]
    assert positions == sorted(positions), list(zip(order, positions))
    assert "QUOTENAME(@scratch) + N'.sys.tables WHERE name = N''zz_scratch_marker'''" in sql


def test_r1_never_recommends_r2_when_the_marker_status_is_unknown():
    sql = _code(_script("R1_recovery_inspect_readonly.sql"))
    assert "OBJECT_ID(" not in sql
    assert "R2 applies" not in sql
    assert sql.count("R2 may be considered") == 1
    recommend = sql.index("'R2 may be considered")
    branch = sql.rindex("WHEN", 0, recommend)
    assert sql[branch:recommend].split() == (
        "WHEN @state = N'ONLINE' AND @probe_error IS NULL AND @marker_tables = 0 THEN".split())
    assert "'no recommendation: manual review (README, recovery)'" in sql
    assert "'UNKNOWN (not online; the marker cannot be read)'" in sql
    assert "'UNKNOWN (the marker probe failed)'" in sql


def test_g7_refuses_an_unreadable_marker_and_keeps_the_original_error():
    sql = _code(_script("G7_drop_scratch.sql"))
    order = ["BEGIN TRY", "BEGIN CATCH", "ERROR_NUMBER()", "ERROR_MESSAGE()", "END CATCH",
             "IF @probe_error IS NOT NULL", "THROW 50710, @probe_error", "THROW 50708", "N'DROP DATABASE '"]
    positions = [sql.index(marker) for marker in order]
    assert positions == sorted(positions), list(zip(order, positions))
    # 50708 now only means "readable, but not exactly one matching row".
    assert "missing, unreadable" not in sql


@pytest.mark.parametrize("name", ["G3_backup_copy_only.sql", "G3b_backup_header_readonly.sql", "G4_restore_scratch.sql",
                                  "G7_drop_scratch.sql", "R1_recovery_inspect_readonly.sql",
                                  "R2_drop_unmarked_scratch.sql"])
def test_destructive_scripts_deny_every_protected_name(name):
    sql = _script(name)
    assert "N'medmind_booking_db', N'medmind_audit_final2', N'medmind_audit_final'" in sql
    assert "LIKE N'medmind[_]audit%'" in sql and "LIKE N'medmind[_]booking%'" in sql


@pytest.mark.parametrize("name", WRITE_SCRIPTS + READ_ONLY_SCRIPTS)
def test_no_script_names_a_protected_database_as_a_target(name):
    sql = _code(_script(name))
    for forbidden in (r"USE\s+\[?MedMind_Booking_DB", r"DATABASE\s+\[?MedMind_Booking_DB",
                      r"DROP\s+DATABASE\s+\[?MedMind", r"RESTORE\s+DATABASE\s+\[?MedMind"):
        assert not re.search(forbidden, sql, re.IGNORECASE), forbidden


def _code(sql, keep_strings=True):
    """SQL without /* */ and -- comments (a small tokenizer, so "--" or "/*"
    inside a string literal is kept). With keep_strings=False, string
    literals are replaced by ''."""
    out, i, n = [], 0, len(sql)
    while i < n:
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
        elif sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end == -1 else end
        elif sql[i] == "'" or (sql[i] in "Nn" and sql.startswith("'", i + 1)
                                and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_"))):
            start = i
            i += 2 if sql[i] in "Nn" else 1
            while i < n:
                if sql[i] == "'" and sql.startswith("''", i):
                    i += 2
                elif sql[i] == "'":
                    i += 1
                    break
                else:
                    i += 1
            out.append(sql[start:i] if keep_strings else "''")
        else:
            out.append(sql[i])
            i += 1
    return "".join(out)


@pytest.mark.parametrize("name", READ_ONLY_SCRIPTS)
def test_read_only_scripts_contain_no_writes(name):
    # String literals (labels such as N'backup') are not statements. The only
    # allowed RESTOREs are the header/label reads of the G3 file (below).
    sql = (_code(_script(name), keep_strings=False)
           .replace("RESTORE HEADERONLY FROM DISK = @file;", "")
           .replace("RESTORE LABELONLY FROM DISK = @file;", ""))
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|BACKUP|RESTORE|TRUNCATE|DBCC)\b",
                         sql, re.IGNORECASE)


def test_the_backup_header_check_only_reads_the_g3_file():
    sql = _code(_script("G3b_backup_header_readonly.sql"))
    # Exactly three result sets, in the order Get-BackupHeaderVerdict expects.
    assert re.findall(r"\bRESTORE\b[^;]*;", sql, re.IGNORECASE) == [
        "RESTORE HEADERONLY FROM DISK = @file;", "RESTORE LABELONLY FROM DISK = @file;"]
    assert len(re.findall(r"^SELECT\b", sql, re.MULTILINE)) == 1
    msdb = sql.index("SELECT bs.backup_set_uuid")
    assert msdb < sql.index("RESTORE HEADERONLY") < sql.index("RESTORE LABELONLY")
    assert "DECLARE @file nvarchar(400) = @dir + @scratch + N'.bak';" in sql
    assert sql.index("THROW 51305") < msdb
    # Every msdb record for the path is returned (no TOP), so a duplicate fails the verdict.
    select = sql[msdb:sql.index("RESTORE HEADERONLY")]
    assert "TOP" not in select and "WHERE bmf.physical_device_name = @file;" in select
    for column in ("bs.backup_set_uuid", "bs.database_name", "bs.type AS backup_type", "bs.is_copy_only",
                   "bs.has_backup_checksums", "bs.server_name", "bms.name AS media_name"):
        assert column in select, column


def test_g3_names_the_media_set_after_the_scratch_name():
    sql = _code(_script("G3_backup_copy_only.sql"))
    assert ("BACKUP DATABASE [MedMind_Audit_Final2] TO DISK = @file "
            "WITH COPY_ONLY, CHECKSUM, FORMAT, INIT, MEDIANAME = @scratch, STATS = 25;") in sql
    # FORMAT can only ever apply to a file that did not exist.
    assert sql.index("THROW 50307") < sql.index("BACKUP DATABASE")


def test_g4_is_bound_to_the_approved_backup_set():
    sql = _code(_script("G4_restore_scratch.sql"))
    restore = sql.index("RESTORE DATABASE @scratch")
    for refusal in ("THROW 50413", "THROW 50414"):
        assert sql.index(refusal) < restore, refusal
    assert "DATALENGTH(@backup_set_guid) <> 72" in sql
    assert ("LOWER(CONVERT(nchar(36), @approved_set)) COLLATE Latin1_General_BIN "
            "<> @backup_set_guid COLLATE Latin1_General_BIN") in sql
    assert "bs.backup_set_uuid = @approved_set" in sql[:restore]
    assert "WITH MEDIANAME = @scratch," in sql[restore:restore + 80]
    after = sql[restore:]
    assert "ORDER BY rh.restore_history_id DESC" in after
    assert "IF @restored_set IS NULL OR @restored_set <> @approved_set" in after
    assert after.index("@restored_set <> @approved_set") < after.index("THROW 50415")


def test_the_backup_is_copy_only_and_checksummed_from_final2_only():
    sql = _code(_script("G3_backup_copy_only.sql"))
    assert "BACKUP DATABASE [MedMind_Audit_Final2] TO DISK = @file WITH COPY_ONLY, CHECKSUM" in sql
    assert sql.count("BACKUP DATABASE") == 1
    assert sql.index("THROW 50307") < sql.index("BACKUP DATABASE")


def test_the_restore_never_overwrites_and_maps_both_logical_files():
    sql = _code(_script("G4_restore_scratch.sql"))
    restore = sql.index("RESTORE DATABASE @scratch")
    for refusal in ("THROW 50404", "THROW 50407", "THROW 50408", "THROW 50409"):
        assert sql.index(refusal) < restore, refusal
    assert "MOVE @data_logical TO @data_file" in sql and "MOVE @log_logical TO @log_file" in sql
    assert "@data_logical sysname = N'MedMind_Booking_DB'" in sql
    assert "@log_logical sysname = N'MedMind_Booking_DB_log'" in sql
    assert "@scratch + N'_data.mdf'" in sql and "@scratch + N'_log.ldf'" in sql
    assert not re.search(r"\bREPLACE\b\s*(,|$)", sql[restore:], re.IGNORECASE | re.MULTILINE)


def test_the_drop_checks_the_marker_and_confirmation_before_dropping():
    sql = _code(_script("G7_drop_scratch.sql"))
    drop = sql.index("DROP DATABASE")
    for refusal in ("THROW 50701", "THROW 50702", "THROW 50703", "THROW 50704", "THROW 50706", "THROW 50708",
                    "THROW 50710"):
        assert sql.index(refusal) < drop, refusal
    assert sql.count("DROP DATABASE") == 1
    assert "N'DROP DATABASE ' + QUOTENAME(@scratch)" in sql
    assert "zz_scratch_marker" in sql[:drop]


def test_the_marker_stores_only_the_token_hash():
    sql = _code(_script("G5_create_marker.sql"))
    assert "token_sha256 char(64)" in sql and "VALUES (DB_NAME(), N'MedMind_Audit_Final2', @token_sha256)" in sql


# ============================================================ masking inventory vs the models (static)
# These read the model source files only. They say nothing about the live
# database (schema drift is explicitly out of scope of MASKING_PROPOSAL.md).


def _model_columns():
    import ast

    columns = {}
    for path in (SCRIPTS.parents[1] / "Backend" / "app" / "models").glob("*.py"):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if not isinstance(node, ast.ClassDef):
                continue
            table = next((s.value.value for s in node.body if isinstance(s, ast.Assign)
                          and getattr(s.targets[0], "id", "") == "__tablename__"), None)
            if table:
                columns[table] = {s.target.id for s in node.body if isinstance(s, ast.AnnAssign)
                                  and isinstance(s.value, ast.Call) and getattr(s.value.func, "id", "") == "mapped_column"}
    return columns


def _inventory():
    text = _script("MASKING_PROPOSAL.md")
    section = text[text.index("## C."):text.index("## D.")]
    named = set()
    for line in section.splitlines():
        if line.startswith("| `"):
            items = re.findall(r"`([a-z_0-9.]+)`", line.split("|")[1])
            table = items[0].split(".")[0]
            named.add((table, None))
            named.update((table, item.split(".", 1)[-1]) for item in items if item != table)
    unlisted = set(re.findall(r"`([a-z_]+)`", section[section.index("Tables with no personal"):]))
    return text, named, unlisted


def test_every_column_named_in_the_masking_inventory_exists_in_the_models():
    columns = _model_columns()
    _, named, _ = _inventory()
    unknown = sorted(f"{t}.{c}" for t, c in named if c is not None and c not in columns.get(t, set()))
    assert unknown == []
    assert len([c for _, c in named if c]) >= 100


def test_every_model_table_is_inventoried_or_listed_as_non_personal():
    columns = _model_columns()
    _, named, unlisted = _inventory()
    inventoried = {t for t, _ in named}
    assert set(columns) - inventoried - unlisted == set()
    assert inventoried & unlisted == set()  # never both "sensitive" and "no personal content"


def test_the_inventory_does_not_claim_completeness_and_names_date_quasi_identifiers():
    text, named, _ = _inventory()
    assert "## C. Inventory (sensitive columns identified in the models)" in text
    assert "every sensitive column in the models" not in text
    assert "It does not prove that it lists\nevery sensitive column" in text
    for table, column in [("appointments", "scheduled_date"), ("appointments", "start_time"),
                          ("appointments", "end_time"), ("reminders", "scheduled_for"), ("reminders", "sent_at"),
                          ("reminders", "delivered_at"), ("reminders", "response_at"),
                          ("doctor_schedule_exceptions", "exception_date"),
                          ("doctor_schedule_exceptions", "exception_type"),
                          ("appointment_status_history", "changed_at"), ("clinical_notes", "signed_at"),
                          ("patient_access_grants", "granted_at"), ("doctor_availability_slots", "slot_date")]:
        assert (table, column) in named, f"{table}.{column}"
    assert "created_at`/`updated_at" in text
