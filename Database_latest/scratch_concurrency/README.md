# Scratch database for cross-session concurrency tests (C1-C3)

**Status: prepared offline. Nothing here has been run.** Every gate below
that writes or deletes needs its own explicit approval. No gate implies the
next.

## Why

The rescheduling cross-session cases (two reschedules racing for one slot;
reschedule vs a committed doctor rejection; deadlock and lock-timeout
behavior) need rows that are **committed** before the test, so that two
connections see them. They must not be committed in `MedMind_Audit_Final2`.
They run only on a disposable copy that is dropped afterwards.

## The only entry point: `Invoke-ScratchGate.ps1`

Do **not** run any `.sql` file here with `sqlcmd`, SSMS or any other tool.
`sqlcmd -v` substitutes values into the script text before SQL Server parses
it, so a quote in a value would become SQL before any check runs. The
scripts no longer contain `$(...)` placeholders; they only work through the
runner, which:

- refuses to start if `SCRATCH_NAME`, `CONFIRM_NAME`, `TOKEN_SHA256`,
  `EXPECTED_DB` or any `SQLCMD*` environment variable exists;
- validates every input first with full-string patterns (`\A...\z`) and the
  protected-name denylist; anything invalid stops it before a connection
  object is created;
- fixes the server (`localhost\SQLEXPRESS`), the database and the script for
  each gate; callers cannot pass a server, a database, a path or a script;
- reads each script once as bytes, checks those bytes against a pinned
  SHA-256, and executes the text decoded from the same bytes;
- connects with .NET `SqlClient` (Windows authentication, no pooling), then
  requires `DB_NAME()` and `@@SERVERNAME` (`LAPTOP-FACHLL1N\SQLEXPRESS`) to
  be exactly as expected. Read-only gates are read-only because their
  pinned scripts contain only SELECT/inspection statements. The runner also
  sets `ApplicationIntent=ReadOnly` for them, but on a standalone Express
  instance that is only a routing hint and enforces nothing;
- sends the fixed script text with values only as typed `SqlParameter`s
  (`@scratch_name`, `@confirm_name`, `@token_sha256`, `@backup_set_guid`,
  `@expected_db`);
- creates a connection object only in `New-GateConnection`. That function
  refuses during `-DryRun` and when the offline-test backstop is set,
  wherever it is called from;
- loads its check functions from `ScratchGateChecks.ps1`, pinned by SHA-256
  inside the runner and executed from exactly the hashed bytes;
- requires `-Approved` for every writing gate; `-DryRun` validates and
  prints the plan without connecting.

```powershell
$Runner = "<repo>\Database_latest\scratch_concurrency\Invoke-ScratchGate.ps1"
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Runner -Gate <gate> [-ScratchName ...] [-ConfirmName ...] [-TokenSha256 ...] [-Approved] [-DryRun]
```

### Approval record: the runner's own hash

The runner pins the scripts, but nothing pins the runner. Every gate
approval must record this hash and check it immediately before the run:

```text
Invoke-ScratchGate.ps1  SHA-256  f9466ca17101b3377ac1694ec55a949036fe98bf56fbb834571307551afc9078
```

`(Get-FileHash -Algorithm SHA256 $Runner).Hash.ToLower()` must print exactly
this value. Any change to the runner must update this line in the same
reviewed change (an offline test enforces that they agree).

### Line endings

All scripts, `ScratchGateChecks.ps1` and the runner are LF-only ASCII, and
their pins are over those exact bytes. `.gitattributes` in this folder marks
`*.sql` and `*.ps1` as `-text`, so git does not convert them (for example
with `core.autocrlf=true`). This is not verifiable here because this copy is
not a git repository, and editors or copy tools can still change the files.
If a checkout still changes them, the runner refuses every gate; restore
the exact bytes rather than updating pins.

## Names and protected databases

- Scratch name: `MedMind_ConcScratch_<YYYYMMDD>_<6 lowercase hex>` (35 ASCII
  characters), for example `MedMind_ConcScratch_20261026_a1b2c3`.
- Never a target, in any letter case: `MedMind_Booking_DB`,
  `MedMind_Audit_Final2`, `MedMind_Audit_Final`, and anything starting with
  `MedMind_Audit` or `MedMind_Booking`.
- The source keeps the **logical file names** `MedMind_Booking_DB` /
  `MedMind_Booking_DB_log`. They are file labels only; G4 maps them to new
  physical files `<scratch>_data.mdf` / `<scratch>_log.ldf`. No check treats
  them as a database name.

## Run-time values (per run, never stored in the repository)

```powershell
$bytes = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$Token = -join ($bytes | ForEach-Object { $_.ToString("x2") })                       # 64 lowercase hex
$TokenSha256 = -join ([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::ASCII.GetBytes($Token)) |
                      ForEach-Object { $_.ToString("x2") })
$suffix = New-Object byte[] 3; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($suffix)
$Scratch = "MedMind_ConcScratch_" + (Get-Date -Format yyyyMMdd) + "_" + (-join ($suffix | ForEach-Object { $_.ToString("x2") }))
```

The runner re-validates `$Scratch` and `$TokenSha256` itself.

## Gates (each needs separate, explicit approval)

| Gate | Runner call | Effect |
|---|---|---|
| before G3 | `-Gate ReferenceFingerprint` (+ reviewed state snapshot) | read-only Final2 reference |
| G3 | `-Gate G3 -ScratchName $Scratch -Approved` | one `.bak` (COPY_ONLY, CHECKSUM, media name = `$Scratch`) of Final2; on failure see "If G3 fails" |
| G3 check | `-Gate BackupHeader -ScratchName $Scratch` | read-only; compared automatically, prints `-BackupSetGuid`; see "Backup provenance" |
| G4 | `-Gate G4 -ScratchName $Scratch -BackupSetGuid $BackupSetGuid -Approved` | restore as the scratch name (never REPLACE), bound to the verified backup set |
| G4 check | `-Gate G4b -ScratchName $Scratch`, then `-Gate ScratchFingerprint -ScratchName $Scratch` | read-only; must equal the Final2 reference |
| G5 | `-Gate G5 -ScratchName $Scratch -TokenSha256 $TokenSha256 -Approved` | marker table, one row (hash only) |
| G6 | pytest, see below | C1-C3 on the scratch copy only |
| G7 | `-Gate G7 -ScratchName $Scratch -ConfirmName $Scratch -TokenSha256 $TokenSha256 -Approved` | drops the marked scratch copy |
| G8 | manual `Remove-Item -LiteralPath "<default backup path>\$Scratch.bak"` | removes the `.bak` |

### G6

Set these variables in the test process only:
- `APP_ENV=staging`. In staging the settings never load a `.env` file
  (`app/core/config.py`, `get_settings`).
- `MEDMIND_DB_INTEGRATION=1`, `MEDMIND_SCRATCH_CONCURRENCY=1`
- `MEDMIND_SCRATCH_DB_NAME=$Scratch`, `MEDMIND_SCRATCH_TOKEN=$Token`
- `DB_SERVER=localhost\SQLEXPRESS`, `DB_NAME=$Scratch`,
  `DB_TRUSTED_CONNECTION=true`

Never set `MEDMIND_DB_COMMIT_TESTS` or `DOCTOR_VERIFICATION_ENFORCED`.

Run from `Backend\`, with the backend virtual environment's Python
(`Backend\.venv\Scripts\python.exe`; the system Python lacks the backend's
dependencies) and no plugins beyond the repository's own:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -c pytest.ini --rootdir . -o addopts="" -v -rA --tb=long tests/test_reschedule_concurrency_scratch_db.py
```

The target guard in `tests/scratch_db_guard.py` (the scratch name, marker
and token checks) stays in force. Final2 snapshots before G3 and after
G7/G8 must be identical.

### If G3 fails

G3 can fail after creating the file: a `BACKUP` error part-way, or a
`RESTORE VERIFYONLY` error after a complete backup. The runner then exits 1
with the original SQL error. Nothing is deleted automatically. Then:

1. **Stop.** Do not run BackupHeader or G4, and do not rerun G3 with the
   same name (it refuses with 50307 because the file exists).
2. **Record** the runner output: the SQL error number and message.
3. **Inspect read-only** (R1, needs its own approval):
   `-Gate R1 -ScratchName $Scratch`. It must show:
   - no database with that name;
   - no restore history for it;
   - whether `<default backup path>\$Scratch.bak` exists.
4. **Treat the file as sensitive.** A partial or unverified `.bak` can still
   hold Final2 data.
5. **Remove the file (separate written approval).** Use the G8 procedure,
   naming exactly `<default backup path>\$Scratch.bak`, and only after R1
   showed that no database or restore history refers to it. msdb backup
   history rows, if any, are left in place.
6. **Check Final2.** The reference fingerprint and state snapshot must
   still be unchanged (G3 only reads Final2).
7. **Any retry** is a new G3 approval with a **new** scratch name.

## Backup provenance (between G3 and G4)

### BackupHeader: automatic comparison

`-Gate BackupHeader -ScratchName $Scratch` (read-only, master) returns three
result sets:
1. every msdb record for that exact path, with its media set name;
2. the file's own header (`RESTORE HEADERONLY`);
3. the file's media label (`RESTORE LABELONLY`).

The runner compares them itself (`Get-BackupHeaderVerdict` in the pinned
`ScratchGateChecks.ps1`). It does not use the printed tables, which are for
display only. The gate exits 4 (`BACKUP HEADER NOT VERIFIED`) unless:
- each result set has exactly one row, with no NULL and no missing column;
- the header's `BackupSetGUID` equals msdb's `backup_set_uuid`;
- `DatabaseName` and `database_name` are `MedMind_Audit_Final2`;
- `BackupType` is 1 and `backup_type` is `D`;
- `IsCopyOnly`, `is_copy_only`, `HasBackupChecksums` and
  `has_backup_checksums` are all 1;
- `ServerName` and `server_name` are `LAPTOP-FACHLL1N\SQLEXPRESS`;
- `MediaName` and msdb `media_name` both equal `$Scratch`.

On success it prints `BACKUP HEADER VERIFIED: -BackupSetGuid <guid>`. That
exact value goes into the G4 approval and the G4 call.

### G4 binding to the verified backup set

The gap between BackupHeader and G4 is narrowed by three checks:
1. **Before the restore**, msdb's record for the file must be that backup
   set (`@backup_set_guid`) with media name `$Scratch` (50413/50414).
2. **During the restore**, G4 uses `RESTORE ... WITH MEDIANAME = $Scratch`.
   SQL Server itself then refuses a file at that path whose media set has
   another name.
3. **After the restore**, the latest msdb restore history row for
   `$Scratch` must reference the approved backup set. Otherwise 50415 says
   the copy must not be used; inspect it with R1.

**This does not provably close the race.** Remaining limits:
- Someone with write access to the backup folder who can also create a
  backup with the same media name (a SQL Server backup right, not just file
  access) could still place a different file there between BackupHeader and
  G4. Check 2 would not notice.
- Check 3 detects a different backup set only if SQL Server records the
  restored file's own set in the restore history (runtime assumption, not
  observed).
- If check 3 fails, the database has already been restored. Nothing is
  dropped automatically; it goes to R1 and review.
- `MEDIANAME` enforcement at restore time, and `RESTORE HEADERONLY` /
  `LABELONLY` writing nothing, are documented SQL Server behavior but have
  not been observed on this server.

**G4 therefore remains blocked** until these runtime assumptions are
accepted in writing, or observed, as part of its own approval.

## Recovery: a partial restore or an unmarked copy (R1, R2, manual)

G7 refuses a copy whose marker cannot be read or does not match. Its
refusal (50710) includes the original SQL error number and message. Never
improvise a `DROP`.

1. **R1 (read-only)**: `-Gate R1 -ScratchName $Scratch`. It reports:
   - the database row and state;
   - its files, and whether they are exactly the G4 paths;
   - files on disk at those paths, and any other database using them;
   - the msdb restore history for that name;
   - the marker status (`PRESENT`, `absent` or `UNKNOWN`) and a next step.

   R1 says "R2 may be considered" **only** for an ONLINE copy whose marker
   probe succeeded and found no marker. For `PRESENT` it says G7. For
   `UNKNOWN` (not online, or the probe failed) it recommends nothing:
   manual review.
2. **R2 (destructive)**, only after R1 was reviewed:
   `-Gate R2 -ScratchName $Scratch -ConfirmName $Scratch -Approved`. It does
   not need a marker, but it drops only if all of these hold:
   - the exact scratch name, and not a protected name;
   - exactly one database with that exact name, not a snapshot;
   - state ONLINE, RESTORING, RECOVERY_PENDING or SUSPECT (OFFLINE is
     refused: dropping it would leave its files);
   - exactly two files at exactly the G4 paths, and no other database on
     those paths;
   - the latest msdb restore into that name is a FULL restore from
     `<backup path>\<name>.bak`, which is a FULL, COPY_ONLY, checksummed
     backup of `MedMind_Audit_Final2` from this server;
   - if ONLINE, a guarded probe of the copy's `sys.tables` succeeds and
     finds no `zz_scratch_marker` table. A marker means "use G7" (51212).
     An unreadable marker status is refused (51214) and never treated as
     "unmarked".

   For RESTORING, RECOVERY_PENDING and SUSPECT the copy cannot be opened,
   so the marker is not consulted; only the provenance checks apply.
3. **Not automated: a failed restore with no msdb restore history (U1).**
   R2 relies on `msdb.dbo.restorehistory`. Whether SQL Server writes that
   row for a `RESTORE` that failed part-way has **not** been verified, and
   it probably does not. In that case R2 refuses (51211) by design; its
   checks are not weakened for this case. Recovery is then manual and needs
   its own written review and approval, based on R1's output:
   - the exact name;
   - the state (typically RESTORING);
   - both files at exactly the G4 paths, used by no other database;
   - `create_date` after the G3 backup.

   A reviewer then drops that one database by hand. It is not an
   automatically supported case.
4. **R3 (manual, separately approved)**: data or log files left on disk with
   no database (a restore that failed before the database was registered,
   or a drop that left files). R1 shows them. Remove only those exact paths,
   and only after R1 shows that no database references them.

## Privacy

See `MASKING_PROPOSAL.md`. All five **mandatory** decisions in its section B
must be made before G3:
- B.1, whether a full, unmasked copy may exist at all;
- B.2, retention of the `.bak` and the copy;
- B.3, staff credentials (`user_accounts.password_hash`);
- B.4, national-ID protection (keys held on the same machine);
- B.5, access and output.

Masking itself is optional.

## Before G3 (checklist)

G3 must not be approved until every item is recorded in writing:

- [ ] **Privacy:** decisions B.1-B.5 in `MASKING_PROPOSAL.md` are made.
- [ ] **G3 runtime assumptions accepted.** None of these has been observed
  on this server:
  - `BACKUP DATABASE ... WITH COPY_ONLY, CHECKSUM, FORMAT, INIT,
    MEDIANAME = @scratch` and `RESTORE VERIFYONLY` run inside the
    parameterized batch the runner sends (`sp_executesql`);
  - `sys.dm_os_file_exists` reports the default backup folder as a
    directory (otherwise G3 refuses with 50306);
  - the SQL Server service account can write to that folder.

  Also accept the "If G3 fails" procedure.
- [ ] **Runner hash verified** immediately before the run:
  `(Get-FileHash -Algorithm SHA256 $Runner).Hash.ToLower()` equals the
  value under "Approval record". The recorded value is included in the
  approval.
- [ ] **Final2 reference taken:** `-Gate ReferenceFingerprint` and the
  reviewed state snapshot, for comparison after G7/G8.

## Residual risks

- The login is sysadmin: these checks are the only barrier. Every write
  gate needs its own approval and a second reviewer.
- Backup-folder write access is unverified until G3 itself runs.
- Restore provenance: BackupHeader compares the file and msdb
  automatically. G4 is bound to the verified backup set by msdb checks,
  `MEDIANAME` and a post-restore history check, but the window between
  them is narrowed, not provably closed (see "G4 binding to the verified
  backup set").
- `ALTER DATABASE ... SET SINGLE_USER` then `DROP` can be interrupted by
  another connection taking the single slot. The drop then fails safely and
  the copy is left `SINGLE_USER`. Rerun the same gate once that session has
  gone. While it holds the slot, G7 refuses with 50710 (the original error,
  typically 924), and R2 refuses an ONLINE copy with 51214.
- None of the gates has ever run. Every SQL behavior above is designed and
  statically tested only (see the offline tests); runtime behavior on this
  server is unverified.
