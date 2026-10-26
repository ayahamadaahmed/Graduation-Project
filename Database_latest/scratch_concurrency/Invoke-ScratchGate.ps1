<#
.SYNOPSIS
    The ONLY entry point for the MedMind scratch-database gates.

.DESCRIPTION
    Gates: ReferenceFingerprint, G3, BackupHeader, G4, G4b, ScratchFingerprint,
    G5, G7, R1, R2.

    Why not sqlcmd: sqlcmd -v substitutes values into the script TEXT before
    SQL Server parses it, so any validation inside the script runs too late
    (a quote in a value would already have become SQL). This runner never
    starts sqlcmd and never puts a caller value into SQL text:

      - every caller input is validated first, by full-string patterns
        (\A...\z) and the protected-name denylist; anything invalid stops
        the runner before a connection object is even created;
      - environment variables that sqlcmd would read (SCRATCH_NAME,
        CONFIRM_NAME, TOKEN_SHA256, EXPECTED_DB, SQLCMD*) must not exist;
      - the server, the database and the script for each gate are fixed
        here; callers cannot choose a server, a database, a script, a path
        or a variable name;
      - each script is a fixed reviewed file next to this runner, read ONCE
        as bytes; those exact bytes are hashed against a pinned SHA-256 and
        the executed text is decoded from the same bytes (strict UTF-8);
      - values reach SQL Server only as typed SqlParameter values
        (nvarchar(4000)) bound to @scratch_name, @confirm_name,
        @token_sha256, @backup_set_guid and @expected_db; inside the
        scripts, identifiers are only ever built with QUOTENAME() from
        validated values;
      - a connection object is only ever created by New-GateConnection,
        which refuses during -DryRun and when the offline-test backstop is
        set, wherever it is called from;
      - after connecting, DB_NAME() and @@SERVERNAME must be exactly the
        expected values, or nothing is executed;
      - BackupHeader results are compared by Get-BackupHeaderVerdict
        (ScratchGateChecks.ps1, pinned like the scripts); the gate fails
        (exit 4) unless the file's header, its media label and the msdb
        record all match. Its verified BackupSetGUID is G4's -BackupSetGuid.

    Write gates (G3, G4, G5, G7, R2) also need -Approved. -DryRun validates
    everything and prints the plan without creating any connection.

    Read-only gates are read-only because their pinned scripts contain only
    SELECT/inspection statements (checked by the offline tests). The
    ApplicationIntent=ReadOnly setting below is only a routing hint; on a
    standalone SQL Server Express instance it enforces nothing.

    This runner is itself not pinned by anything it runs: its SHA-256 is
    recorded in README.md and must be checked as part of every gate approval.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('ReferenceFingerprint', 'G3', 'BackupHeader', 'G4', 'G4b', 'ScratchFingerprint', 'G5', 'G7', 'R1', 'R2')]
    [string] $Gate,
    [string] $ScratchName = '',
    [string] $ConfirmName = '',
    [string] $TokenSha256 = '',
    [string] $BackupSetGuid = '',
    [switch] $Approved,
    [switch] $DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------- fixed, reviewed configuration
$DataSource         = 'localhost\SQLEXPRESS'
$ExpectedServerName = 'LAPTOP-FACHLL1N\SQLEXPRESS'
$SourceDatabase     = 'MedMind_Audit_Final2'
$ScratchPattern     = '\AMedMind_ConcScratch_[0-9]{8}_[0-9a-f]{6}\z'
$TokenHashPattern   = '\A[0-9a-f]{64}\z'
$BackupSetPattern   = '\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\z'
$ProtectedNames     = @('medmind_booking_db', 'medmind_audit_final2', 'medmind_audit_final')
$ProtectedPrefixes  = @('medmind_audit', 'medmind_booking')
$ForbiddenEnvironment = @(
    'SCRATCH_NAME', 'CONFIRM_NAME', 'TOKEN_SHA256', 'EXPECTED_DB',
    'SQLCMDSERVER', 'SQLCMDDBNAME', 'SQLCMDUSER', 'SQLCMDPASSWORD', 'SQLCMDINI'
)

$GateTable = @{
    ReferenceFingerprint = @{ Script = 'fingerprint_readonly.sql';         Database = 'source';  Writes = $false; Inputs = @() }
    G3                   = @{ Script = 'G3_backup_copy_only.sql';          Database = 'source';  Writes = $true;  Inputs = @('scratch') }
    BackupHeader         = @{ Script = 'G3b_backup_header_readonly.sql';   Database = 'master';  Writes = $false; Inputs = @('scratch') }
    G4                   = @{ Script = 'G4_restore_scratch.sql';           Database = 'master';  Writes = $true;  Inputs = @('scratch', 'backupset') }
    G4b                  = @{ Script = 'G4b_verify_scratch_readonly.sql';  Database = 'scratch'; Writes = $false; Inputs = @('scratch') }
    ScratchFingerprint   = @{ Script = 'fingerprint_readonly.sql';         Database = 'scratch'; Writes = $false; Inputs = @('scratch') }
    G5                   = @{ Script = 'G5_create_marker.sql';             Database = 'scratch'; Writes = $true;  Inputs = @('scratch', 'token') }
    G7                   = @{ Script = 'G7_drop_scratch.sql';              Database = 'master';  Writes = $true;  Inputs = @('scratch', 'confirm', 'token') }
    R1                   = @{ Script = 'R1_recovery_inspect_readonly.sql'; Database = 'master';  Writes = $false; Inputs = @('scratch') }
    R2                   = @{ Script = 'R2_drop_unmarked_scratch.sql';     Database = 'master';  Writes = $true;  Inputs = @('scratch', 'confirm') }
}

# SHA-256 of each reviewed script. Any change to a script must be reviewed
# and this table updated in the same change.
$PinnedSha256 = @{
    'fingerprint_readonly.sql'         = 'e7c9b15f01011b7cef03cdaa59cc2e416f315304110e72cc450b8b22bdcfe5eb'
    'G3_backup_copy_only.sql'          = '4cf89646ad283a9705d66f5f13abf8df914c9abfc6f9d51d9706f252c7cba1ac'
    'G3b_backup_header_readonly.sql'   = '644b53830751e92084fb0e399fb523cd1150d9f0d087b07b3f94783eb8becdc6'
    'G4_restore_scratch.sql'           = 'be762e59d458f53333855656da3b13768592e6748e4d08001bbaa426ed6000f4'
    'G4b_verify_scratch_readonly.sql'  = '64e57607a8fc2bcd8180a2a75f37979456a8beae9b0003d1b8f490f9ede068ec'
    'G5_create_marker.sql'             = '43a28db15932e178de2ebacb756a9b3401bf2fbe9a8a5ccc3fb4a3438e6eab92'
    'G7_drop_scratch.sql'              = 'e9354119d4c64f251f6bed6a4d5694d039bce8f77f164c9f945e38ebafcc55fa'
    'R1_recovery_inspect_readonly.sql' = 'eef78aa8788a04a7e9d1ac092c11209c4cabc6a0feadb822cff18ec53daa150a'
    'R2_drop_unmarked_scratch.sql'     = '437aaf3191502ac3d223ed6702921a8f71f040bce329debc79415891e0029c92'
}
# SHA-256 of ScratchGateChecks.ps1 (pure check functions; dot-sourced from these bytes).
$ChecksPinnedSha256 = '41d03f195ea7c6bb529e84a0aaa7d9a62da1beb230347fb043432e8626351404'

function Stop-Refused([string] $Reason) {
    [Console]::Error.WriteLine("SCRATCH RUNNER REFUSED: $Reason")
    exit 2
}

# The ONLY place a connection object is created. Its guards do not depend
# on where it is called from: a -DryRun run, or an offline test (backstop
# set), can never get a connection even if a later change moved the call
# before validation or before the DryRun exit.
function New-GateConnection([string] $ConnectionString) {
    if ($DryRun) { Stop-Refused 'internal: a connection was requested during -DryRun.' }
    if ($env:MEDMIND_SCRATCH_RUNNER_NO_CONNECT -eq '1') {
        [Console]::Error.WriteLine('SCRATCH RUNNER BACKSTOP: connection blocked (offline test).')
        exit 3
    }
    return New-Object System.Data.SqlClient.SqlConnection($ConnectionString)
}

function Assert-ScratchName([string] $Value, [string] $Label) {
    if ([string]::IsNullOrEmpty($Value)) { Stop-Refused "$Label is required for gate $Gate." }
    if (-not [regex]::IsMatch($Value, $ScratchPattern)) {
        Stop-Refused "$Label is not MedMind_ConcScratch_<YYYYMMDD>_<6 lowercase hex>."
    }
    $folded = $Value.ToLowerInvariant()
    if ($ProtectedNames -contains $folded) { Stop-Refused "$Label is a protected database name." }
    foreach ($prefix in $ProtectedPrefixes) {
        if ($folded.StartsWith($prefix, [StringComparison]::Ordinal)) { Stop-Refused "$Label is a protected database name." }
    }
}

# ---------------------------------------------------------------- 1. environment
foreach ($name in $ForbiddenEnvironment) {
    if (Test-Path -LiteralPath "Env:$name") {
        Stop-Refused "environment variable $name must not exist (sqlcmd-style values are never accepted)."
    }
}

# ---------------------------------------------------------------- 2. inputs (all validated before anything else)
$config = $GateTable[$Gate]
$needs = $config.Inputs

if ($needs -contains 'scratch') { Assert-ScratchName $ScratchName 'ScratchName' }
elseif ($ScratchName -ne '') { Stop-Refused "gate $Gate takes no ScratchName." }

if ($needs -contains 'confirm') {
    Assert-ScratchName $ConfirmName 'ConfirmName'
    if ($ConfirmName -cne $ScratchName) { Stop-Refused 'ConfirmName must equal ScratchName exactly.' }
}
elseif ($ConfirmName -ne '') { Stop-Refused "gate $Gate takes no ConfirmName." }

if ($needs -contains 'token') {
    if (-not [regex]::IsMatch($TokenSha256, $TokenHashPattern)) {
        Stop-Refused 'TokenSha256 must be exactly 64 lowercase hex characters.'
    }
}
elseif ($TokenSha256 -ne '') { Stop-Refused "gate $Gate takes no TokenSha256." }

if ($needs -contains 'backupset') {
    if (-not [regex]::IsMatch($BackupSetGuid, $BackupSetPattern)) {
        Stop-Refused 'BackupSetGuid must be the lowercase GUID printed by -Gate BackupHeader (8-4-4-4-12 hex).'
    }
}
elseif ($BackupSetGuid -ne '') { Stop-Refused "gate $Gate takes no BackupSetGuid." }

if ($config.Writes -and -not $Approved) { Stop-Refused "gate $Gate writes; it needs -Approved (explicit, separate approval)." }
if (-not $config.Writes -and $Approved) { Stop-Refused "gate $Gate is read-only; -Approved is not accepted." }

switch ($config.Database) {
    'source'  { $database = $SourceDatabase }
    'master'  { $database = 'master' }
    'scratch' { $database = $ScratchName }
    default   { Stop-Refused 'internal: unknown database kind.' }
}

# ---------------------------------------------------------------- 3. fixed, pinned script
$scriptPath = Join-Path -Path $PSScriptRoot -ChildPath $config.Script
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) { Stop-Refused "script $($config.Script) is missing." }
# Read once: the bytes that are hashed are the bytes that are executed.
$scriptBytes = [System.IO.File]::ReadAllBytes($scriptPath)
$hasher = [System.Security.Cryptography.SHA256]::Create()
try { $actualSha256 = -join ($hasher.ComputeHash($scriptBytes) | ForEach-Object { $_.ToString('x2') }) }
finally { $hasher.Dispose() }
if ($actualSha256 -cne $PinnedSha256[$config.Script]) {
    Stop-Refused "script $($config.Script) does not match its pinned SHA-256 (unreviewed change)."
}
$sqlText = (New-Object System.Text.UTF8Encoding($false, $true)).GetString($scriptBytes)
if ($sqlText.Contains('$(') -or [regex]::IsMatch($sqlText, '(?im)^\s*(GO|:setvar|:r)\b')) {
    Stop-Refused "script $($config.Script) contains sqlcmd syntax."
}

# The pinned check functions, executed from exactly the bytes that were hashed.
$checksPath = Join-Path -Path $PSScriptRoot -ChildPath 'ScratchGateChecks.ps1'
if (-not (Test-Path -LiteralPath $checksPath -PathType Leaf)) { Stop-Refused 'ScratchGateChecks.ps1 is missing.' }
$checksBytes = [System.IO.File]::ReadAllBytes($checksPath)
$hasher = [System.Security.Cryptography.SHA256]::Create()
try { $checksSha256 = -join ($hasher.ComputeHash($checksBytes) | ForEach-Object { $_.ToString('x2') }) }
finally { $hasher.Dispose() }
if ($checksSha256 -cne $ChecksPinnedSha256) {
    Stop-Refused 'ScratchGateChecks.ps1 does not match its pinned SHA-256 (unreviewed change).'
}
. ([scriptblock]::Create((New-Object System.Text.UTF8Encoding($false, $true)).GetString($checksBytes)))

$parameters = New-Object System.Collections.Generic.List[object]
if ($needs -contains 'scratch') { $parameters.Add(@('@scratch_name', $ScratchName)) }
if ($needs -contains 'confirm') { $parameters.Add(@('@confirm_name', $ConfirmName)) }
if ($needs -contains 'token')   { $parameters.Add(@('@token_sha256', $TokenSha256)) }
if ($needs -contains 'backupset') { $parameters.Add(@('@backup_set_guid', $BackupSetGuid)) }
if ($config.Script -eq 'fingerprint_readonly.sql') { $parameters.Add(@('@expected_db', $database)) }

Write-Host "Gate:         $Gate"
Write-Host "Server:       $DataSource (expected @@SERVERNAME $ExpectedServerName)"
Write-Host "Database:     $database"
Write-Host "Writes:       $($config.Writes)"
Write-Host "Script:       $($config.Script)"
Write-Host "ScriptSha256: OK $actualSha256"
foreach ($p in $parameters) { Write-Host ("Parameter:    {0} = {1}" -f $p[0], $p[1]) }

if ($DryRun) {
    Write-Host 'DryRun: validated; no connection created.'
    exit 0
}

# ---------------------------------------------------------------- 4. connect and verify identity
$builder = New-Object System.Data.SqlClient.SqlConnectionStringBuilder
$builder.DataSource = $DataSource
$builder.InitialCatalog = $database
$builder.IntegratedSecurity = $true
$builder.Encrypt = $true
$builder.TrustServerCertificate = $true
$builder.Pooling = $false
$builder.ApplicationName = 'MedMind-ScratchGateRunner'
$builder.ConnectTimeout = 15
# A routing hint only: on a standalone Express instance it enforces nothing.
if (-not $config.Writes) { $builder.ApplicationIntent = [System.Data.SqlClient.ApplicationIntent]::ReadOnly }

$connection = New-GateConnection $builder.ConnectionString
$exitCode = 0
try {
    $connection.add_InfoMessage({ param($source, $messageArgs) Write-Host $messageArgs.Message })
    $connection.Open()

    $identity = $connection.CreateCommand()
    $identity.CommandText = 'SELECT DB_NAME(), @@SERVERNAME'
    $reader = $identity.ExecuteReader()
    [void]$reader.Read()
    $connectedDatabase = $reader.GetString(0)
    $connectedServer = $reader.GetString(1)
    $reader.Close()
    if ($connectedDatabase -cne $database -or $connectedServer -cne $ExpectedServerName) {
        Stop-Refused "connected to $connectedServer / $connectedDatabase, expected $ExpectedServerName / $database."
    }

    # ------------------------------------------------------------ 5. fixed text + bound parameters
    $command = $connection.CreateCommand()
    $command.CommandText = $sqlText
    $command.CommandTimeout = 0
    foreach ($p in $parameters) {
        $bound = $command.Parameters.Add($p[0], [System.Data.SqlDbType]::NVarChar, 4000)
        $bound.Value = $p[1]
    }
    $adapter = New-Object System.Data.SqlClient.SqlDataAdapter($command)
    $results = New-Object System.Data.DataSet
    [void]$adapter.Fill($results)
    foreach ($table in $results.Tables) {
        # Display only. No decision below is based on this formatted text.
        if ($Gate -eq 'BackupHeader') { Write-Host ($table | Format-List | Out-String -Width 4096) }
        else { Write-Host ($table | Format-Table -AutoSize | Out-String -Width 4096) }
    }
    if ($Gate -eq 'BackupHeader') {
        $verdict = Get-BackupHeaderVerdict -Tables @($results.Tables) -ScratchName $ScratchName `
            -SourceDatabase $SourceDatabase -ServerName $ExpectedServerName
        if ($verdict.Problems.Count -gt 0) {
            foreach ($problem in $verdict.Problems) { [Console]::Error.WriteLine("BACKUP HEADER MISMATCH: $problem") }
            [Console]::Error.WriteLine('BACKUP HEADER NOT VERIFIED: do not approve G4.')
            $exitCode = 4
        }
        else {
            Write-Host "BACKUP HEADER VERIFIED: -BackupSetGuid $($verdict.BackupSetGuid)"
        }
    }
    if ($exitCode -eq 0) { Write-Host "Gate $Gate finished." }
}
catch [System.Data.SqlClient.SqlException] {
    foreach ($e in $_.Exception.Errors) { [Console]::Error.WriteLine("SQL ERROR $($e.Number): $($e.Message)") }
    $exitCode = 1
}
finally {
    $connection.Dispose()
}
exit $exitCode
