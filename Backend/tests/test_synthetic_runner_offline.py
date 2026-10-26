"""
Offline tests of Database_latest/synthetic_concurrency/Invoke-SyntheticGate.ps1.
No database, no SQL:

- the pytest guard plugins only observe THIS Python process, not the child
  powershell.exe; the evidence for the runner is that a connection object
  can only come from New-GateConnection, which refuses during -DryRun and,
  because every child gets MEDMIND_SYNTHETIC_RUNNER_NO_CONNECT=1, exits 3
  instead of creating one; valid inputs run without -DryRun only on copies
  that exit 4 just before the connection request (to check the built
  connection string), and once on the real runner for read-only S0, which
  must stop at the backstop (exit 3); every other run asserts the backstop
  never fired (so every non-dry run was refused by validation first);
  mutated copies prove the two guards hold even if the call is moved before
  validation; and a module-level precondition checks the source shape
  BEFORE any child process is started.
- every value is passed base64-encoded and decoded inside PowerShell
  (-Command path), or as ordinary arguments (-File, the documented path).
"""

import base64
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "Database_latest" / "synthetic_concurrency"
RUNNER = FOLDER / "Invoke-SyntheticGate.ps1"
POWERSHELL = shutil.which("powershell.exe")

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or POWERSHELL is None, reason="Windows PowerShell is required."
)

NAME = "MedMind_SynthConc_20261026_a1b2c3"
TOKEN_HASH = "0123456789abcdef" * 4
FORBIDDEN_ENV = ["SYNTH_NAME", "SCRATCH_NAME", "CONFIRM_NAME", "TOKEN_SHA256", "EXPECTED_DB",
                 "SQLCMDSERVER", "SQLCMDDBNAME", "SQLCMDUSER", "SQLCMDPASSWORD", "SQLCMDINI"]
GATE_DATABASE = {"S0": "master", "S1": "master", "S2": NAME, "S3": NAME, "S4": NAME, "S6": "master"}
WRITE_GATES = {"S1", "S2", "S3", "S6"}


def _runner_code(path=None):
    text = (path or RUNNER).read_text(encoding="utf-8")
    text = re.sub(r"<#.*?#>", "", text, flags=re.DOTALL)
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _connection_safety_problems(path=None):
    code = _runner_code(path)
    problems = []
    if len(re.findall(r"SqlConnection(?!StringBuilder)\b", code)) != 1:
        problems.append("SqlConnection must appear exactly once (inside New-GateConnection)")
    if code.count(".Open()") != code.count("$connection.Open()"):
        problems.append("only $connection.Open() may open a connection")
    try:
        start = code.index("function New-GateConnection(")
        body = code[start:code.index("\n}", start)]
        create = body.index("New-Object System.Data.SqlClient.SqlConnection(")
        if not body.index("if ($DryRun) { Stop-Refused") < body.index("MEDMIND_SYNTHETIC_RUNNER_NO_CONNECT") < create:
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
    # Before the first test of this module, i.e. before any child PowerShell.
    problems = _connection_safety_problems()
    if problems:
        pytest.exit("Invoke-SyntheticGate.ps1 is not safe to execute in offline tests: " + "; ".join(problems),
                    returncode=3)


def _arg(name, value):
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return f"-{name} ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}')))"


def _valid_inputs(gate):
    inputs = {"SynthName": NAME}
    if gate == "S6":
        inputs["ConfirmName"] = NAME
    if gate in ("S3", "S4", "S6"):
        inputs["TokenSha256"] = TOKEN_HASH
    return inputs


def _child_env(extra_env):
    env = {key: value for key, value in os.environ.items()
           if key.upper() not in FORBIDDEN_ENV and not key.upper().startswith(("MEDMIND_", "DB_"))}
    env["MEDMIND_SYNTHETIC_RUNNER_NO_CONNECT"] = "1"
    env.update(extra_env or {})
    return env


def _checked(proc, allow_backstop=False):
    if not allow_backstop:
        assert "BACKSTOP" not in proc.stderr, "a run passed validation without -DryRun (reached the backstop)"
    return proc


def run(gate, inputs=None, *, approved=None, dry_run=True, extra_env=None, runner=RUNNER, allow_backstop=False):
    parts = [f"& '{runner}' {_arg('Gate', gate)}"] + [_arg(k, v) for k, v in (inputs or {}).items()]
    if approved if approved is not None else gate in WRITE_GATES:
        parts.append("-Approved")
    if dry_run:
        parts.append("-DryRun")
    command = "$ErrorActionPreference = 'Stop'; " + " ".join(parts) + "; exit $LASTEXITCODE"
    return _checked(subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True, text=True, env=_child_env(extra_env), timeout=120), allow_backstop)


def run_file(arguments, *, extra_env=None):
    return _checked(subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(RUNNER), *arguments],
        capture_output=True, text=True, env=_child_env(extra_env), timeout=120))


def _file_args(gate, inputs, *, dry_run=True):
    arguments = ["-Gate", gate]
    for name, value in inputs.items():
        arguments += [f"-{name}", value]
    if gate in WRITE_GATES:
        arguments.append("-Approved")
    if dry_run:
        arguments.append("-DryRun")
    return arguments


def _refused(proc):
    return proc.returncode == 2 and "SYNTHETIC RUNNER REFUSED" in proc.stderr


def _no_plan(proc):
    return "Gate:" not in proc.stdout and "DryRun: validated" not in proc.stdout


def _assert_valid_plan(proc, gate):
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.replace("\r\n", "\n")
    assert "Server:       localhost\\SQLEXPRESS" in out
    assert f"Database:     {GATE_DATABASE[gate]}\n" in out
    assert "ScriptSha256: OK" in out and "DryRun: validated; no connection created." in out


# ============================================================ valid plans (dry run only)


@pytest.mark.parametrize("gate", list(GATE_DATABASE))
def test_valid_dry_run_fixes_server_database_and_script(gate):
    _assert_valid_plan(run(gate, _valid_inputs(gate)), gate)


@pytest.mark.parametrize("gate", list(GATE_DATABASE))
def test_valid_dry_run_through_the_documented_file_path(gate):
    _assert_valid_plan(run_file(_file_args(gate, _valid_inputs(gate))), gate)


# ============================================================ names: protected, restored, malformed


BAD_NAMES = [
    "MedMind_Booking_DB", "medmind_booking_db", "MedMind_Audit_Final2", "MEDMIND_AUDIT_FINAL2", "MedMind_Audit_Final",
    "MedMind_ConcScratch_20261026_a1b2c3",  # a restored scratch copy is never synthetic
    "MedMind_SynthConc_20261026_A1B2C3", "MedMind_SynthConc_2026102_a1b2c3", NAME + "_x", NAME + " ", "\n" + NAME,
    NAME + "'; DROP DATABASE [MedMind_Audit_Final2]; --", NAME + ";DROP DATABASE MedMind_Audit_Final2",
    "$(SYNTH_NAME)", ":setvar SYNTH_NAME MedMind_Audit_Final2", NAME + "\x00",
    "MedMind_SynthConc_٢٠٢٦١٠٢٦_a1b2c3", "",
]


def _with_name(gate, name):
    inputs = _valid_inputs(gate)
    inputs["SynthName"] = name
    if "ConfirmName" in inputs:
        inputs["ConfirmName"] = name
    return inputs


@pytest.mark.parametrize("gate", list(GATE_DATABASE))
@pytest.mark.parametrize("name", BAD_NAMES)
def test_every_gate_refuses_protected_restored_or_malformed_names_without_dry_run(gate, name):
    proc = run(gate, _with_name(gate, name), dry_run=False)
    assert _refused(proc) and _no_plan(proc)


@pytest.mark.parametrize("gate", list(GATE_DATABASE))
@pytest.mark.parametrize("name", ["MedMind_Audit_Final2", "MedMind_Booking_DB", "MedMind_ConcScratch_20261026_a1b2c3",
                                  NAME + "'; DROP DATABASE [MedMind_Audit_Final2]; --"])
def test_bad_names_are_refused_through_the_file_path(gate, name):
    proc = run_file(_file_args(gate, _with_name(gate, name), dry_run=False))
    assert _refused(proc) and _no_plan(proc), (proc.returncode, proc.stderr)
    assert "SynthName" in proc.stderr


@pytest.mark.parametrize("confirm", ["MedMind_SynthConc_20261026_a1b2c4", NAME.upper(), "MedMind_Audit_Final2", ""])
def test_s6_confirmation_must_equal_the_name(confirm):
    assert _refused(run("S6", {**_valid_inputs("S6"), "ConfirmName": confirm}, dry_run=False))


@pytest.mark.parametrize("token", [TOKEN_HASH.upper(), TOKEN_HASH[:-1], TOKEN_HASH + "0", TOKEN_HASH + "\n",
                                   TOKEN_HASH[:-1] + "'", "$(TOKEN_SHA256)", ""])
@pytest.mark.parametrize("gate", ["S3", "S4", "S6"])
def test_bad_token_hashes_are_refused(gate, token):
    assert _refused(run(gate, {**_valid_inputs(gate), "TokenSha256": token}, dry_run=False))


# ============================================================ environment and gate rules


@pytest.mark.parametrize("variable", FORBIDDEN_ENV)
def test_sqlcmd_style_environment_variables_are_refused(variable):
    assert _refused(run("S0", _valid_inputs("S0"), extra_env={variable: "MedMind_Audit_Final2"}))


def test_environment_injection_is_refused_on_the_file_path():
    proc = run_file(_file_args("S1", _valid_inputs("S1")), extra_env={"SQLCMDDBNAME": "MedMind_Audit_Final2"})
    assert _refused(proc) and _no_plan(proc)


@pytest.mark.parametrize("gate", sorted(WRITE_GATES))
def test_write_gates_need_explicit_approval(gate):
    assert _refused(run(gate, _valid_inputs(gate), approved=False))


@pytest.mark.parametrize("gate", ["S0", "S4"])
def test_read_only_gates_reject_approval(gate):
    assert _refused(run(gate, _valid_inputs(gate), approved=True))


@pytest.mark.parametrize("gate, extra", [("S0", {"TokenSha256": TOKEN_HASH}), ("S1", {"ConfirmName": NAME}),
                                         ("S2", {"TokenSha256": TOKEN_HASH}), ("S4", {"ConfirmName": NAME})])
def test_inputs_a_gate_does_not_take_are_refused(gate, extra):
    assert _refused(run(gate, {**_valid_inputs(gate), **extra}))


@pytest.mark.parametrize("gate", ["S5", "G3", "S6; DROP DATABASE x", "'S1'"])
def test_unknown_gates_are_rejected(gate):
    proc = run(gate, {"SynthName": NAME})
    # Rejected by [ValidateSet] while binding parameters: no runner code runs.
    assert proc.returncode == 1 and _no_plan(proc), (proc.returncode, proc.stderr)
    assert "ParameterArgumentValidationError" in "".join(proc.stderr.split())


def test_a_missing_gate_fails_without_prompting_on_the_file_path():
    proc = run_file(["-SynthName", NAME, "-DryRun"])
    assert proc.returncode == 1 and _no_plan(proc), (proc.returncode, proc.stderr)
    assert "MissingMandatoryParameter" in "".join(proc.stderr.split())


@pytest.mark.parametrize("gate, inputs, reason", [
    ("S1", {}, "SynthName is required for gate S1."),
    ("S0", {"SynthName": NAME, "ConfirmName": NAME}, "gate S0 takes no ConfirmName."),
    ("S6", {"SynthName": NAME, "ConfirmName": NAME}, "TokenSha256 must be exactly 64 lowercase hex characters."),
    # Protected names never match the pattern, so the pattern check refuses them first.
    ("S6", {"SynthName": NAME, "ConfirmName": "MedMind_Audit_Final2", "TokenSha256": TOKEN_HASH},
     "ConfirmName is not MedMind_SynthConc_<YYYYMMDD>_<6 lowercase hex>."),
    ("S4", {"SynthName": "MedMind_Audit_Final2", "TokenSha256": TOKEN_HASH},
     "SynthName is not MedMind_SynthConc_<YYYYMMDD>_<6 lowercase hex>."),
    ("S6", {"SynthName": NAME, "ConfirmName": NAME.replace("a1b2c3", "a1b2c4"), "TokenSha256": TOKEN_HASH},
     "ConfirmName must equal SynthName exactly."),
    ("S4", {"SynthName": NAME + "x", "TokenSha256": TOKEN_HASH},
     "SynthName is not MedMind_SynthConc_<YYYYMMDD>_<6 lowercase hex>."),
])
def test_invalid_inputs_are_refused_with_the_specific_reason(gate, inputs, reason):
    proc = run(gate, inputs, dry_run=False)
    assert _refused(proc) and _no_plan(proc), (proc.returncode, proc.stderr)
    assert f"SYNTHETIC RUNNER REFUSED: {reason}" in proc.stderr


def _copy(tmp_path):
    for item in FOLDER.iterdir():
        shutil.copy2(item, tmp_path / item.name)
    return tmp_path / "Invoke-SyntheticGate.ps1"


@pytest.mark.parametrize("script", ["S1_create_synthetic_db.sql", "S2_schema.sql", "S6_drop_synthetic_db.sql"])
def test_a_changed_script_is_refused(tmp_path, script):
    runner = _copy(tmp_path)
    with open(tmp_path / script, "a", encoding="ascii") as handle:
        handle.write("\n-- unreviewed change\n")
    gate = {"S1_create_synthetic_db.sql": "S1", "S2_schema.sql": "S2", "S6_drop_synthetic_db.sql": "S6"}[script]
    proc = run(gate, _valid_inputs(gate), runner=runner)
    assert _refused(proc) and "pinned SHA-256" in proc.stderr


# ============================================================ connection guards (mutated copies)


EARLY_CALL = "$null = New-GateConnection 'Data Source=invalid.offline.test;Connect Timeout=1'"


def _mutant(tmp_path):
    runner = _copy(tmp_path)
    text = runner.read_text(encoding="utf-8")
    anchor = "# ---------------------------------------------------------------- 1. environment"
    assert text.count(anchor) == 1
    runner.write_bytes(text.replace(anchor, EARLY_CALL + "\n" + anchor).encode("ascii"))
    return runner


def test_an_early_connection_request_is_refused_during_dry_run(tmp_path):
    proc = run("S1", _valid_inputs("S1"), runner=_mutant(tmp_path))
    assert proc.returncode == 2 and "a connection was requested during -DryRun" in proc.stderr and _no_plan(proc)


def test_an_early_connection_request_hits_the_backstop_without_dry_run(tmp_path):
    inputs = {**_valid_inputs("S6"), "SynthName": "MedMind_Audit_Final2", "ConfirmName": "MedMind_Audit_Final2"}
    proc = run("S6", inputs, dry_run=False, runner=_mutant(tmp_path), allow_backstop=True)
    assert proc.returncode == 3 and "SYNTHETIC RUNNER BACKSTOP" in proc.stderr and _no_plan(proc)


def test_the_safety_precondition_detects_a_misplaced_connection(tmp_path):
    fake = tmp_path / "runner.ps1"
    fake.write_text(RUNNER.read_text(encoding="utf-8").replace(
        "$connection = New-GateConnection $builder.ConnectionString",
        "$connection = New-Object System.Data.SqlClient.SqlConnection($builder.ConnectionString)"), encoding="utf-8")
    assert any("exactly once" in problem for problem in _connection_safety_problems(fake))


# ============================================================ connection-string construction (never connects)


CONNECTION_REQUEST = "$connection = New-GateConnection $builder.ConnectionString"
BUILT_STRING_PROBE = "[Console]::Out.WriteLine('CONNSTR=' + $builder.ConnectionString); exit 4"


def _builder_probe(tmp_path):
    """A copy that prints the built connection string and exits 4 just
    before the connection request: proves construction without relying on
    the backstop (which every child still has)."""
    runner = _copy(tmp_path)
    text = runner.read_text(encoding="utf-8")
    assert text.count(CONNECTION_REQUEST) == 1
    runner.write_bytes(text.replace(CONNECTION_REQUEST, BUILT_STRING_PROBE + "\n" + CONNECTION_REQUEST).encode("ascii"))
    return runner


def _expected_connection_string(gate):
    expected = {"Data Source": "localhost\\SQLEXPRESS", "Initial Catalog": GATE_DATABASE[gate],
                "Integrated Security": "True", "Encrypt": "True", "TrustServerCertificate": "True",
                "Pooling": "False", "Application Name": "MedMind-SyntheticGateRunner", "Connect Timeout": "15"}
    if gate not in WRITE_GATES:
        expected["ApplicationIntent"] = "ReadOnly"
    return expected


@pytest.mark.parametrize("gate", list(GATE_DATABASE))
def test_valid_inputs_build_exactly_the_expected_connection_string(tmp_path, gate):
    proc = run(gate, _valid_inputs(gate), dry_run=False, runner=_builder_probe(tmp_path))
    assert proc.returncode == 4, (proc.returncode, proc.stderr)
    lines = [line for line in proc.stdout.splitlines() if line.startswith("CONNSTR=")]
    assert len(lines) == 1, proc.stdout
    built = dict(part.split("=", 1) for part in lines[0][len("CONNSTR="):].split(";"))
    assert built == _expected_connection_string(gate)


def test_a_valid_non_dry_run_reaches_the_backstop_after_building_the_connection_string():
    # The real, pinned runner; S0 is read-only and the backstop (checked by the
    # module precondition) exits 3 before any connection object exists.
    proc = run("S0", _valid_inputs("S0"), dry_run=False, allow_backstop=True)
    assert proc.returncode == 3, (proc.returncode, proc.stderr)
    assert "SYNTHETIC RUNNER BACKSTOP: connection blocked (offline test)." in proc.stderr
    assert "Keyword not supported" not in proc.stderr and "Exception" not in proc.stderr
    assert "ScriptSha256: OK" in proc.stdout and "DryRun" not in proc.stdout


def test_the_backstop_check_detects_the_property_style_builder_bug(tmp_path):
    # The S0 failure of 2026-10-26: `$builder.DataSource = ...` throws under
    # Windows PowerShell before the connection request. Reproduced on a copy.
    runner = _copy(tmp_path)
    text = runner.read_text(encoding="utf-8")
    assert text.count("$builder['Data Source'] = $DataSource") == 1
    runner.write_bytes(text.replace("$builder['Data Source'] = $DataSource", "$builder.DataSource = $DataSource")
                       .encode("ascii"))
    proc = run("S0", _valid_inputs("S0"), dry_run=False, runner=runner)
    assert proc.returncode == 1 and "Keyword not supported: 'DataSource'" in proc.stderr, (proc.returncode, proc.stderr)
    assert "BACKSTOP" not in proc.stderr  # so the regression test above (exit 3) would fail on this code


def test_the_builder_is_never_assigned_through_properties():
    code = _runner_code()
    assert not re.findall(r"\$builder\.\w+\s*=", code)
    assert code.count("$builder['") == 9


# ============================================================ static checks of the runner


def test_the_runner_never_starts_sqlcmd_or_substitutes_text():
    code = _runner_code()
    assert not [line for line in code.splitlines()
                if re.search(r"\bsqlcmd(\.exe)?\b", line, re.IGNORECASE) and "Stop-Refused" not in line]
    assert not re.search(r"Invoke-Sqlcmd|Start-Process|Invoke-Expression|\biex\b|cmd(\.exe)?\s*/c|scriptblock",
                         code, re.IGNORECASE)
    assert len(re.findall(r"CommandText\s*=", code)) == 2  # identity query + the pinned script
    assert "$command.Parameters.Add($p[0], [System.Data.SqlDbType]::NVarChar, 4000)" in code


def test_the_script_is_read_once_and_the_hashed_bytes_are_executed():
    code = _runner_code()
    assert code.count("[System.IO.File]::ReadAllBytes($scriptPath)") == 1
    assert "ReadAllText" not in code and "Get-FileHash" not in code and "Get-Content" not in code
    order = ["$scriptBytes = [System.IO.File]::ReadAllBytes($scriptPath)", "$hasher.ComputeHash($scriptBytes)",
             "$actualSha256 -cne $PinnedSha256[$config.Script]",
             "$sqlText = (New-Object System.Text.UTF8Encoding($false, $true)).GetString($scriptBytes)",
             "$command.CommandText = $sqlText"]
    positions = [code.index(marker) for marker in order]
    assert positions == sorted(positions)


def test_validation_comes_before_the_only_connection_request():
    assert _connection_safety_problems() == []
    code = _runner_code()
    request = code.index("$connection = New-GateConnection $builder.ConnectionString")
    for marker in ("Test-Path -LiteralPath \"Env:$name\"", "Assert-SynthName $SynthName", "-cne $SynthName",
                   "$TokenHashPattern", "needs -Approved", "pinned SHA-256", "if ($DryRun) {\n    Write-Host 'DryRun"):
        assert code.index(marker) < request, marker
    assert code.index("$connectedServer -cne $ExpectedServerName") < code.index("$command.CommandText = $sqlText")


def test_server_prefixes_and_isolation_from_the_restored_runner_are_fixed():
    code = _runner_code()
    assert "$DataSource         = 'localhost\\SQLEXPRESS'" in code
    assert "$ExpectedServerName = 'LAPTOP-FACHLL1N\\SQLEXPRESS'" in code
    assert "$ProtectedPrefixes  = @('medmind_audit', 'medmind_booking', 'medmind_concscratch')" in code
    assert "$builder['Integrated Security'] = $true" in code
    for other in ("Invoke-ScratchGate", "G3_", "G4_", "G7_", "R2_", "ScratchGateChecks", ".."):
        assert other not in code, other
