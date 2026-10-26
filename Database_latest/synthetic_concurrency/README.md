# Synthetic concurrency database (C1-C4), no copied data

**Status: phase P0 only, prepared and tested offline. Nothing here has ever
run against SQL Server.** Every gate below that connects needs its own
explicit approval. No gate implies the next. G3/G4 (the restored-copy
workflow in `../scratch_concurrency`) are not used, not changed and not
authorized by this.

## What it is

An empty database on `localhost\SQLEXPRESS`, named
`MedMind_SynthConc_<YYYYMMDD>_<6 lowercase hex>`, with:
- a schema generated from the SQLAlchemy models;
- a small deterministic fixture of fake rows: one provider, branch,
  specialty, service, patient (with both profiles), staff account and
  `provider_admin` membership.

The tests create everything else themselves. There is no backup file,
no restore, and no row from `MedMind_Booking_DB`, `MedMind_Audit_Final2` or
any other database.

| Piece | File |
|---|---|
| Fake fixture (single source of truth) | `Backend/tests/synthetic_fixture.py` |
| Generator (offline, models + fixture to SQL) | `Backend/tools/generate_synthetic_sql.py` (`--check` / `--write`; refuses unless SQLAlchemy is exactly the reviewed 2.0.51, the `requirements-prod.txt` pin, because it relies on private SQLAlchemy APIs) |
| Runner (the only entry point) | `Invoke-SyntheticGate.ps1` (this folder) |
| Target guard for pytest | `Backend/tests/synthetic_db_guard.py` |
| Offline tests | `Backend/tests/test_synthetic_db_offline.py`, `Backend/tests/test_synthetic_runner_offline.py` |

## Gates (each needs separate, explicit approval)

| Gate | Runner call | Effect |
|---|---|---|
| S0 | `-Gate S0 -SynthName $Synth` | read-only, master: version, default paths, `model` database settings (isolation, recovery, compatibility level, collation, user-object count), name and file availability, free space |
| S1 | `-Gate S1 -SynthName $Synth -Approved` | `CREATE DATABASE ... COLLATE SQL_Latin1_General_CP1_CI_AS`, then explicitly `RECOVERY SIMPLE`, `READ_COMMITTED_SNAPSHOT OFF`, `ALLOW_SNAPSHOT_ISOLATION OFF`, `AUTO_CLOSE OFF`, `COMPATIBILITY_LEVEL = 170`; all verified (state, recovery, isolation, `is_auto_close_on = 0`, `compatibility_level = 170`, `collation_name`, file paths) |
| S2 | `-Gate S2 -SynthName $Synth -Approved` | generated schema, one transaction, only into an empty database |
| S3 | `-Gate S3 -SynthName $Synth -TokenSha256 $TokenSha256 -Approved` | fake fixture + marker, one transaction, only into the exact empty schema |
| S4 | `-Gate S4 -SynthName $Synth -TokenSha256 $TokenSha256` | read-only proof that it is exactly the synthetic database |
| S5 | pytest (below) | C1-C4 on the synthetic database only, **after** the proposed test change |
| S6 | `-Gate S6 -SynthName $Synth -ConfirmName $Synth -TokenSha256 $TokenSha256 -Approved` | guarded drop (also of a partially created database) |

```powershell
$Runner = "<repo>\Database_latest\synthetic_concurrency\Invoke-SyntheticGate.ps1"
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Runner -Gate <gate> [-SynthName ...] [-ConfirmName ...] [-TokenSha256 ...] [-Approved] [-DryRun]
```

Run-time values are generated per run and never stored:

```powershell
$bytes = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$Token = -join ($bytes | ForEach-Object { $_.ToString("x2") })
$TokenSha256 = -join ([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::ASCII.GetBytes($Token)) | ForEach-Object { $_.ToString("x2") })
$suffix = New-Object byte[] 3; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($suffix)
$Synth = "MedMind_SynthConc_" + (Get-Date -Format yyyyMMdd) + "_" + (-join ($suffix | ForEach-Object { $_.ToString("x2") }))
```

### Approval record: the runner's own hash

```text
Invoke-SyntheticGate.ps1  SHA-256  f737a3fdb832add6063aae039d10315f7187f8e2e260b1144c95092f5dcfc1b6
```

`(Get-FileHash -Algorithm SHA256 $Runner).Hash.ToLower()` must print exactly
this value immediately before any gate. The runner pins every script.
`.gitattributes` in this folder marks `*.sql` and `*.ps1` `-text`, so git
never converts their line endings.

## Safety model

**Names.** Only `MedMind_SynthConc_<8 digits>_<6 lowercase hex>`. The
following are refused everywhere (runner, every script, pytest guard), in
any letter case:
- `MedMind_Booking_DB`, `MedMind_Audit_Final2`, `MedMind_Audit_Final`;
- anything starting with `MedMind_Audit` or `MedMind_Booking`;
- restored scratch copies, `MedMind_ConcScratch_*`.

**Positive proof that it is synthetic.** The S2-S4 scripts and the pytest
guard (`connected_problem`) require:
- `@@SERVERNAME` `LAPTOP-FACHLL1N\SQLEXPRESS`, the value every gate script
  and the runner already pin (the guard takes it from
  `generate_synthetic_sql.SERVER_NAME`);
- the exact database name;
- ONLINE, writable, not a snapshot, RCSI and snapshot isolation OFF;
- S4 and the pytest guard only: exactly two files, at exactly the S1 paths
  (`<InstanceDefaultDataPath>\<name>_data.mdf`,
  `<InstanceDefaultLogPath>\<name>_log.ldf`, read from `sys.database_files`
  and compared case-insensitively, as S1 and S6 do). This assumes the
  instance default paths have not changed since S1; if they have, the check
  refuses (fail closed), as S6 already does;
- S4 and the pytest guard only: `compatibility_level = 170` and
  `collation_name = SQL_Latin1_General_CP1_CI_AS`, the values S1 pins
  (single source: `generate_synthetic_sql.SYNTHETIC_COMPATIBILITY_LEVEL` and
  `SYNTHETIC_COLLATION`). Both are checked before the marker or any
  application table is read;
- no msdb RESTORE history for the name (a synthetic database is never
  restored, so a restored copy can never pass);
- a marker with exactly one row: this name, kind `synthetic`, fixture
  `synthetic-v1`, SHA-256 of this run's token, and the fixture's manifest
  SHA-256;
- revision `c3d9e6a2f8b1`;
- the exact generated `table.column` set;
- every seeded table holding exactly its fixture rows, and every other
  non-test table empty.

S4 additionally checks that the tables the tests write to contain only rows
the tests could have created: test doctors licensed `ZZTEST-CC-*`, the
fixture provider, patient and staff user. The pytest guard deliberately
never reads those tables on each connection, because they can be locked by
a concurrent session mid-test.

**Guard lock timeout.** The pytest guard sets `LOCK_TIMEOUT 5000`
(`GUARD_LOCK_TIMEOUT_MS`) before its first query, so a lock held elsewhere
ends in a refusal instead of an indefinite wait. Any error from a guard query
is a `SYNTHETIC SAFETY STOP`. The caller's own `LOCK_TIMEOUT` is set only after
every check has passed, so the C1-C4 timeouts are unchanged.

**Partial creation and cleanup (S6).** S2 and S3 are each one transaction,
so a database is in one of four states. S6 drops only the first three:
1. empty (S1 done, S2 not committed);
2. exact schema with no rows and no marker (S3 not committed);
3. marked with this token and the exact schema.

Anything else is refused, including a database with data but no marker, a
different schema, another token, a state other than ONLINE, a RESTORE
history, or different file paths. The inspection runs through the database's
own `sp_executesql` in TRY/CATCH; any error is a refusal carrying the
original SQL error. Files left with no database at all are a manual step
with its own approval.

## S5: running the tests (separate approval; has not run)

**Status: the guard switch is implemented and tested offline only. S5 has
not run; C1-C4 have never executed against any database, and no result is
claimed.**

`Backend/tests/test_reschedule_concurrency_scratch_db.py` selects its guard
through `Backend/tests/concurrency_target.py` (pure: reads only the
environment, never connects):
- `MEDMIND_CONCURRENCY_TARGET=synthetic`: imports `synthetic_connection`,
  `synthetic_open_transaction` and `synthetic_committing_session` from
  `tests.synthetic_db_guard` under the module's existing three names;
- `MEDMIND_CONCURRENCY_TARGET=restored`: imports the unchanged
  `tests.scratch_db_guard` functions, exactly as before.

**No default target; everything invalid fails closed.**

| Environment | Result |
|---|---|
| `MEDMIND_DB_INTEGRATION` is not `1`, or neither `MEDMIND_SYNTHETIC_CONCURRENCY=1` nor `MEDMIND_SCRATCH_CONCURRENCY=1` | every test skipped |
| opted in, `MEDMIND_CONCURRENCY_TARGET` missing, empty, or not exactly `synthetic`/`restored` (any other case or whitespace) | `SAFETY STOP` while the module is imported, before either guard is imported; nothing runs |
| both `MEDMIND_SYNTHETIC_CONCURRENCY=1` and `MEDMIND_SCRATCH_CONCURRENCY=1` | `SAFETY STOP` (ambiguous) |
| target and opt-in disagree (`synthetic` with `MEDMIND_SCRATCH_CONCURRENCY=1`, or `restored` with `MEDMIND_SYNTHETIC_CONCURRENCY=1`) | `SAFETY STOP` |

The selector only chooses which guard runs. Each guard still performs every
one of its own checks on every connection (for the synthetic guard: the
pre-connection settings and engine checks, then server, name, state, files,
compatibility level and collation, restore history, marker, token, manifest,
revision, schema and fixture counts; see "Safety model" above).

**Restored mode** now also needs `MEDMIND_CONCURRENCY_TARGET=restored` in
addition to its existing variables (`MEDMIND_SCRATCH_CONCURRENCY=1`,
`MEDMIND_SCRATCH_DB_NAME`, `MEDMIND_SCRATCH_TOKEN` and the matching
`DB_*` settings). The G3/G4 workflow and its files in `../scratch_concurrency`
are unchanged and do not mention this variable; without it, an opted-in
restored run stops with `SAFETY STOP`.

`SEED_SQL` needs no change: the guard proves exactly one row per seeded
table, so its `TOP 1` selects the fixture. The booking service under test is
given the seeded patient's `national_id_hash` directly (`FixedHashProtector`),
so the test's `NATIONAL_ID` only has to be well-formed.

**S5 environment for `MedMind_SynthConc_20261026_04dce3`** (all required;
the synthetic guard refuses anything else before connecting):
- `APP_ENV=staging` (settings then ignore any `.env` file)
- `MEDMIND_DB_INTEGRATION=1`
- `MEDMIND_CONCURRENCY_TARGET=synthetic`
- `MEDMIND_SYNTHETIC_CONCURRENCY=1`
- `MEDMIND_SYNTHETIC_DB_NAME=MedMind_SynthConc_20261026_04dce3`
- `MEDMIND_SYNTHETIC_TOKEN`: the raw run token (64 lowercase hex), loaded
  from the encrypted token file below; never printed
- `DB_SERVER=localhost\SQLEXPRESS` (the guard's approved server; it then
  requires `@@SERVERNAME` `LAPTOP-FACHLL1N\SQLEXPRESS`)
- `DB_NAME=MedMind_SynthConc_20261026_04dce3` (must equal
  `MEDMIND_SYNTHETIC_DB_NAME`)
- `DB_TRUSTED_CONNECTION=true`

Must not be set: `MEDMIND_SCRATCH_CONCURRENCY` (both opt-ins is a
`SAFETY STOP`), `MEDMIND_DB_COMMIT_TESTS`, `DOCTOR_VERIFICATION_ENFORCED`.

The token was generated for S3 and is stored DPAPI-encrypted (current
Windows user only) at
`%LOCALAPPDATA%\MedMind\synthetic_tokens\MedMind_SynthConc_20261026_04dce3.token.dpapi`.
Load it into the process environment without echoing it:

```powershell
$f = Join-Path $env:LOCALAPPDATA 'MedMind\synthetic_tokens\MedMind_SynthConc_20261026_04dce3.token.dpapi'
$env:MEDMIND_SYNTHETIC_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR((Get-Content -LiteralPath $f | ConvertTo-SecureString)))
```

Remove it afterwards (`Remove-Item Env:MEDMIND_SYNTHETIC_TOKEN`). Never
print the token or its SHA-256, and keep the file until S6 has run.

Run from `Backend\` with `.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -c pytest.ini --rootdir . -o addopts="" -v -rA tests/test_reschedule_concurrency_scratch_db.py`.

**C4** (two sessions rescheduling the same appointment) was added to that
file. Its expected outcomes come from static review of
`AppointmentService.reschedule_booking` and `AppointmentRepository` (the
derivation is in the test file). They have not been observed.

## Schema fidelity: what is NOT claimed

The schema is the models compiled with SQLAlchemy's SQL Server dialect,
pinned to modern SQL Server types (`DATE`, `TIME`, `NVARCHAR(max)`, not
`DATETIME`/`NTEXT`). It is **not** claimed to match `MedMind_Audit_Final2`.
Known and possible differences:

**Known:**
- `patient_number_sequences.year` would compile as `IDENTITY`; the generator
  removes it (`NO_IDENTITY`). The real column is unknown.
- 36 of 93 foreign keys and every default constraint are unnamed in the
  models, so SQL Server generates their names.
- Nine `DateTime` model columns compile to `DATETIME`; the real database
  may use `DATETIME2`.

**Possible, not detectable offline:**
- triggers, computed columns, views, procedures and functions;
- indexes or constraints that exist only in the database;
- different collations, column types, nullability or defaults.

Any of these could change locking and plans; the remaining risks below
include data volume. A schema-only comparison against Final2's catalog would
need its own approval, and is not part of P0.

## Syntax validation: what can and cannot be checked

No SQL in this folder has been parsed by SQL Server or by any T-SQL parser.
The offline tests check text and statement order only.

**Server-side `SET PARSEONLY ON` / `SET NOEXEC ON`.** Both need a connection,
so either would be its own gate with its own approval. Neither proves the
scripts work:
- `PARSEONLY` checks grammar only and binds no names;
- `NOEXEC` compiles without executing, but deferred name resolution leaves
  objects created in the same batch (all of S2) unchecked;
- neither looks inside dynamic SQL strings (`EXEC (@create)`,
  `EXEC (@options)`, `EXEC (@drop)`, S6's `@probe` through `sp_executesql`);
- neither evaluates a `THROW` condition, transaction behavior, permissions,
  `STRING_AGG`/`HASHBYTES` producing the offline fingerprint, or
  `sys.partitions` counts;
- the runner sends each script as one parameterized batch. How these `SET`
  options behave inside that batch would itself need confirming.

**Offline parser (proposed, not added).** Microsoft's T-SQL parser,
`Microsoft.SqlServer.TransactSql.ScriptDom.dll`, is installed on this
machine, Authenticode-signed by Microsoft:
- SSMS 22: version 18.0.105;
- Visual Studio 2022: version 16.1.

It parses text without any connection. It could check the grammar of the six
scripts and, if extracted, of the dynamic-SQL string literals. It cannot check
name binding, types, the bound `@synthetic_name`/`@token_sha256` parameters,
permissions or any runtime behavior.

Loading it was blocked by this session's permission policy, so it has not
been run. It is not confirmed which parser versions the DLL provides or
whether the scripts parse cleanly with it. Adding it needs explicit
approval; the test would skip when the DLL is absent.

## Remaining risks and open questions

- **Compatibility level and collation** are pinned by S1: level 170 and
  `SQL_Latin1_General_CP1_CI_AS` (option B in
  `PROPOSED_S1_COMPATIBILITY_LEVEL.md`), the values S0 reported for `model`
  on 2026-10-26. They are not claimed to match `MedMind_Audit_Final2`, which
  was not inspected. S4 and the pytest guard re-check both before reading
  the marker or any application table; S2 and S3 (run right after S1) do not.
- **Never executed.** Unverified at runtime:
  - DDL, `CREATE DATABASE` and `ALTER DATABASE` inside the runner's
    parameterized batch;
  - `EXEC @proc` through `[db].sys.sp_executesql`;
  - `STRING_AGG` + `HASHBYTES` matching the offline fingerprint;
  - `sys.partitions` row counts in S6.
- **Data volume.** One row per seeded table and a handful of test rows. Tiny
  tables can produce different plans, scans and lock footprints than a
  realistic database. C3 especially, which asserts that reschedule holds
  overlap, may behave differently. Open question: add deterministic filler
  rows (more doctors and slots) to the fixture?
- **The test switch** (above) is implemented and tested offline only; S5
  has not run, so C1-C4 have no observed result on this database yet.
- **Same instance as Final2.** The name rules, marker, token, manifest and
  restore-history checks are the only separation.
