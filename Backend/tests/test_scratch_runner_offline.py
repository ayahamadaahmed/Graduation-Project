"""
Offline tests of Database_latest/scratch_concurrency/Invoke-ScratchGate.ps1,
the only entry point for the scratch-database gates. No database.

What keeps these tests from connecting, and what does NOT:

- The pytest guard plugins (medmind_offline_guard, no_database_guard) only
  observe THIS Python process. They cannot see a connection made by a child
  powershell.exe, so their "0 attempts" counters are not evidence about the
  runner.
- The evidence for the runner is in the runner itself and in these tests:
  a connection object can only be created by New-GateConnection, which
  refuses during -DryRun and, because every child gets
  MEDMIND_SCRATCH_RUNNER_NO_CONNECT=1, exits 3 (backstop) instead of
  creating one, wherever it is called from; valid inputs are only run with
  -DryRun; every run asserts that the backstop never fired, so every non-dry
  run here was refused by validation first; mutated copies of the runner
  prove the two guards hold even if the call is moved before validation;
  and a module-level precondition checks the source for exactly this shape
  BEFORE any child PowerShell process is started.
- No SQL is executed by any test here. The BackupHeader comparison is
  tested by calling Get-BackupHeaderVerdict on synthetic DataTables.

Two invocation paths are exercised:
- -Command, with every value base64-decoded inside PowerShell, so quotes,
  newlines, NULs and sqlcmd syntax reach the runner byte for byte;
- -File, the documented path (README), with values passed as ordinary
  command-line arguments.
"""

import base64
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "Database_latest" / "scratch_concurrency"
RUNNER = FOLDER / "Invoke-ScratchGate.ps1"
POWERSHELL = shutil.which("powershell.exe")

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or POWERSHELL is None, reason="Windows PowerShell is required."
)

CHECKS = FOLDER / "ScratchGateChecks.ps1"
SCRATCH = "MedMind_ConcScratch_20261026_a1b2c3"
TOKEN_HASH = "0123456789abcdef" * 4
BACKUP_SET = "0f8fad5b-d9cb-469f-a165-70867728950e"
FORBIDDEN_ENV = ["SCRATCH_NAME", "CONFIRM_NAME", "TOKEN_SHA256", "EXPECTED_DB",
                 "SQLCMDSERVER", "SQLCMDDBNAME", "SQLCMDUSER", "SQLCMDPASSWORD", "SQLCMDINI"]
GATE_DATABASE = {
    "ReferenceFingerprint": "MedMind_Audit_Final2", "G3": "MedMind_Audit_Final2", "BackupHeader": "master",
    "G4": "master", "G4b": SCRATCH, "ScratchFingerprint": SCRATCH, "G5": SCRATCH, "G7": "master",
    "R1": "master", "R2": "master",
}
WRITE_GATES = {"G3", "G4", "G5", "G7", "R2"}
SCRATCH_GATES = [gate for gate in GATE_DATABASE if gate != "ReferenceFingerprint"]


def _runner_code():
    text = RUNNER.read_text(encoding="utf-8")
    text = re.sub(r"<#.*?#>", "", text, flags=re.DOTALL)
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _connection_safety_problems():
    """Static shape that makes every child process in this file safe. Checked
    before any child PowerShell is started (see the fixture below)."""
    code = _runner_code()
    problems = []
    if len(re.findall(r"SqlConnection(?!StringBuilder)\b", code)) != 1:
        problems.append("SqlConnection must appear exactly once (inside New-GateConnection)")
    if re.search(r"\.Open\(\)", code) and code.count("$connection.Open()") != len(re.findall(r"\.Open\(\)", code)):
        problems.append("only $connection.Open() may open a connection")
    try:
        start = code.index("function New-GateConnection(")
        end = code.index("\n}", start)
        body = code[start:end]
        create = body.index("New-Object System.Data.SqlClient.SqlConnection(")
        if not body.index("if ($DryRun) { Stop-Refused") < body.index("MEDMIND_SCRATCH_RUNNER_NO_CONNECT") < create:
            problems.append("New-GateConnection must check -DryRun and the backstop before creating anything")
    except ValueError as missing:
        problems.append(f"New-GateConnection is malformed: {missing}")
    calls = [m.start() for m in re.finditer(r"New-GateConnection\s+\$", code)]
    if len(calls) != 1:
        problems.append("New-GateConnection must be called exactly once")
    elif "if ($DryRun) {" not in code or calls[0] < code.index("if ($DryRun) {"):
        problems.append("the connection must be requested after the -DryRun exit")
    return problems


@pytest.fixture(scope="module", autouse=True)
def runner_is_safe_to_execute():
    # Runs before the first test of this module, i.e. before any child
    # PowerShell process. A regression stops the whole session here.
    problems = _connection_safety_problems()
    if problems:
        pytest.exit("Invoke-ScratchGate.ps1 is not safe to execute in offline tests: " + "; ".join(problems),
                    returncode=3)


def _arg(name, value):
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return f"-{name} ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}')))"


def _valid_inputs(gate):
    inputs = {}
    if gate != "ReferenceFingerprint":
        inputs["ScratchName"] = SCRATCH
    if gate in ("G7", "R2"):
        inputs["ConfirmName"] = SCRATCH
    if gate in ("G5", "G7"):
        inputs["TokenSha256"] = TOKEN_HASH
    if gate == "G4":
        inputs["BackupSetGuid"] = BACKUP_SET
    return inputs


def _child_env(extra_env):
    env = {key: value for key, value in os.environ.items()
           if key.upper() not in FORBIDDEN_ENV and not key.upper().startswith(("MEDMIND_", "DB_"))}
    env["MEDMIND_SCRATCH_RUNNER_NO_CONNECT"] = "1"
    env.update(extra_env or {})
    return env


def _checked(proc, allow_backstop=False):
    if not allow_backstop:
        assert "BACKSTOP" not in proc.stderr, "a run passed validation without -DryRun (reached the backstop)"
    return proc


def run(gate, inputs=None, *, approved=None, dry_run=True, extra_env=None, runner=RUNNER, allow_backstop=False):
    """-Command path: every value base64-decoded inside PowerShell."""
    parts = [f"& '{runner}' {_arg('Gate', gate)}"]
    for name, value in (inputs or {}).items():
        parts.append(_arg(name, value))
    if approved is None:
        approved = gate in WRITE_GATES
    if approved:
        parts.append("-Approved")
    if dry_run:
        parts.append("-DryRun")
    # Stop: a parameter-binding error (e.g. an unknown -Gate) must end the
    # command with a non-zero exit code instead of continuing to "exit".
    command = "$ErrorActionPreference = 'Stop'; " + " ".join(parts) + "; exit $LASTEXITCODE"
    return _checked(subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True, text=True, env=_child_env(extra_env), timeout=120,
    ), allow_backstop)


def run_file(arguments, *, extra_env=None):
    """-File path, exactly as README documents it."""
    return _checked(subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(RUNNER),
         *arguments],
        capture_output=True, text=True, env=_child_env(extra_env), timeout=120,
    ))


def _file_args(gate, inputs, *, approved=None, dry_run=True):
    arguments = ["-Gate", gate]
    for name, value in inputs.items():
        arguments += [f"-{name}", value]
    if approved if approved is not None else gate in WRITE_GATES:
        arguments.append("-Approved")
    if dry_run:
        arguments.append("-DryRun")
    return arguments


def _refused(proc):
    return proc.returncode == 2 and "SCRATCH RUNNER REFUSED" in proc.stderr


def _no_plan(proc):
    return "Gate:" not in proc.stdout and "DryRun: validated" not in proc.stdout


def _assert_valid_plan(proc, gate):
    assert proc.returncode == 0, proc.stderr
    assert "Server:       localhost\\SQLEXPRESS" in proc.stdout
    assert f"Database:     {GATE_DATABASE[gate]}\n" in proc.stdout.replace("\r\n", "\n")
    assert "ScriptSha256: OK" in proc.stdout
    assert "DryRun: validated; no connection created." in proc.stdout


# ============================================================ valid plans (dry run only)


@pytest.mark.parametrize("gate", list(GATE_DATABASE))
def test_valid_dry_run_fixes_server_database_and_script(gate):
    _assert_valid_plan(run(gate, _valid_inputs(gate)), gate)


@pytest.mark.parametrize("gate", list(GATE_DATABASE))
def test_valid_dry_run_through_the_documented_file_path(gate):
    _assert_valid_plan(run_file(_file_args(gate, _valid_inputs(gate))), gate)


# ============================================================ malicious and malformed names


MALICIOUS_NAMES = [
    SCRATCH + "'; DROP DATABASE [MedMind_Audit_Final2]; --",
    SCRATCH + ";DROP DATABASE MedMind_Audit_Final2",
    SCRATCH + "\n",
    SCRATCH + "\r\n",
    "\n" + SCRATCH,
    SCRATCH + "\x00",
    "$(SCRATCH_NAME)",
    SCRATCH + "$(x)",
    ":setvar SCRATCH_NAME MedMind_Audit_Final2",
    SCRATCH + "`$env:x",
    "MedMind_ConcScratch_20261026_A1B2C3",
    "MedMind_ConcScratch_٢٠٢٦١٠٢٦_a1b2c3",
    SCRATCH + " ",
    "",
    "MedMind_Booking_DB", "medmind_booking_db", "MEDMIND_BOOKING_DB",
    "MedMind_Audit_Final2", "medmind_audit_final2", "MedMind_Audit_Final",
    "MedMind_Audit_Final2_RestoreTest",
]


def _with_name(gate, name):
    inputs = _valid_inputs(gate)
    inputs["ScratchName"] = name
    if "ConfirmName" in inputs:
        inputs["ConfirmName"] = name
    return inputs


@pytest.mark.parametrize("gate", SCRATCH_GATES)
@pytest.mark.parametrize("name", MALICIOUS_NAMES)
def test_every_gate_refuses_malicious_or_protected_names_without_dry_run(gate, name):
    # Without -DryRun: the refusal must come from validation, before the plan
    # and before the backstop (asserted in run()).
    proc = run(gate, _with_name(gate, name), dry_run=False)
    assert _refused(proc) and _no_plan(proc)


@pytest.mark.parametrize("name", MALICIOUS_NAMES)
@pytest.mark.parametrize("gate", ["G7", "R2"])
def test_a_malicious_confirmation_is_refused(gate, name):
    inputs = _valid_inputs(gate)
    inputs["ConfirmName"] = name
    assert _refused(run(gate, inputs, dry_run=False))


FILE_PATH_NAMES = [
    SCRATCH + "'; DROP DATABASE [MedMind_Audit_Final2]; --",
    SCRATCH + ";DROP DATABASE MedMind_Audit_Final2",
    SCRATCH + "\n",
    "$(SCRATCH_NAME)",
    ":setvar SCRATCH_NAME MedMind_Audit_Final2",
    'MedMind_ConcScratch_20261026_a1b2c3" -Approved "',
    "MedMind_ConcScratch_20261026_A1B2C3",
    "MedMind_Booking_DB", "medmind_audit_final2",
]


@pytest.mark.parametrize("gate", SCRATCH_GATES)
@pytest.mark.parametrize("name", FILE_PATH_NAMES)
def test_every_gate_refuses_malicious_names_through_the_file_path(gate, name):
    # On the -File path, Windows command-line parsing comes first; whatever
    # value that produces must still be refused, with no plan printed.
    proc = run_file(_file_args(gate, _with_name(gate, name), dry_run=False))
    assert proc.returncode != 0 and _no_plan(proc), (proc.returncode, proc.stdout, proc.stderr)


@pytest.mark.parametrize(
    "token",
    [TOKEN_HASH.upper(), TOKEN_HASH[:-1], TOKEN_HASH + "0", TOKEN_HASH + "\n",
     TOKEN_HASH[:-1] + "'", "$(TOKEN_SHA256)", ""],
)
def test_bad_token_hashes_are_refused(token):
    assert _refused(run("G5", {"ScratchName": SCRATCH, "TokenSha256": token}, dry_run=False))
    assert _refused(run("G7", {"ScratchName": SCRATCH, "ConfirmName": SCRATCH, "TokenSha256": token},
                        dry_run=False))


@pytest.mark.parametrize("confirm", ["MedMind_ConcScratch_20261026_a1b2c4", SCRATCH.lower(), ""])
@pytest.mark.parametrize("gate", ["G7", "R2"])
def test_the_confirmation_must_equal_the_name(gate, confirm):
    inputs = {"ScratchName": SCRATCH, "ConfirmName": confirm}
    if gate == "G7":
        inputs["TokenSha256"] = TOKEN_HASH
    assert _refused(run(gate, inputs, dry_run=False))


# ============================================================ environment and gate rules


@pytest.mark.parametrize("variable", FORBIDDEN_ENV)
def test_sqlcmd_style_environment_variables_are_refused(variable):
    assert _refused(run("ReferenceFingerprint", extra_env={variable: "MedMind_Audit_Final2"}))


@pytest.mark.parametrize("variable", ["SCRATCH_NAME", "SQLCMDSERVER"])
def test_environment_injection_is_refused_on_the_file_path(variable):
    proc = run_file(_file_args("G4", _valid_inputs("G4")), extra_env={variable: "MedMind_Audit_Final2"})
    assert _refused(proc) and _no_plan(proc)


@pytest.mark.parametrize("gate", sorted(WRITE_GATES))
def test_write_gates_need_explicit_approval(gate):
    assert _refused(run(gate, _valid_inputs(gate), approved=False))


@pytest.mark.parametrize("gate", ["ReferenceFingerprint", "BackupHeader", "G4b", "ScratchFingerprint", "R1"])
def test_read_only_gates_reject_approval(gate):
    assert _refused(run(gate, _valid_inputs(gate), approved=True))


@pytest.mark.parametrize(
    "gate, extra",
    [("ReferenceFingerprint", {"ScratchName": SCRATCH}), ("G3", {"TokenSha256": TOKEN_HASH}),
     ("BackupHeader", {"ConfirmName": SCRATCH}), ("G4", {"ConfirmName": SCRATCH}),
     ("R2", {"TokenSha256": TOKEN_HASH})],
)
def test_inputs_a_gate_does_not_take_are_refused(gate, extra):
    assert _refused(run(gate, {**_valid_inputs(gate), **extra}))


@pytest.mark.parametrize("gate", ["G3; DROP DATABASE x", "Master", "G8", "'G3'"])
def test_unknown_gates_are_rejected_by_parameter_validation(gate):
    proc = run(gate, {"ScratchName": SCRATCH})
    assert proc.returncode != 0 and "Database:" not in proc.stdout


@pytest.mark.parametrize("gate", ["G3; DROP DATABASE x", "G8"])
def test_unknown_gates_are_rejected_on_the_file_path(gate):
    proc = run_file(["-Gate", gate, "-ScratchName", SCRATCH, "-DryRun"])
    assert proc.returncode != 0 and _no_plan(proc)


def test_a_missing_gate_fails_without_prompting_on_the_file_path():
    proc = run_file(["-ScratchName", SCRATCH, "-DryRun"])
    assert proc.returncode != 0 and _no_plan(proc)


def test_a_changed_script_is_refused(tmp_path):
    for item in FOLDER.iterdir():
        shutil.copy2(item, tmp_path / item.name)
    with open(tmp_path / "G7_drop_scratch.sql", "a", encoding="utf-8") as handle:
        handle.write("\n-- unreviewed change\n")

    proc = run("G7", _valid_inputs("G7"), runner=tmp_path / "Invoke-ScratchGate.ps1")

    assert _refused(proc) and "pinned SHA-256" in proc.stderr


def test_a_changed_checks_file_is_refused(tmp_path):
    for item in FOLDER.iterdir():
        shutil.copy2(item, tmp_path / item.name)
    with open(tmp_path / "ScratchGateChecks.ps1", "a", encoding="utf-8") as handle:
        handle.write("\n# unreviewed change\n")

    proc = run("BackupHeader", _valid_inputs("BackupHeader"), runner=tmp_path / "Invoke-ScratchGate.ps1")

    assert _refused(proc) and "ScratchGateChecks.ps1 does not match its pinned SHA-256" in proc.stderr


# ============================================================ G4 backup-set input


@pytest.mark.parametrize("guid", [
    "", BACKUP_SET.upper(), "{" + BACKUP_SET + "}", BACKUP_SET.replace("-", ""), BACKUP_SET[:-1],
    BACKUP_SET + "0", BACKUP_SET + "\n", BACKUP_SET[:-1] + "'", BACKUP_SET + "'; DROP DATABASE x; --",
    "$(BACKUP_SET)", "0f8fad5b-d9cb-469f-a165-70867728950g",
])
def test_g4_refuses_a_missing_or_malformed_backup_set_guid(guid):
    inputs = {**_valid_inputs("G4"), "BackupSetGuid": guid}
    proc = run("G4", inputs, dry_run=False)
    assert _refused(proc) and _no_plan(proc)


@pytest.mark.parametrize("gate", [g for g in GATE_DATABASE if g != "G4"])
def test_only_g4_takes_a_backup_set_guid(gate):
    proc = run(gate, {**_valid_inputs(gate), "BackupSetGuid": BACKUP_SET})
    assert _refused(proc) and "takes no BackupSetGuid" in proc.stderr


def test_g4_binds_the_backup_set_guid_as_a_typed_parameter():
    proc = run("G4", _valid_inputs("G4"))
    _assert_valid_plan(proc, "G4")
    assert f"Parameter:    @backup_set_guid = {BACKUP_SET}" in proc.stdout


# ============================================================ connection guards (mutated copies)


def _mutant(tmp_path, inserted_line):
    """A copy of the folder whose runner requests a connection right after
    New-GateConnection is defined, i.e. BEFORE environment checks, input
    validation and the -DryRun exit. Scripts and checks keep their pins."""
    for item in FOLDER.iterdir():
        shutil.copy2(item, tmp_path / item.name)
    runner = tmp_path / "Invoke-ScratchGate.ps1"
    text = runner.read_text(encoding="utf-8")
    anchor = "# ---------------------------------------------------------------- 1. environment"
    assert text.count(anchor) == 1
    runner.write_bytes(text.replace(anchor, inserted_line + "\n" + anchor).encode("ascii"))
    return runner


EARLY_CALL = "$null = New-GateConnection 'Data Source=invalid.offline.test;Connect Timeout=1'"


def test_an_early_connection_request_is_refused_during_dry_run(tmp_path):
    proc = run("G4", _valid_inputs("G4"), runner=_mutant(tmp_path, EARLY_CALL))
    assert proc.returncode == 2 and "a connection was requested during -DryRun" in proc.stderr
    assert _no_plan(proc)


def test_an_early_connection_request_hits_the_backstop_without_dry_run(tmp_path):
    # Invalid name as well: even past the guard, validation would refuse.
    inputs = {**_valid_inputs("G4"), "ScratchName": "MedMind_Audit_Final2"}
    proc = run("G4", inputs, dry_run=False, runner=_mutant(tmp_path, EARLY_CALL), allow_backstop=True)
    assert proc.returncode == 3 and "SCRATCH RUNNER BACKSTOP" in proc.stderr
    assert _no_plan(proc)


def test_the_safety_precondition_detects_a_misplaced_connection(monkeypatch, tmp_path):
    # The precondition reads the real runner; feed it a mutated text instead.
    mutated = RUNNER.read_text(encoding="utf-8").replace(
        "$connection = New-GateConnection $builder.ConnectionString",
        "$connection = New-Object System.Data.SqlClient.SqlConnection($builder.ConnectionString)")
    fake = tmp_path / "runner.ps1"
    fake.write_text(mutated, encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "RUNNER", fake)
    problems = _connection_safety_problems()
    assert any("exactly once" in problem for problem in problems)


# ============================================================ BackupHeader verdict (synthetic tables, no SQL)


VERDICT_HARNESS = r"""
param([string] $ChecksPath, [string] $SpecBase64)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. $ChecksPath
$spec = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($SpecBase64)) | ConvertFrom-Json
$tables = @()
foreach ($t in @($spec.tables)) {
    $dt = New-Object System.Data.DataTable
    foreach ($c in @($t.columns)) { [void]$dt.Columns.Add($c.name, [Type]$c.type) }
    foreach ($r in @($t.rows)) {
        $row = $dt.NewRow()
        foreach ($c in @($t.columns)) {
            $property = $r.PSObject.Properties[$c.name]
            if ($null -eq $property -or $null -eq $property.Value) { $row[$c.name] = [DBNull]::Value }
            else { $row[$c.name] = [System.Management.Automation.LanguagePrimitives]::ConvertTo($property.Value, [Type]$c.type) }
        }
        $dt.Rows.Add($row)
    }
    $tables += ,$dt
}
$verdict = Get-BackupHeaderVerdict -Tables $tables -ScratchName $spec.scratch `
    -SourceDatabase 'MedMind_Audit_Final2' -ServerName 'LAPTOP-FACHLL1N\SQLEXPRESS'
[pscustomobject]@{ problems = @($verdict.Problems); guid = $verdict.BackupSetGuid } | ConvertTo-Json -Compress
"""

MSDB_COLUMNS = [("backup_set_uuid", "System.Guid"), ("database_name", "System.String"),
                ("backup_type", "System.String"), ("is_copy_only", "System.Boolean"),
                ("has_backup_checksums", "System.Boolean"), ("server_name", "System.String"),
                ("media_name", "System.String")]
HEADER_COLUMNS = [("BackupSetGUID", "System.Guid"), ("DatabaseName", "System.String"),
                  ("BackupType", "System.Int16"), ("IsCopyOnly", "System.Boolean"),
                  ("HasBackupChecksums", "System.Boolean"), ("ServerName", "System.String")]
LABEL_COLUMNS = [("MediaName", "System.String")]
GOOD_MSDB = {"backup_set_uuid": BACKUP_SET.upper(), "database_name": "MedMind_Audit_Final2", "backup_type": "D",
             "is_copy_only": True, "has_backup_checksums": True, "server_name": "LAPTOP-FACHLL1N\\SQLEXPRESS",
             "media_name": SCRATCH}
GOOD_HEADER = {"BackupSetGUID": BACKUP_SET, "DatabaseName": "MedMind_Audit_Final2", "BackupType": 1,
               "IsCopyOnly": True, "HasBackupChecksums": True, "ServerName": "LAPTOP-FACHLL1N\\SQLEXPRESS"}
GOOD_LABEL = {"MediaName": SCRATCH}


def _table(columns, rows):
    return {"columns": [{"name": n, "type": t} for n, t in columns], "rows": rows}


def _verdict(tmp_path, tables):
    import json
    harness = tmp_path / "verdict_harness.ps1"
    harness.write_text(VERDICT_HARNESS, encoding="ascii")
    spec = base64.b64encode(json.dumps({"scratch": SCRATCH, "tables": tables}).encode("utf-8")).decode("ascii")
    proc = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(harness),
         "-ChecksPath", str(CHECKS), "-SpecBase64", spec],
        capture_output=True, text=True, env=_child_env(None), timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    problems = result["problems"]
    return ([problems] if isinstance(problems, str) else problems or []), result["guid"]


def _good_tables(**changes):
    msdb, header, label = dict(GOOD_MSDB), dict(GOOD_HEADER), dict(GOOD_LABEL)
    for key, value in changes.items():
        target, column = key.split("__", 1)
        {"msdb": msdb, "header": header, "label": label}[target][column] = value
    return [_table(MSDB_COLUMNS, [msdb]), _table(HEADER_COLUMNS, [header]), _table(LABEL_COLUMNS, [label])]


def test_a_matching_header_is_verified_and_returns_the_lowercase_guid(tmp_path):
    problems, guid = _verdict(tmp_path, _good_tables())
    assert problems == [] and guid == BACKUP_SET


@pytest.mark.parametrize("change, expected", [
    ({"header__BackupSetGUID": "11111111-2222-3333-4444-555555555555"}, "does not equal msdb backup_set_uuid"),
    ({"header__BackupSetGUID": None}, "BackupSetGUID is NULL"),
    ({"msdb__backup_set_uuid": None}, "backup_set_uuid is NULL"),
    ({"header__DatabaseName": "MedMind_Booking_DB"}, "DatabaseName is 'MedMind_Booking_DB'"),
    ({"msdb__database_name": "MedMind_Audit_Final"}, "database_name is 'MedMind_Audit_Final'"),
    ({"header__BackupType": 5}, "BackupType is '5'"),
    ({"msdb__backup_type": "I"}, "backup_type is 'I'"),
    ({"header__IsCopyOnly": False}, "IsCopyOnly is not 1"),
    ({"msdb__is_copy_only": False}, "is_copy_only is not 1"),
    ({"header__HasBackupChecksums": False}, "HasBackupChecksums is not 1"),
    ({"msdb__has_backup_checksums": None}, "has_backup_checksums is NULL"),
    ({"header__ServerName": "laptop-fachll1n\\sqlexpress"}, "ServerName is 'laptop-fachll1n\\sqlexpress'"),
    ({"msdb__server_name": "OTHER\\SQLEXPRESS"}, "server_name is 'OTHER\\SQLEXPRESS'"),
    ({"label__MediaName": "MedMind_ConcScratch_20261026_ffffff"}, "MediaName is 'MedMind_ConcScratch_20261026_ffffff'"),
    ({"msdb__media_name": None}, "media_name is NULL"),
])
def test_any_mismatch_or_null_fails_closed(tmp_path, change, expected):
    problems, guid = _verdict(tmp_path, _good_tables(**change))
    assert guid is None and any(expected in problem for problem in problems), problems


@pytest.mark.parametrize("index, rows", [(0, 0), (0, 2), (1, 0), (1, 2), (2, 0), (2, 2)])
def test_a_result_set_without_exactly_one_row_fails_closed(tmp_path, index, rows):
    tables = _good_tables()
    tables[index]["rows"] = tables[index]["rows"] * rows
    problems, guid = _verdict(tmp_path, tables)
    assert guid is None and any("exactly one row" in problem for problem in problems), problems


def test_a_missing_column_or_result_set_fails_closed(tmp_path):
    tables = _good_tables()
    tables[1] = _table([c for c in HEADER_COLUMNS if c[0] != "BackupSetGUID"],
                       [{k: v for k, v in GOOD_HEADER.items() if k != "BackupSetGUID"}])
    problems, guid = _verdict(tmp_path, tables)
    assert guid is None and any("no column BackupSetGUID" in problem for problem in problems), problems

    problems, guid = _verdict(tmp_path, _good_tables()[:2])
    assert guid is None and any("expected 3 result sets" in problem for problem in problems), problems


def test_the_runner_decides_backup_header_only_from_the_verdict():
    code = _runner_code()
    fill = code.index("[void]$adapter.Fill($results)")
    verdict = code.index("$verdict = Get-BackupHeaderVerdict -Tables @($results.Tables)")
    assert fill < verdict
    block = code[verdict:code.index('if ($exitCode -eq 0) { Write-Host "Gate $Gate finished." }')]
    assert "$exitCode = 4" in block and "BACKUP HEADER NOT VERIFIED" in block
    assert "Format-" not in block and "Out-String" not in block


# ============================================================ README procedures (static)


def _readme():
    return (FOLDER / "README.md").read_text(encoding="utf-8")


def test_the_g6_command_uses_no_plugin_outside_the_repository():
    readme = _readme()
    section = readme[readme.index("### G6"):readme.index("### If G3 fails")]
    command = re.search(r"```powershell\n(\S+ -B -m pytest [^\n]+)\n```", section).group(1)
    # The backend virtual environment's interpreter, relative to Backend\.
    assert command.split()[0] == ".\\.venv\\Scripts\\python.exe"
    plugins = re.findall(r"-p\s+(\S+)", command)
    assert plugins and all(plugin.startswith("no:") for plugin in plugins), plugins
    assert "medmind_offline_guard" not in readme
    assert "`APP_ENV=staging`" in section and "Run from `Backend\\`" in section
    assert (ROOT / "Backend" / command.split()[-1]).is_file()
    # Staging settings never read a .env file (code check only; no .env is read).
    config = (ROOT / "Backend" / "app" / "core" / "config.py").read_text(encoding="utf-8")
    assert "if staging_selected():\n        return Settings(_env_file=None)" in config


def test_the_g3_failure_procedure_is_manual_and_complete():
    readme = _readme()
    section = readme[readme.index("### If G3 fails"):readme.index("## Backup provenance")]
    for required in ("Nothing is deleted automatically", "do not rerun G3 with the\n   same name", "50307",
                     "-Gate R1 -ScratchName $Scratch", "separate written approval", "G8 procedure",
                     "**new** scratch name", "Final2"):
        assert required in section, required


def test_g4_is_documented_as_blocked_until_its_runtime_assumptions_are_accepted():
    readme = _readme()
    assert "**This does not provably close the race.**" in readme
    assert "**G4 therefore remains blocked**" in readme
    assert "-Gate G4 -ScratchName $Scratch -BackupSetGuid $BackupSetGuid -Approved" in readme


# ============================================================ static checks of the runner


def test_the_runner_never_starts_sqlcmd_or_substitutes_text():
    code = _runner_code()
    # "sqlcmd" may appear in refusal messages, never as a command.
    invocations = [line for line in code.splitlines()
                   if re.search(r"\bsqlcmd(\.exe)?\b", line, re.IGNORECASE) and "Stop-Refused" not in line]
    assert invocations == []
    assert not re.search(r"Invoke-Sqlcmd|Start-Process|Invoke-Expression|\biex\b|cmd(\.exe)?\s*/c",
                         code, re.IGNORECASE)
    assert "$command.CommandText = $sqlText" in code
    assert "$command.Parameters.Add($p[0], [System.Data.SqlDbType]::NVarChar, 4000)" in code
    # The SQL text is the pinned file, never combined with any caller value.
    assert len(re.findall(r"CommandText\s*=", code)) == 2  # identity query + the script
    # The only code built from text is the pinned checks file, from its hashed bytes.
    assert re.findall(r"\[scriptblock\]::Create\(([^\n]*)\)\)", code) == [
        "(New-Object System.Text.UTF8Encoding($false, $true)).GetString($checksBytes)"]
    assert code.index("$checksSha256 -cne $ChecksPinnedSha256") < code.index("[scriptblock]::Create(")


def test_the_script_is_read_once_and_the_hashed_bytes_are_executed():
    code = _runner_code()
    assert code.count("[System.IO.File]::ReadAllBytes($scriptPath)") == 1
    assert "ReadAllText" not in code and "Get-FileHash" not in code and "Get-Content" not in code
    read = code.index("$scriptBytes = [System.IO.File]::ReadAllBytes($scriptPath)")
    hashed = code.index("$hasher.ComputeHash($scriptBytes)")
    compared = code.index("$actualSha256 -cne $PinnedSha256[$config.Script]")
    decoded = code.index("$sqlText = (New-Object System.Text.UTF8Encoding($false, $true)).GetString($scriptBytes)")
    assert read < hashed < compared < decoded < code.index("$command.CommandText = $sqlText")
    assert len(re.findall(r"\$sqlText\s*=", code)) == 1


def test_validation_comes_before_the_only_connection_request():
    assert _connection_safety_problems() == []
    code = _runner_code()
    request = code.index("$connection = New-GateConnection $builder.ConnectionString")
    for marker in ("Test-Path -LiteralPath \"Env:$name\"", "Assert-ScratchName $ScratchName",
                   "-cne $ScratchName", "$TokenHashPattern", "$BackupSetPattern", "needs -Approved",
                   "pinned SHA-256", "if ($DryRun) {\n    Write-Host 'DryRun"):
        assert code.index(marker) < request, marker
    assert request < code.index("$connection.Open()")
    assert code.index("$connectedServer -cne $ExpectedServerName") < code.index("$command.CommandText = $sqlText")


def test_the_pinned_hashes_match_the_reviewed_scripts():
    text = RUNNER.read_text(encoding="utf-8")
    pinned = dict(re.findall(r"'([A-Za-z0-9_]+\.sql)'\s*=\s*'([0-9a-f]{64})'", text))
    assert set(pinned) == {path.name for path in FOLDER.glob("*.sql")}
    for name, digest in pinned.items():
        assert hashlib.sha256((FOLDER / name).read_bytes()).hexdigest() == digest, name
    checks_pin = re.findall(r"\$ChecksPinnedSha256 = '([0-9a-f]{64})'", text)
    assert checks_pin == [hashlib.sha256(CHECKS.read_bytes()).hexdigest()]


def test_the_readme_records_the_current_runner_hash():
    digest = hashlib.sha256(RUNNER.read_bytes()).hexdigest()
    readme = (FOLDER / "README.md").read_text(encoding="utf-8")
    assert re.findall(r"Invoke-ScratchGate\.ps1\s+SHA-256\s+([0-9a-f]{64})", readme) == [digest]


def test_pinned_files_are_lf_only_ascii_and_marked_minus_text():
    # Static: the bytes and the .gitattributes rules. Git itself is not run
    # (this copy is not a git repository).
    for path in [RUNNER, CHECKS, *FOLDER.glob("*.sql")]:
        data = path.read_bytes()
        assert b"\r" not in data and all(byte < 128 for byte in data), path.name
    rules = (FOLDER / ".gitattributes").read_text(encoding="utf-8").split()
    assert "*.sql" in rules and "*.ps1" in rules and rules.count("-text") == 2


def test_server_and_databases_are_fixed_in_the_runner():
    code = _runner_code()
    assert "$DataSource         = 'localhost\\SQLEXPRESS'" in code
    assert "$ExpectedServerName = 'LAPTOP-FACHLL1N\\SQLEXPRESS'" in code
    assert "$SourceDatabase     = 'MedMind_Audit_Final2'" in code
    assert "$builder.IntegratedSecurity = $true" in code
    assert "MedMind_Booking_DB" not in code.replace("medmind_booking_db", "")
