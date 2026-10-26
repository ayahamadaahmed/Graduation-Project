"""
Offline tests of the SYNTHETIC concurrency database workflow:
the generator (Backend/tools/generate_synthetic_sql.py), the pinned SQL in
Database_latest/synthetic_concurrency, the fake fixture
(tests/synthetic_fixture.py) and the synthetic guard (tests/synthetic_db_guard.py).

No database: nothing here creates a connection. Engines are built from URLs
only, and Engine.connect is patched to fail if anything tries. The SQL is
checked as text (statement presence and order); it is never executed, so
these tests do not prove SQL Server runtime behavior.
"""

import hashlib
import re
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote_plus

import pytest
import sqlalchemy
from _pytest.outcomes import Failed
from sqlalchemy import CheckConstraint

import app.db.session as db_session_module
import app.models  # noqa: F401
from app.core.config import get_settings
from app.db.base import Base
from tests import synthetic_db_guard as guard
from tests import synthetic_fixture as fx
from tools import generate_synthetic_sql as generator

ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC = ROOT / "Database_latest" / "synthetic_concurrency"
SCRATCH = ROOT / "Database_latest" / "scratch_concurrency"
NAME = "MedMind_SynthConc_20261026_a1b2c3"
TOKEN = "0123456789abcdef" * 4
PROTECTED = ["MedMind_Booking_DB", "MedMind_Audit_Final2", "MedMind_Audit_Final"]
SCRIPTS = ["S0_instance_readonly.sql", "S1_create_synthetic_db.sql", "S2_schema.sql", "S3_seed.sql",
           "S4_verify_synthetic_readonly.sql", "S6_drop_synthetic_db.sql"]


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


def _script(name):
    return (SYNTHETIC / name).read_text(encoding="ascii")


def _code(sql, keep_strings=True):
    """SQL without comments; string literals optionally blanked."""
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
                if sql.startswith("''", i):
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


# ============================================================ generator: determinism and pins


def test_generation_is_deterministic():
    assert generator.generated() == generator.generated()
    assert generator.schema_fingerprint() == generator.schema_fingerprint()


def test_the_generated_files_are_exactly_the_pinned_bytes():
    for name, text in generator.generated().items():
        assert (SYNTHETIC / name).read_bytes() == text.encode("ascii"), name
    assert generator.main(["--check"]) == 0


@pytest.mark.parametrize("hash_seed", ["0", "1", "12345"])
def test_generation_is_byte_identical_in_fresh_processes(hash_seed):
    # Set/dict iteration and object identities differ between processes; the
    # output must not. Runs the generator's own --check (pure Python, offline).
    import os
    import subprocess
    import sys

    env = {key: value for key, value in os.environ.items() if not key.upper().startswith(("MEDMIND_", "DB_"))}
    env["PYTHONHASHSEED"] = hash_seed
    proc = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "Backend" / "tools" / "generate_synthetic_sql.py"),
                           "--check"], capture_output=True, text=True, env=env, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_synthetic_runner_pins_every_script_exactly():
    runner = (SYNTHETIC / "Invoke-SyntheticGate.ps1").read_text(encoding="ascii")
    pins = dict(re.findall(r"'([\w.]+\.sql)'\s*=\s*'([0-9a-f]{64})'", runner))
    assert set(pins) == {p.name for p in SYNTHETIC.glob("*.sql")} == set(SCRIPTS)
    for name, digest in pins.items():
        assert hashlib.sha256((SYNTHETIC / name).read_bytes()).hexdigest() == digest, name


def test_the_readme_records_the_synthetic_runner_hash():
    digest = hashlib.sha256((SYNTHETIC / "Invoke-SyntheticGate.ps1").read_bytes()).hexdigest()
    readme = (SYNTHETIC / "README.md").read_text(encoding="utf-8")
    assert re.findall(r"Invoke-SyntheticGate\.ps1\s+SHA-256\s+([0-9a-f]{64})", readme) == [digest]


def test_synthetic_files_are_lf_only_ascii():
    for path in SYNTHETIC.iterdir():
        data = path.read_bytes()
        assert b"\r" not in data and all(byte < 128 for byte in data), path.name


def test_the_restored_scratch_runner_and_its_pins_are_unchanged():
    runner = SCRATCH / "Invoke-ScratchGate.ps1"
    assert hashlib.sha256(runner.read_bytes()).hexdigest() == (
        "f9466ca17101b3377ac1694ec55a949036fe98bf56fbb834571307551afc9078")
    pins = dict(re.findall(r"'([\w.]+\.sql)'\s*=\s*'([0-9a-f]{64})'", runner.read_text(encoding="ascii")))
    assert set(pins) == {p.name for p in SCRATCH.glob("*.sql")} and len(pins) == 9
    for name, digest in pins.items():
        assert hashlib.sha256((SCRATCH / name).read_bytes()).hexdigest() == digest, name


def test_the_generator_imports_no_settings_engine_or_dotenv():
    source = (ROOT / "Backend" / "tools" / "generate_synthetic_sql.py").read_text(encoding="utf-8")
    for forbidden in ("app.core", "app.db.session", "create_engine", "dotenv", "get_settings", ".connect("):
        assert forbidden not in source, forbidden


# ============================================================ S2: schema


S2 = _script("S2_schema.sql")
S2_CODE = _code(S2)


def test_every_model_table_is_created_in_dbo_and_nothing_else():
    created = re.findall(r"^CREATE TABLE (\S+) \($", S2_CODE, re.MULTILINE)
    expected = sorted(f"dbo.{t}" for t in Base.metadata.tables) + ["dbo.alembic_version"]
    assert sorted(created) == sorted(expected) and len(created) == len(Base.metadata.tables) + 1


def test_every_model_foreign_key_and_check_constraint_is_emitted():
    model_fks = [fk for t in Base.metadata.tables.values() for fk in t.foreign_key_constraints]
    assert len(re.findall(r"^ALTER TABLE dbo\.\w+ ADD (?:CONSTRAINT \S+ )?FOREIGN KEY", S2_CODE, re.MULTILINE)) \
        == len(model_fks)
    for table in Base.metadata.tables.values():
        for check in (c for c in table.constraints if isinstance(c, CheckConstraint)):
            assert re.search(rf"CONSTRAINT \[?{re.escape(check.name)}\]? CHECK \(", S2_CODE), check.name


def test_the_indexes_the_concurrency_code_relies_on_are_present():
    for index in (
        "CREATE UNIQUE INDEX [UX_appointments_active_slot] ON dbo.appointments (slot_id) WHERE status<>'cancelled';",
        "CREATE UNIQUE INDEX [UX_availability_slots_doctor_date_time] ON dbo.doctor_availability_slots "
        "(doctor_id, slot_date, start_time) WHERE doctor_id IS NOT NULL;",
        "CREATE UNIQUE INDEX [UX_branches_provider_mrn_code] ON dbo.branches (provider_id, mrn_code) "
        "WHERE mrn_code IS NOT NULL;",
    ):
        assert index in S2_CODE, index
    model_indexes = sum(len(t.indexes) for t in Base.metadata.tables.values())
    assert len(re.findall(r"^CREATE (?:UNIQUE )?INDEX ", S2_CODE, re.MULTILINE)) == model_indexes


def test_sql_server_types_are_modern_and_identity_is_never_emitted():
    assert "IDENTITY" not in S2_CODE and "NTEXT" not in S2_CODE
    assert "\tslot_date DATE NOT NULL," in S2_CODE and "\tstart_time TIME NOT NULL," in S2_CODE
    assert "\tscheduled_date DATE NOT NULL," in S2_CODE
    assert "\tyear INTEGER NOT NULL," in S2_CODE  # patient_number_sequences: no IDENTITY (NO_IDENTITY)
    assert not re.search(r"(?:REFERENCES|ON|TABLE) (?!dbo\.)[a-z_]+\b", S2_CODE)


def test_s2_refuses_before_any_ddl_and_is_all_or_nothing():
    begin = S2_CODE.index("BEGIN TRANSACTION;")
    first_ddl = S2_CODE.index("CREATE TABLE ")
    assert begin < first_ddl and S2_CODE.rstrip().count("COMMIT TRANSACTION;") == 1
    for refusal in ("THROW 52200", "THROW 52201", "THROW 52202", "THROW 52203", "THROW 52204", "THROW 52205",
                    "THROW 52206"):
        assert S2_CODE.index(refusal) < begin, refusal
    assert "IF EXISTS (SELECT 1 FROM sys.objects WHERE is_ms_shipped = 0)" in S2_CODE[:begin]
    assert f"INSERT INTO dbo.alembic_version (version_num) VALUES ('{fx.EXPECTED_REVISION}');" in S2_CODE


# ============================================================ the code paths under test vs the schema


def _not_null_without_default(table):
    return {c.name for c in table.columns
            if not c.nullable and c.server_default is None and not (c.primary_key and c.server_default)}


def test_raw_sql_on_the_booking_path_names_only_generated_tables():
    sources = [ROOT / "Backend" / "app" / "repositories" / name for name in
               ("appointment_repository.py", "patient_branch_profile_repository.py", "patient_repository.py")]
    sources.append(ROOT / "Backend" / "tests" / "test_reschedule_concurrency_scratch_db.py")
    tables = set(generator.schema_tables())
    for path in sources:
        for table in re.findall(r"\bdbo\.([a-z_]+)\b", path.read_text(encoding="utf-8")):
            assert table in tables, (path.name, table)


def test_every_raw_insert_on_the_path_supplies_the_columns_the_schema_requires():
    sources = [ROOT / "Backend" / "app" / "repositories" / "appointment_repository.py",
               ROOT / "Backend" / "tests" / "test_reschedule_concurrency_scratch_db.py"]
    seen = 0
    for path in sources:
        text = path.read_text(encoding="utf-8").replace('"\n', "").replace('\n                     "', "")
        flat = re.sub(r'"\s*\n\s*"', "", text)
        for table, columns in re.findall(r"INSERT INTO dbo\.([a-z_]+)\s*\(([^)]*)\)", flat):
            given = {c.strip() for c in columns.replace('"', "").split(",") if c.strip()}
            model = Base.metadata.tables[table]
            assert given <= {c.name for c in model.columns}, (path.name, table, given - {c.name for c in model.columns})
            missing = _not_null_without_default(model) - given
            assert not missing, (path.name, table, missing)
            seen += 1
    assert seen >= 6  # 3 repository inserts on the path + 4 fixture inserts in the test


# ============================================================ fixture


METADATA = generator.schema_metadata()


def _model(table):
    return METADATA.tables[f"dbo.{table}"]


def test_fixture_rows_use_real_columns_fit_their_types_and_fill_required_columns():
    for table, row in fx.SYNTHETIC_ROWS:
        model = _model(table)
        assert set(row) <= {c.name for c in model.columns}, (table, set(row) - {c.name for c in model.columns})
        assert not (_not_null_without_default(model) - set(row)), (table, _not_null_without_default(model) - set(row))
        for column, value in row.items():
            length = getattr(model.c[column].type, "length", None)
            if isinstance(value, str) and length:
                assert len(value) <= length, (table, column)
            if isinstance(value, str):
                assert value.isascii(), (table, column)


def test_fixture_foreign_keys_resolve_inside_the_fixture():
    ids = {(table, row["id"]) for table, row in fx.SYNTHETIC_ROWS}
    for table, row in fx.SYNTHETIC_ROWS:
        for fk in _model(table).foreign_keys:
            value = row.get(fk.parent.name)
            if value is not None:
                assert fk.column.name == "id" and (fk.column.table.name, value) in ids, (table, fk.parent.name)


FIXTURE_CHECKS = {
    ("providers", "CK_providers_default_language"):
        ("default_language='en' OR default_language='ar'", lambda r: r.get("default_language") in ("en", "ar")),
    ("providers", "CK_providers_org_type"):
        ("org_type='pharmacy' OR org_type='diagnostic_lab' OR org_type='hospital' OR org_type='clinic'",
         lambda r: r.get("org_type") in ("pharmacy", "diagnostic_lab", "hospital", "clinic")),
    ("providers", "CK_providers_verification_status"):
        ("verification_status='rejected' OR verification_status='pending' OR verification_status='verified'",
         lambda r: r.get("verification_status") in ("rejected", "pending", "verified")),
    ("branches", "CK_branches_latitude"):
        ("latitude>=(-90) AND latitude<=(90) OR latitude IS NULL",
         lambda r: r.get("latitude") is None or -90 <= r["latitude"] <= 90),
    ("branches", "CK_branches_longitude"):
        ("longitude>=(-180) AND longitude<=(180) OR longitude IS NULL",
         lambda r: r.get("longitude") is None or -180 <= r["longitude"] <= 180),
    ("services", "CK_services_duration_minutes"):
        ("duration_minutes>(0)", lambda r: r["duration_minutes"] > 0),
    ("services", "CK_services_price"):
        ("price IS NULL OR price>=(0)", lambda r: r.get("price") is None or r["price"] >= 0),
    ("services", "CK_services_service_type"):
        ("service_type='surgery' OR service_type='procedure' OR service_type='diagnostic' OR "
         "service_type='follow_up' OR service_type='teleconsultation' OR service_type='consultation'",
         lambda r: r.get("service_type") in ("surgery", "procedure", "diagnostic", "follow_up", "teleconsultation",
                                             "consultation")),
    ("services", "ck_services_voice_featured_rank_positive"):
        ("voice_featured_rank IS NULL OR voice_featured_rank>(0)",
         lambda r: r.get("voice_featured_rank") is None or r["voice_featured_rank"] > 0),
    ("patients", "CK_patients_digital_literacy"):
        ("digital_literacy_flag IS NULL OR (digital_literacy_flag='app_capable' OR digital_literacy_flag='phone_only')",
         lambda r: r.get("digital_literacy_flag") in (None, "app_capable", "phone_only")),
    ("patients", "CK_patients_gender"):
        ("gender IS NULL OR (gender='female' OR gender='male')", lambda r: r.get("gender") in (None, "female", "male")),
    ("patients", "CK_patients_national_id_hash"):
        ("len(national_id_hash)=(64)", lambda r: len(r["national_id_hash"]) == 64),
    ("patients", "CK_patients_national_id_last4"):
        ("len(national_id_last4)=(4) AND NOT national_id_last4 like '%[^0-9]%'",
         lambda r: len(r["national_id_last4"]) == 4 and r["national_id_last4"].isdigit()),
    ("patients", "CK_patients_patient_code"):
        ("len(patient_code)>=(7) AND NOT patient_code like '%[^0-9]%'",
         lambda r: len(r["patient_code"]) >= 7 and r["patient_code"].isdigit()),
    ("patients", "CK_patients_preferred_language"):
        ("preferred_language='en' OR preferred_language='ar'", lambda r: r.get("preferred_language") in ("en", "ar")),
    ("patient_provider_profiles", "CK_patient_provider_profiles_consent_status"):
        ("consent_status='pending' OR consent_status='withdrawn' OR consent_status='granted'",
         lambda r: r.get("consent_status") in ("pending", "withdrawn", "granted")),
    ("patient_provider_profiles", "CK_patient_provider_profiles_consent_timestamp"):
        ("consent_status='pending' OR (consent_status='withdrawn' OR consent_status='granted') AND "
         "consent_timestamp IS NOT NULL",
         lambda r: r.get("consent_status") == "pending" or r.get("consent_timestamp") is not None),
    ("patient_provider_profiles", "CK_patient_provider_profiles_preferred_channel"):
        ("preferred_channel='mobile' OR preferred_channel='web' OR preferred_channel='whatsapp' OR "
         "preferred_channel='voice'",
         lambda r: r.get("preferred_channel") in ("mobile", "web", "whatsapp", "voice")),
    ("provider_memberships", "ck_provider_memberships_doctor_role"):
        ("role='doctor' AND doctor_id IS NOT NULL OR role<>'doctor' AND doctor_id IS NULL",
         lambda r: (r["role"] == "doctor") == (r.get("doctor_id") is not None)),
    ("provider_memberships", "ck_provider_memberships_role"):
        ("role='lab_staff' OR role='receptionist' OR role='doctor' OR role='provider_admin'",
         lambda r: r["role"] in ("lab_staff", "receptionist", "doctor", "provider_admin")),
}


def test_every_check_constraint_on_a_seeded_table_is_known_and_satisfied():
    seen = set()
    for table, row in fx.SYNTHETIC_ROWS:
        for check in (c for c in Base.metadata.tables[table].constraints if isinstance(c, CheckConstraint)):
            key = (table, check.name)
            assert key in FIXTURE_CHECKS, f"new CHECK constraint {key}: add its predicate"
            expected_text, predicate = FIXTURE_CHECKS[key]
            assert str(check.sqltext) == expected_text, f"{key} changed in the model"
            assert predicate(row), key
            seen.add(key)
    assert seen == set(FIXTURE_CHECKS)


def test_unique_and_filtered_unique_keys_hold_for_the_fixture():
    for table, row in fx.SYNTHETIC_ROWS:
        assert sum(1 for t, _ in fx.SYNTHETIC_ROWS if t == table) == 1  # one row per seeded table
    branch = dict(fx.SYNTHETIC_ROWS)["branches"]
    assert branch["mrn_code"] is not None and len(branch["mrn_code"]) == 3


def test_the_concurrency_seed_query_selects_exactly_the_fixture():
    rows = dict(fx.SYNTHETIC_ROWS)
    provider, branch = rows["providers"], rows["branches"]
    assert provider["is_active"] and provider["org_type"] != "diagnostic_lab"
    assert branch["is_active"] and branch["mrn_code"] and branch["provider_id"] == provider["id"]
    assert rows["specialties"]["is_active"] and rows["services"]["is_active"]
    assert rows["patients"]["is_active"] and rows["patients"]["national_id_hash"] == fx.PATIENT_HASH
    assert rows["patient_provider_profiles"]["is_active"] and rows["patient_branch_profiles"]["is_active"]
    assert rows["patient_branch_profiles"]["branch_id"] == branch["id"]
    membership = rows["provider_memberships"]
    assert membership["role"] == "provider_admin" and membership["is_active"] and membership["user_id"] == fx.USER_ID


def test_the_fixture_contains_no_realistic_personal_data_or_credentials():
    rows = dict(fx.SYNTHETIC_ROWS)
    assert rows["user_accounts"]["email"].endswith(".invalid")
    assert not rows["user_accounts"]["password_hash"].startswith(("$2a$", "$2b$", "$2y$"))  # not bcrypt
    assert rows["patients"]["phone"].startswith("+200")  # no real Egyptian number starts +20 0
    assert rows["patients"]["national_id_hash"] == hashlib.sha256(b"medmind-synthetic-patient-0001").hexdigest()
    assert rows["patients"]["national_id_encrypted"] == b"SYNTHETIC"
    for table, row in fx.SYNTHETIC_ROWS:
        for column in ("name", "name_ar", "name_en", "full_name_ar", "full_name_en"):
            if column in row:
                assert row[column].startswith("Synthetic "), (table, column)


def test_the_manifest_hash_is_embedded_in_the_seed_and_verify_scripts():
    assert f"'{fx.MANIFEST_SHA256}'" in _code(_script("S3_seed.sql"))
    assert f"manifest_sha256 = '{fx.MANIFEST_SHA256}'" in _code(_script("S4_verify_synthetic_readonly.sql"))
    assert generator.guard_expected_counts() == {**fx.SYNTHETIC_MANIFEST, **{t: 0 for t in generator.empty_tables()}}
    assert set(fx.SYNTHETIC_TEST_WRITABLE_TABLES) <= set(generator.schema_tables())


# ============================================================ S0-S6 static safety


@pytest.mark.parametrize("name", SCRIPTS)
def test_every_script_checks_server_name_pattern_and_denylist_first(name):
    code = _code(_script(name))
    assert code.index("IF @@SERVERNAME <> N'LAPTOP-FACHLL1N\\SQLEXPRESS'") < code.index("THROW")
    assert "DATALENGTH(@synthetic_name) <> 66" in code
    assert generator.NAME_LIKE in code
    for denied in ("N'medmind_booking_db', N'medmind_audit_final2', N'medmind_audit_final'",
                   "LIKE N'medmind[_]audit%'", "LIKE N'medmind[_]booking%'", "LIKE N'medmind[_]concscratch%'"):
        assert denied in code, denied
    assert "$(" not in code and not re.search(r"(?im)^\s*(GO|:setvar|:r)\b", code)


@pytest.mark.parametrize("name", ["S0_instance_readonly.sql", "S4_verify_synthetic_readonly.sql"])
def test_read_only_scripts_contain_no_writes(name):
    code = _code(_script(name), keep_strings=False)
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|BACKUP|RESTORE|TRUNCATE|DBCC|EXEC|GRANT)\b",
                         code, re.IGNORECASE)


@pytest.mark.parametrize("name", ["S2_schema.sql", "S3_seed.sql", "S4_verify_synthetic_readonly.sql"])
def test_in_database_scripts_prove_identity_isolation_and_no_restore(name):
    code = _code(_script(name))
    first_write = min([code.index(m) for m in ("BEGIN TRANSACTION;",) if m in code] + [len(code)])
    for required in ("DB_NAME() COLLATE Latin1_General_BIN <> @synthetic_name COLLATE Latin1_General_BIN",
                     "is_read_committed_snapshot_on = 0", "snapshot_isolation_state = 0",
                     "source_database_id IS NULL", "FROM msdb.dbo.restorehistory WHERE destination_database_name = DB_NAME()"):
        assert required in code[:first_write], required


def test_s3_seeds_only_an_empty_exact_schema_in_one_transaction():
    code = _code(_script("S3_seed.sql"))
    begin = code.index("BEGIN TRANSACTION;")
    for refusal in ("THROW 52306", "THROW 52307", "THROW 52308", "THROW 52309", "THROW 52310"):
        assert code.index(refusal) < begin, refusal
    assert f"<> 0x{generator.schema_fingerprint().upper()}" in code[:begin]
    for table in generator.schema_tables():
        if table != "alembic_version":
            assert f"EXISTS (SELECT 1 FROM dbo.{table})" in code[:begin], table
    marker = code.index(f"CREATE TABLE dbo.{fx.MARKER_TABLE}")
    assert begin < marker < code.index("COMMIT TRANSACTION;")


def test_s1_creates_only_after_every_refusal_and_never_quotenames_a_path():
    code = _code(_script("S1_create_synthetic_db.sql"))
    create = code.index("EXEC (@create);")
    for refusal in ("THROW 52100", "THROW 52101", "THROW 52102", "THROW 52103", "THROW 52104", "THROW 52105",
                    "THROW 52106", "THROW 52107", "THROW 52108"):
        assert code.index(refusal) < create, refusal
    assert set(re.findall(r"QUOTENAME\((@\w+)\)", code)) == {"@db"}
    assert "REPLACE(@data_file, N'''', N'''''')" in code and "REPLACE(@log_file, N'''', N'''''')" in code
    for option in ("SET RECOVERY SIMPLE", "SET READ_COMMITTED_SNAPSHOT OFF", "SET ALLOW_SNAPSHOT_ISOLATION OFF"):
        assert option in code[create:], option
    assert code.index("EXEC (@options);") < code.index("THROW 52110") < code.index("THROW 52111")


def test_s6_proves_identity_and_synthetic_state_before_the_only_drop():
    code = _code(_script("S6_drop_synthetic_db.sql"))
    drop = code.index("EXEC (@drop);")
    for number in range(52600, 52618):
        assert code.index(f"THROW {number}") < drop, number
    assert code.count("DROP DATABASE") == 1 and "N'DROP DATABASE ' + QUOTENAME(@db)" in code
    assert "state_desc = N'ONLINE'" in code[:drop]
    assert "FROM msdb.dbo.restorehistory WHERE destination_database_name = @db" in code[:drop]
    assert code.index("BEGIN TRY") < code.index("EXEC @proc @probe") < code.index("BEGIN CATCH") \
        < code.index("THROW 52613, @probe_error") < drop


def test_s6_embeds_exactly_the_generated_schema_fingerprint_and_table_count():
    sql = _script("S6_drop_synthetic_db.sql")
    assert generator.FINGERPRINT_SQL.replace("'", "''") in sql
    assert f"@expected_fingerprint varbinary(32) = 0x{generator.schema_fingerprint().upper()};" in sql
    tables = len(generator.schema_tables())
    assert f"@user_tables <> {tables + 1}" in sql and f"@user_tables = {tables} AND" in sql


def test_s6_partial_cleanup_accepts_only_empty_or_schema_only_databases():
    code = _code(_script("S6_drop_synthetic_db.sql"))
    branch = code[code.index("IF @marker = 1"):code.index("PRINT N'S6: dropping")]
    assert "ELSE IF @user_tables = 0 AND @user_objects = 0" in branch
    assert "AND ISNULL(@fingerprint, 0x00) = @expected_fingerprint AND @total_rows = 0" in branch
    assert branch.rstrip().endswith("(manual review).', 1;")


# ============================================================ guard: names and engines


def _engine(database, extra=""):
    odbc = (
        "DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\\SQLEXPRESS;"
        f"DATABASE={database};Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes{extra}"
    )
    return sqlalchemy.create_engine("mssql+pyodbc:///?odbc_connect=" + quote_plus(odbc))


@pytest.mark.parametrize("name", [NAME, "MedMind_SynthConc_20991231_000000"])
def test_synthetic_names_are_accepted(name):
    assert guard.synthetic_name_problem(name) is None


@pytest.mark.parametrize("name", PROTECTED + [
    "medmind_audit_final2", "MEDMIND_BOOKING_DB", " " + NAME, NAME + " ", NAME.upper(),
    "MedMind_SynthConc_20261026_A1B2C3", "MedMind_SynthConc_2026102_a1b2c3", NAME + "_x",
    "MedMind_ConcScratch_20261026_a1b2c3", "medmind_concscratch_20261026_a1b2c3",
    "MedMind_SynthConc_٢٠٢٦١٠٢٦_a1b2c3", NAME + ";DATABASE=MedMind_Audit_Final2", "", None,
])
def test_protected_restored_and_malformed_names_are_refused(name):
    assert guard.synthetic_name_problem(name) is not None


def test_the_synthetic_engine_is_accepted():
    assert guard.synthetic_engine_problem(_engine(NAME), NAME) is None


@pytest.mark.parametrize("database", PROTECTED + ["MedMind_ConcScratch_20261026_a1b2c3",
                                                  "MedMind_SynthConc_20261026_ffffff"])
def test_engines_for_any_other_database_are_refused(database):
    assert guard.synthetic_engine_problem(_engine(database), NAME) is not None


@pytest.mark.parametrize("extra", [";UID=someone", ";DATABASE=MedMind_Booking_DB", ";Initial Catalog=MedMind_Audit_Final2"])
def test_redirecting_odbc_keys_are_refused(extra):
    assert guard.synthetic_engine_problem(_engine(NAME, extra), NAME) is not None


# ============================================================ guard: before connecting


@pytest.fixture
def synthetic_env(monkeypatch):
    values = {
        "APP_ENV": "staging", "MEDMIND_DB_INTEGRATION": "1", "MEDMIND_SYNTHETIC_CONCURRENCY": "1",
        "MEDMIND_SYNTHETIC_DB_NAME": NAME, "MEDMIND_SYNTHETIC_TOKEN": TOKEN,
        "DB_SERVER": "localhost\\SQLEXPRESS", "DB_NAME": NAME, "DB_TRUSTED_CONNECTION": "true",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(db_session_module, "engine", _engine(NAME))
    get_settings.cache_clear()
    return monkeypatch


def test_the_exact_synthetic_target_passes_without_connecting(synthetic_env):
    engine, name, token_hash = guard.require_synthetic_target()
    assert name == NAME and token_hash == guard.token_sha256(TOKEN)


@pytest.mark.parametrize("change", [
    {"MEDMIND_SYNTHETIC_CONCURRENCY": None}, {"MEDMIND_DB_INTEGRATION": None}, {"APP_ENV": None},
    {"MEDMIND_SYNTHETIC_DB_NAME": "MedMind_Audit_Final2", "DB_NAME": "MedMind_Audit_Final2"},
    {"MEDMIND_SYNTHETIC_DB_NAME": "MedMind_Booking_DB", "DB_NAME": "MedMind_Booking_DB"},
    {"MEDMIND_SYNTHETIC_DB_NAME": "MedMind_ConcScratch_20261026_a1b2c3", "DB_NAME": "MedMind_ConcScratch_20261026_a1b2c3"},
    {"DB_NAME": "MedMind_Audit_Final2"}, {"DB_SERVER": "otherhost"}, {"DB_TRUSTED_CONNECTION": "false"},
    {"MEDMIND_SYNTHETIC_TOKEN": "short"}, {"MEDMIND_SYNTHETIC_TOKEN": TOKEN.upper()}, {"MEDMIND_SYNTHETIC_TOKEN": TOKEN[:32]},
])
def test_any_wrong_setting_fails_closed_before_connecting(synthetic_env, change):
    for key, value in change.items():
        if value is None:
            synthetic_env.delenv(key, raising=False)
        else:
            synthetic_env.setenv(key, value)
    get_settings.cache_clear()
    with pytest.raises(Failed, match="SYNTHETIC SAFETY STOP"):
        guard.require_synthetic_target()


@pytest.mark.parametrize("database", PROTECTED + ["MedMind_ConcScratch_20261026_a1b2c3"])
def test_a_stale_engine_for_another_database_fails_closed(synthetic_env, database):
    synthetic_env.setattr(db_session_module, "engine", _engine(database))
    with pytest.raises(Failed, match="SYNTHETIC SAFETY STOP"):
        guard.require_synthetic_target()


# ============================================================ guard: after connecting (pure)


DATA_DIR = "C:\\Program Files\\Microsoft SQL Server\\MSSQL17.SQLEXPRESS\\MSSQL\\DATA\\"
LOG_DIR = DATA_DIR
GOOD_FILES = [(0, DATA_DIR + NAME + "_data.mdf"), (1, LOG_DIR + NAME + "_log.ldf")]


def _good_facts():
    return SimpleNamespace(
        server_name=generator.SERVER_NAME, db_name=NAME, database_row=("ONLINE", False, None, False, 0, 170, "SQL_Latin1_General_CP1_CI_AS"),
        default_paths=(DATA_DIR, LOG_DIR), files=list(GOOD_FILES), restore_history_rows=0, marker_exists=True,
        marker_rows=[(NAME, fx.MARKER_KIND, fx.FIXTURE_VERSION, guard.token_sha256(TOKEN), fx.MANIFEST_SHA256)],
        revisions=[fx.EXPECTED_REVISION], columns=list(guard.EXPECTED_COLUMNS), counts=dict(guard.EXPECTED_COUNTS),
    )


def test_the_prepared_synthetic_database_passes():
    assert guard.connected_problem(_good_facts(), NAME, guard.token_sha256(TOKEN)) is None


def _marker(**changes):
    fields = dict(zip(("name", "kind", "version", "token", "manifest"), _good_facts().marker_rows[0]))
    fields.update(changes)
    return [tuple(fields.values())]


@pytest.mark.parametrize("change", [
    {"server_name": "OTHERHOST\\SQLEXPRESS"}, {"server_name": "LAPTOP-FACHLL1N"}, {"server_name": None},
    {"files": GOOD_FILES[:1]}, {"files": GOOD_FILES + [(0, DATA_DIR + NAME + "_data2.ndf")]},
    {"files": [(0, "D:\\elsewhere\\" + NAME + "_data.mdf"), GOOD_FILES[1]]},
    {"files": [(0, DATA_DIR + "MedMind_Audit_Final2.mdf"), (1, LOG_DIR + "MedMind_Audit_Final2_log.ldf")]},
    {"files": [(1, GOOD_FILES[0][1]), (0, GOOD_FILES[1][1])]},
    {"default_paths": (None, LOG_DIR)}, {"default_paths": ("D:\\other\\", LOG_DIR)},
    {"db_name": "MedMind_Audit_Final2"}, {"db_name": "MedMind_Booking_DB"},
    {"database_row": None}, {"database_row": ("RESTORING", False, None, False, 0, 170, "SQL_Latin1_General_CP1_CI_AS")},
    {"database_row": ("ONLINE", True, None, False, 0, 170, "SQL_Latin1_General_CP1_CI_AS")}, {"database_row": ("ONLINE", False, 7, False, 0, 170, "SQL_Latin1_General_CP1_CI_AS")},
    {"database_row": ("ONLINE", False, None, True, 0, 170, "SQL_Latin1_General_CP1_CI_AS")}, {"database_row": ("ONLINE", False, None, False, 1, 170, "SQL_Latin1_General_CP1_CI_AS")},
    {"database_row": ("ONLINE", False, None, False, 0, 160, "SQL_Latin1_General_CP1_CI_AS")},
    {"database_row": ("ONLINE", False, None, False, 0, None, "SQL_Latin1_General_CP1_CI_AS")},
    {"database_row": ("ONLINE", False, None, False, 0, 170, "Latin1_General_CI_AS")},
    {"database_row": ("ONLINE", False, None, False, 0, 170, "SQL_Latin1_General_CP1_CS_AS")},
    {"database_row": ("ONLINE", False, None, False, 0, 170, None)},
    {"restore_history_rows": 1},
    {"marker_exists": False, "marker_rows": []}, {"marker_rows": []},
    {"marker_rows": _good_facts().marker_rows * 2},
    {"marker_rows": _marker(name="MedMind_SynthConc_20261026_ffffff")},
    {"marker_rows": _marker(kind="restored")}, {"marker_rows": _marker(version="synthetic-v0")},
    {"marker_rows": _marker(token="0" * 64)}, {"marker_rows": _marker(manifest="0" * 64)},
    {"revisions": ["a8c2e5f1b7d4"]}, {"revisions": []}, {"revisions": [fx.EXPECTED_REVISION] * 2},
    {"columns": list(guard.EXPECTED_COLUMNS)[:-1]},
    {"columns": list(guard.EXPECTED_COLUMNS) + ["patients.extra_column"]},
    {"counts": {**guard.EXPECTED_COUNTS, "patients": 2}},
    {"counts": {**guard.EXPECTED_COUNTS, "clinical_notes": 1}},
    {"counts": {**guard.EXPECTED_COUNTS, "providers": 0}},
])
def test_anything_not_positively_synthetic_is_refused(change):
    facts = _good_facts()
    for key, value in change.items():
        setattr(facts, key, value)
    assert guard.connected_problem(facts, NAME, guard.token_sha256(TOKEN)) is not None


def test_per_connection_guard_queries_never_read_test_written_tables():
    import inspect

    reads = inspect.getsource(guard._read_facts) + guard.COUNTS_SQL
    for table in fx.SYNTHETIC_TEST_WRITABLE_TABLES:
        assert f"dbo.{table}" not in reads, table
    assert "FROM dbo.alembic_version" in reads and "FROM dbo.{fx.MARKER_TABLE}" in reads


def test_the_synthetic_guard_leaves_the_restored_scratch_guard_alone():
    import inspect

    from tests import scratch_db_guard

    source = inspect.getsource(guard)
    assert "scratch_db_guard" not in source.replace("tests/scratch_db_guard.py", "")
    assert scratch_db_guard.SOURCE_DATABASE == "MedMind_Audit_Final2"  # restored-copy marker contract unchanged


# ============================================================ guard: file paths (pure)


@pytest.mark.parametrize("data_dir, log_dir", [(DATA_DIR, LOG_DIR), (DATA_DIR.rstrip("\\"), LOG_DIR.rstrip("\\"))])
def test_s1_file_paths_are_built_exactly_as_s1_builds_them(data_dir, log_dir):
    assert guard.s1_file_paths(data_dir, log_dir, NAME) == (GOOD_FILES[0][1], GOOD_FILES[1][1])
    s1 = _code(_script("S1_create_synthetic_db.sql"))
    assert "@data_dir + @db + N'_data.mdf'" in s1 and "@log_dir + @db + N'_log.ldf'" in s1


def test_file_paths_compare_case_insensitively_like_s1_and_s6():
    files = [(0, GOOD_FILES[0][1].upper()), (1, GOOD_FILES[1][1].lower())]
    assert guard.file_problem(files, (DATA_DIR, LOG_DIR), NAME) is None
    assert guard.file_problem(GOOD_FILES, (None, None), NAME) is not None
    assert guard.file_problem(GOOD_FILES, None, NAME) is not None


# ============================================================ guard: _read_facts on a stub connection


class _StubResult:
    def __init__(self, rows):
        self._rows = [tuple(row) for row in rows] if not isinstance(rows, dict) else rows

    def one(self):
        if isinstance(self._rows, dict) or len(self._rows) != 1:
            raise (sqlalchemy.exc.NoResultFound if not self._rows else sqlalchemy.exc.MultipleResultsFound)()
        return self._rows[0]

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one(self):
        return self.one()[0]

    def scalar(self):
        return self._rows[0][0] if self._rows else None

    def all(self):
        return list(self._rows)

    def mappings(self):
        counts = self._rows
        return SimpleNamespace(one=lambda: counts)


class _StubConnection:
    """Answers the guard's statements from canned rows. Opens nothing:
    an unknown statement fails the test."""

    def __init__(self, **overrides):
        answers = {
            "identity": [(NAME, generator.SERVER_NAME, DATA_DIR, LOG_DIR)],
            "database": [("ONLINE", False, None, False, 0, 170, "SQL_Latin1_General_CP1_CI_AS")],
            "files": list(GOOD_FILES),
            "restore": [(0,)],
            "marker_id": [(1234567,)],
            "marker": [(NAME, fx.MARKER_KIND, fx.FIXTURE_VERSION, guard.token_sha256(TOKEN), fx.MANIFEST_SHA256)],
            "revision": [(fx.EXPECTED_REVISION,)],
            "columns": [(c,) for c in reversed(guard.EXPECTED_COLUMNS)],  # unsorted on purpose
            "counts": dict(guard.EXPECTED_COUNTS),
            "set": [],
        }
        answers.update(overrides)
        self.answers, self.executed, self.kinds, self.calls = answers, [], [], []

    def _kind(self, sql):
        if sql == guard.COUNTS_SQL:
            return "counts"
        for kind, marker in (("set", "SET LOCK_TIMEOUT "), ("identity", "SELECT DB_NAME(), @@SERVERNAME"),
                             ("database", "FROM sys.databases WHERE name = DB_NAME()"),
                             ("files", "FROM sys.database_files"), ("restore", "FROM msdb.dbo.restorehistory"),
                             ("marker_id", f"OBJECT_ID(N'dbo.{fx.MARKER_TABLE}', N'U')"),
                             ("marker", f"FROM dbo.{fx.MARKER_TABLE}"), ("revision", "FROM dbo.alembic_version"),
                             ("columns", "FROM sys.tables AS t JOIN sys.columns")):
            if marker in sql:
                return kind
        raise AssertionError(f"unexpected statement: {sql}")

    def execute(self, clause):
        sql = str(clause)
        kind = self._kind(sql)
        self.executed.append(sql)
        self.kinds.append(kind)
        answer = self.answers[kind]
        if isinstance(answer, Exception):
            raise answer
        return _StubResult(answer)

    def __getattr__(self, name):  # commit, rollback, invalidate, close
        if name in ("commit", "rollback", "invalidate", "close"):
            return lambda: self.calls.append(name)
        raise AttributeError(name)


def _lock_timeout():
    return sqlalchemy.exc.OperationalError("SELECT ...", {}, Exception("Lock request time out period exceeded. (1222)"))


IDENTITY_KINDS = ["identity", "database", "files", "restore"]
CONTENT_KINDS = ["marker_id", "marker", "revision", "columns", "counts"]


def test_read_facts_maps_every_query_result():
    stub = _StubConnection()
    facts = guard._read_facts(stub, NAME)
    assert (facts.db_name, facts.server_name, facts.default_paths) == (NAME, generator.SERVER_NAME, (DATA_DIR, LOG_DIR))
    assert facts.database_row == ("ONLINE", False, None, False, 0, 170, "SQL_Latin1_General_CP1_CI_AS") and facts.files == GOOD_FILES
    assert facts.restore_history_rows == 0 and facts.marker_exists is True
    assert facts.marker_rows == stub.answers["marker"] and facts.revisions == [fx.EXPECTED_REVISION]
    assert facts.columns == list(guard.EXPECTED_COLUMNS) and facts.counts == guard.EXPECTED_COUNTS
    assert guard.connected_problem(facts, NAME, guard.token_sha256(TOKEN)) is None
    assert all(sql.lstrip().startswith("SELECT") for sql in stub.executed)


def test_read_facts_reads_nothing_inside_an_unmarked_database():
    stub = _StubConnection(marker_id=[(None,)])
    facts = guard._read_facts(stub, NAME)
    assert facts.marker_exists is False and facts.marker_rows == [] and facts.counts == {}
    assert stub.kinds == IDENTITY_KINDS + ["marker_id"]  # no marker, revision, schema or count query
    assert "no synthetic marker" in guard.connected_problem(facts, NAME, guard.token_sha256(TOKEN))


def test_guard_queries_run_in_the_exact_order_identity_first():
    stub = _StubConnection()
    guard._verify_connected(stub, NAME, guard.token_sha256(TOKEN))
    assert stub.kinds == IDENTITY_KINDS + CONTENT_KINDS


BAD_IDENTITY = {
    "server": {"identity": [(NAME, "OTHERHOST\\SQLEXPRESS", DATA_DIR, LOG_DIR)]},
    "server_null": {"identity": [(NAME, None, DATA_DIR, LOG_DIR)]},
    "database_name": {"identity": [("MedMind_Audit_Final2", generator.SERVER_NAME, DATA_DIR, LOG_DIR)]},
    "other_synthetic": {"identity": [("MedMind_SynthConc_20261026_ffffff", generator.SERVER_NAME, DATA_DIR, LOG_DIR)]},
    "not_in_sys_databases": {"database": []},
    "restoring": {"database": [("RESTORING", False, None, False, 0, 170, "SQL_Latin1_General_CP1_CI_AS")]},
    "read_only": {"database": [("ONLINE", True, None, False, 0, 170, "SQL_Latin1_General_CP1_CI_AS")]},
    "snapshot": {"database": [("ONLINE", False, 7, False, 0, 170, "SQL_Latin1_General_CP1_CI_AS")]},
    "rcsi": {"database": [("ONLINE", False, None, True, 0, 170, "SQL_Latin1_General_CP1_CI_AS")]},
    "level_160": {"database": [("ONLINE", False, None, False, 0, 160, "SQL_Latin1_General_CP1_CI_AS")]},
    "level_150": {"database": [("ONLINE", False, None, False, 0, 150, "SQL_Latin1_General_CP1_CI_AS")]},
    "level_null": {"database": [("ONLINE", False, None, False, 0, None, "SQL_Latin1_General_CP1_CI_AS")]},
    "collation_latin1": {"database": [("ONLINE", False, None, False, 0, 170, "Latin1_General_CI_AS")]},
    "collation_case_sensitive": {"database": [("ONLINE", False, None, False, 0, 170, "SQL_Latin1_General_CP1_CS_AS")]},
    "collation_null": {"database": [("ONLINE", False, None, False, 0, 170, None)]},
    "no_default_data_path": {"identity": [(NAME, generator.SERVER_NAME, None, LOG_DIR)]},
    "no_default_log_path": {"identity": [(NAME, generator.SERVER_NAME, DATA_DIR, "")]},
    "files_elsewhere": {"files": [(0, "D:\\elsewhere\\" + NAME + "_data.mdf"), GOOD_FILES[1]]},
    "files_of_final2": {"files": [(0, DATA_DIR + "MedMind_Audit_Final2.mdf"), (1, LOG_DIR + "MedMind_Audit_Final2_log.ldf")]},
    "extra_file": {"files": GOOD_FILES + [(0, DATA_DIR + NAME + "_data2.ndf")]},
    "no_files": {"files": []},
    "restored": {"restore": [(1,)]},
}


@pytest.mark.parametrize("case", sorted(BAD_IDENTITY))
def test_a_wrong_identity_never_reads_marker_revision_schema_or_counts(case):
    stub = _StubConnection(**BAD_IDENTITY[case])
    with pytest.raises(Failed, match="SYNTHETIC SAFETY STOP"):
        guard._verify_connected(stub, NAME, guard.token_sha256(TOKEN))
    assert stub.kinds == IDENTITY_KINDS
    assert not [sql for sql in stub.executed if "FROM dbo." in sql or "sys.tables" in sql or "OBJECT_ID" in sql]
    facts = guard._read_facts(_StubConnection(**BAD_IDENTITY[case]), NAME)
    assert guard.identity_problem(facts, NAME) is not None
    assert (facts.marker_exists, facts.marker_rows, facts.revisions, facts.columns, facts.counts) == (False, [], [], [], {})


@pytest.mark.parametrize("level, collation, reason", [
    (160, "SQL_Latin1_General_CP1_CI_AS", "compatibility level must be 170"),
    ("170", "SQL_Latin1_General_CP1_CI_AS", "compatibility level must be 170"),  # wrong type is not equal
    (170, "Latin1_General_CI_AS", "collation must be SQL_Latin1_General_CP1_CI_AS"),
    (170, "sql_latin1_general_cp1_ci_as", "collation must be SQL_Latin1_General_CP1_CI_AS"),
])
def test_a_wrong_level_or_collation_is_refused_before_any_marker_or_table_read(level, collation, reason):
    stub = _StubConnection(database=[("ONLINE", False, None, False, 0, level, collation)])
    with pytest.raises(Failed, match=re.escape(f"SYNTHETIC SAFETY STOP: the {reason}")):
        guard._verify_connected(stub, NAME, guard.token_sha256(TOKEN))
    assert stub.kinds == IDENTITY_KINDS
    assert not [sql for sql in stub.executed if "FROM dbo." in sql or "sys.tables" in sql or "OBJECT_ID" in sql]


def test_the_level_and_collation_come_from_the_identity_query():
    sql = _StubConnection()
    guard._read_facts(sql, NAME)
    database_query = sql.executed[IDENTITY_KINDS.index("database")]
    assert "compatibility_level, collation_name FROM sys.databases WHERE name = DB_NAME()" in database_query
    assert (guard.EXPECTED_COMPATIBILITY_LEVEL, guard.EXPECTED_COLLATION) == (170, "SQL_Latin1_General_CP1_CI_AS")


def test_a_wrong_level_through_synthetic_connection_reads_only_identity(monkeypatch):
    stub = _StubConnection(**BAD_IDENTITY["level_160"])
    _stub_target(monkeypatch, stub)
    with pytest.raises(Failed, match="compatibility level must be 170"):
        with guard.synthetic_connection(2000):
            raise AssertionError("an unverified connection was yielded")
    assert stub.kinds == ["set"] + IDENTITY_KINDS and "SET LOCK_TIMEOUT 2000" not in stub.executed
    assert stub.calls == ["commit", "invalidate", "close"]


def test_a_failing_level_and_collation_query_stops_before_any_marker_or_table_read():
    stub = _StubConnection(database=_lock_timeout())
    with pytest.raises(Failed, match="SYNTHETIC SAFETY STOP: a guard query failed"):
        guard._verify_connected(stub, NAME, guard.token_sha256(TOKEN))
    assert stub.kinds == ["identity", "database"]


@pytest.mark.parametrize("failing", IDENTITY_KINDS)
def test_an_identity_query_error_stops_before_anything_else(failing):
    stub = _StubConnection(**{failing: _lock_timeout()})
    with pytest.raises(Failed, match="SYNTHETIC SAFETY STOP: a guard query failed"):
        guard._verify_connected(stub, NAME, guard.token_sha256(TOKEN))
    assert stub.kinds == IDENTITY_KINDS[:IDENTITY_KINDS.index(failing) + 1]


@pytest.mark.parametrize("override", [{"identity": [(NAME, generator.SERVER_NAME, DATA_DIR)]},
                                      {"restore": []}, {"identity": [(NAME,) * 5]},
                                      {"database": [("ONLINE", False, None)]}, {"files": [(0,), (1,)]}])
def test_a_malformed_identity_result_fails_closed(override):
    stub = _StubConnection(**override)
    with pytest.raises(Failed, match="SYNTHETIC SAFETY STOP: a guard query failed"):
        guard._verify_connected(stub, NAME, guard.token_sha256(TOKEN))
    assert not set(stub.kinds) & set(CONTENT_KINDS)


@pytest.mark.parametrize("override, reason", [
    ({"identity": [(NAME, "OTHERHOST\\SQLEXPRESS", DATA_DIR, LOG_DIR)]}, "@@SERVERNAME"),
    ({"identity": [("MedMind_Audit_Final2", generator.SERVER_NAME, DATA_DIR, LOG_DIR)]}, "different database"),
    ({"database": []}, "not listed in sys.databases"),
    ({"files": [(0, DATA_DIR + "MedMind_Audit_Final2.mdf"), (1, LOG_DIR + "MedMind_Audit_Final2_log.ldf")]}, "S1 paths"),
    ({"identity": [(NAME, generator.SERVER_NAME, None, LOG_DIR)]}, "no default data or log path"),
    ({"restore": [(1,)]}, "RESTORE"),
    ({"counts": {**guard.EXPECTED_COUNTS, "clinical_notes": 1}}, "row counts"),
    ({"counts": {k: v for k, v in guard.EXPECTED_COUNTS.items() if k != "patients"}}, "row counts"),
])
def test_stubbed_query_results_that_are_not_synthetic_are_refused(override, reason):
    with pytest.raises(Failed, match=re.escape(reason)):
        guard._verify_connected(_StubConnection(**override), NAME, guard.token_sha256(TOKEN))


@pytest.mark.parametrize("kind", ["identity", "database", "files", "restore", "marker_id", "marker", "revision",
                                  "columns", "counts"])
def test_any_guard_query_error_is_a_safety_stop(kind):
    with pytest.raises(Failed, match="SYNTHETIC SAFETY STOP: a guard query failed"):
        guard._verify_connected(_StubConnection(**{kind: _lock_timeout()}), NAME, guard.token_sha256(TOKEN))


def test_an_identity_query_without_exactly_one_row_is_a_safety_stop():
    for rows in ([], [(NAME, generator.SERVER_NAME, DATA_DIR, LOG_DIR)] * 2):
        with pytest.raises(Failed, match="SYNTHETIC SAFETY STOP: a guard query failed"):
            guard._verify_connected(_StubConnection(identity=rows), NAME, guard.token_sha256(TOKEN))


# ============================================================ guard: LOCK_TIMEOUT ordering (stub engine)


def _stub_target(monkeypatch, stub):
    engine = SimpleNamespace(connect=lambda: stub)
    monkeypatch.setattr(guard, "require_synthetic_target", lambda: (engine, NAME, guard.token_sha256(TOKEN)))


def test_the_guard_lock_timeout_is_set_before_any_guard_query_and_the_callers_after(monkeypatch):
    stub = _StubConnection()
    _stub_target(monkeypatch, stub)
    with guard.synthetic_connection(2000) as connection:
        assert connection is stub
        executed = list(stub.executed)
    assert 0 < guard.GUARD_LOCK_TIMEOUT_MS <= 10000
    assert executed[0] == f"SET LOCK_TIMEOUT {guard.GUARD_LOCK_TIMEOUT_MS}"
    assert executed[-1] == "SET LOCK_TIMEOUT 2000"
    assert [sql for sql in executed if sql.startswith("SET ")] == [executed[0], executed[-1]]
    assert stub.kinds == ["set"] + IDENTITY_KINDS + CONTENT_KINDS + ["set"]  # every guard query is bounded
    assert stub.calls == ["commit", "rollback", "commit", "rollback", "invalidate", "close"]


@pytest.mark.parametrize("override", [{"identity": [(NAME, "OTHERHOST\\SQLEXPRESS", DATA_DIR, LOG_DIR)]},
                                      {"columns": _lock_timeout()}])
def test_a_refused_connection_is_never_yielded_and_never_gets_the_callers_timeout(monkeypatch, override):
    stub = _StubConnection(**override)
    _stub_target(monkeypatch, stub)
    with pytest.raises(Failed, match="SYNTHETIC SAFETY STOP"):
        with guard.synthetic_connection(2000):
            raise AssertionError("an unverified connection was yielded")
    assert "SET LOCK_TIMEOUT 2000" not in stub.executed
    assert stub.executed[0] == f"SET LOCK_TIMEOUT {guard.GUARD_LOCK_TIMEOUT_MS}"
    assert stub.calls == ["commit", "invalidate", "close"]


def test_a_wrong_server_through_synthetic_connection_reads_only_identity(monkeypatch):
    stub = _StubConnection(**BAD_IDENTITY["server"])
    _stub_target(monkeypatch, stub)
    with pytest.raises(Failed, match="@@SERVERNAME"):
        with guard.synthetic_connection(2000):
            raise AssertionError("an unverified connection was yielded")
    assert stub.kinds == ["set"] + IDENTITY_KINDS
    assert stub.calls == ["commit", "invalidate", "close"]


# ============================================================ fixture vs concurrency test, S0, S4, generator pin


def test_the_test_doctor_prefix_matches_the_concurrency_test():
    import ast

    tree = ast.parse((ROOT / "Backend" / "tests" / "test_reschedule_concurrency_scratch_db.py").read_text(encoding="utf-8"))
    values = [node.value.value for node in tree.body
              if isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] == ["MARKER_PREFIX"]]
    assert values == [fx.TEST_DOCTOR_LICENSE_PREFIX]
    assert f"NOT LIKE N'{fx.TEST_DOCTOR_LICENSE_PREFIX}%'" in _code(_script("S4_verify_synthetic_readonly.sql"))


def test_s4_checks_the_s1_file_paths_before_reading_the_database():
    code = _code(_script("S4_verify_synthetic_readonly.sql"))
    files = code.index("THROW 52412")
    assert code.index("THROW 52405") < code.index("THROW 52411") < files < code.index("FROM dbo.zz_synthetic_marker")
    assert "IF (SELECT COUNT(*) FROM sys.database_files) <> 2" in code
    assert "type = 0 AND LOWER(physical_name) = LOWER(@data_dir + DB_NAME() + N'_data.mdf')" in code
    assert "type = 1 AND LOWER(physical_name) = LOWER(@log_dir + DB_NAME() + N'_log.ldf')" in code
    assert "master_files" not in code


def test_s4_checks_level_and_collation_before_the_marker_or_any_application_table():
    code = _code(_script("S4_verify_synthetic_readonly.sql"))
    check = ("IF NOT EXISTS (SELECT 1 FROM sys.databases\n"
             "               WHERE name = DB_NAME() AND compatibility_level = 170\n"
             "                 AND collation_name = N'SQL_Latin1_General_CP1_CI_AS')\n"
             "    THROW 52413, ")
    assert code.count(check) == 1
    level = code.index(check)
    assert code.index("THROW 52403") < code.index("THROW 52404") < level  # name and state first
    first_read = min(code.index(m) for m in ("OBJECT_ID(N'dbo.zz_synthetic_marker'", "FROM dbo."))
    assert level < first_read
    assert code.count("THROW 52413") == 1


def test_s1_s4_and_the_guard_share_one_level_and_collation():
    level, collation = generator.SYNTHETIC_COMPATIBILITY_LEVEL, generator.SYNTHETIC_COLLATION
    assert (level, collation) == (int(S1_LEVEL), S1_COLLATION)
    s1 = _code(_script("S1_create_synthetic_db.sql"))
    assert f"SET COMPATIBILITY_LEVEL = {level};" in s1 and f"COLLATE {collation};" in s1
    assert f"compatibility_level = {level}" in s1 and f"collation_name = N'{collation}'" in s1
    s4 = _code(_script("S4_verify_synthetic_readonly.sql"))
    assert f"compatibility_level = {level}" in s4 and f"collation_name = N'{collation}'" in s4
    assert (guard.EXPECTED_COMPATIBILITY_LEVEL, guard.EXPECTED_COLLATION) == (level, collation)


def test_s0_reports_the_model_database_compatibility_collation_and_user_objects():
    code = _code(_script("S0_instance_readonly.sql"))
    model = code[code.index("SELECT name, is_read_committed_snapshot_on"):]
    model = model[:model.index(";")]
    assert "compatibility_level, collation_name" in model
    assert "(SELECT COUNT(*) FROM model.sys.objects WHERE is_ms_shipped = 0) AS user_objects" in model
    assert model.rstrip().endswith("FROM sys.databases WHERE name = N'model'")
    # S0 reads system databases only: never a MedMind database by name
    assert not re.search(r"\bMedMind_\w+\.", code, re.IGNORECASE)


S1_COLLATION = "SQL_Latin1_General_CP1_CI_AS"
S1_LEVEL = "170"


def _s1_section(start, end):
    code = _code(_script("S1_create_synthetic_db.sql"))
    return code[code.index(start):code.index(end)]


def test_s1_creates_the_database_with_the_pinned_collation():
    create = _s1_section("DECLARE @create nvarchar(max) =", "IF @create IS NULL")
    assert create.rstrip().endswith(f"+ N' COLLATE {S1_COLLATION};';")
    assert create.index("LOG ON") < create.index(f"COLLATE {S1_COLLATION}")
    code = _code(_script("S1_create_synthetic_db.sql"))
    assert re.findall(r"COLLATE (SQL_\w+)", code) == [S1_COLLATION]  # nowhere else, no other collation


def test_s1_sets_compatibility_level_170_after_creating():
    options = _s1_section("DECLARE @options nvarchar(max) =", "IF @options IS NULL")
    assert options.rstrip().endswith(f"+ N'ALTER DATABASE ' + QUOTENAME(@db) + N' SET COMPATIBILITY_LEVEL = {S1_LEVEL};';")
    code = _code(_script("S1_create_synthetic_db.sql"))
    assert re.findall(r"COMPATIBILITY_LEVEL = (\d+)", code) == [S1_LEVEL]
    assert code.index("EXEC (@create);") < code.index("EXEC (@options);") < code.index("THROW 52110")


def test_s1_verification_52110_requires_every_pinned_setting():
    check = _s1_section("DECLARE @db_id int = DB_ID(@db);", "THROW 52110")
    for condition in ("state_desc = N'ONLINE'", "is_read_only = 0", "source_database_id IS NULL",
                      "recovery_model_desc = N'SIMPLE'", "is_read_committed_snapshot_on = 0",
                      "snapshot_isolation_state = 0", "is_auto_close_on = 0", f"compatibility_level = {S1_LEVEL}",
                      f"collation_name = N'{S1_COLLATION}'"):
        assert condition in check, condition
    assert check.count("AND") >= 8  # every condition is conjunctive, inside the one NOT EXISTS


def test_the_compatibility_decision_is_option_b_from_s0_only():
    doc = (SYNTHETIC / "PROPOSED_S1_COMPATIBILITY_LEVEL.md").read_text(encoding="ascii")
    assert doc.startswith(f"# DECIDED: option B, S1 pins compatibility level {S1_LEVEL} and collation {S1_COLLATION}")
    assert "`MedMind_Audit_Final2` was not\ninspected" in doc and "S1 has not run." in doc
    readme = (SYNTHETIC / "README.md").read_text(encoding="utf-8")
    assert f"`COMPATIBILITY_LEVEL = {S1_LEVEL}`" in readme and f"COLLATE {S1_COLLATION}" in readme
    assert f"`compatibility_level = {S1_LEVEL}`" in readme and "`is_auto_close_on = 0`" in readme


def test_the_generator_is_pinned_to_the_reviewed_sqlalchemy_version(monkeypatch):
    pins = re.findall(r"(?im)^sqlalchemy==([\w.]+)\s*$",
                      (ROOT / "Backend" / "requirements-prod.txt").read_text(encoding="utf-8"))
    assert pins == [generator.SQLALCHEMY_VERSION] and sqlalchemy.__version__ == generator.SQLALCHEMY_VERSION
    monkeypatch.setattr(generator.sqlalchemy, "__version__", "2.0.99")
    assert generator.main(["--check"]) == 2
