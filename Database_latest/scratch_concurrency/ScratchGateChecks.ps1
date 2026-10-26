<#
    Pure check functions for Invoke-ScratchGate.ps1: no connection, no file
    access, no output. The runner pins this file's SHA-256 and dot-sources
    exactly the bytes it hashed. The offline tests call these functions
    directly with synthetic result tables.
#>

function Test-ScratchFlag([object] $Value) {
    # bit columns arrive as Boolean, smallint/tinyint as integers.
    try { return [Convert]::ToInt32($Value) -eq 1 } catch { return $false }
}

function Get-BackupHeaderVerdict {
    <#
        Compares the three BackupHeader result sets:
          [0] the msdb record for the G3 path (backup_set_uuid, database_name,
              backup_type, is_copy_only, has_backup_checksums, server_name,
              media_name);
          [1] RESTORE HEADERONLY of the file (BackupSetGUID, DatabaseName,
              BackupType, IsCopyOnly, HasBackupChecksums, ServerName);
          [2] RESTORE LABELONLY of the file (MediaName).
        Returns Problems (empty only if everything matches) and, only then,
        the verified BackupSetGuid in lowercase. Fails closed on a missing
        result set, a row count other than one, a missing column, NULL, or
        any mismatch.
    #>
    param(
        [object[]] $Tables,
        [string] $ScratchName,
        [string] $SourceDatabase,
        [string] $ServerName
    )
    $problems = New-Object System.Collections.Generic.List[string]
    $verdict = { param($guid) [pscustomobject]@{ Problems = [string[]]$problems.ToArray(); BackupSetGuid = $guid } }

    if ($null -eq $Tables -or $Tables.Count -ne 3) {
        $count = if ($null -eq $Tables) { 0 } else { $Tables.Count }
        $problems.Add("expected 3 result sets (msdb record, backup header, media label), got $count.")
        return (& $verdict $null)
    }
    $sets = [ordered]@{
        'msdb record'   = @{ Table = $Tables[0]; Columns = @('backup_set_uuid', 'database_name', 'backup_type', 'is_copy_only',
                                                             'has_backup_checksums', 'server_name', 'media_name') }
        'backup header' = @{ Table = $Tables[1]; Columns = @('BackupSetGUID', 'DatabaseName', 'BackupType', 'IsCopyOnly',
                                                             'HasBackupChecksums', 'ServerName') }
        'media label'   = @{ Table = $Tables[2]; Columns = @('MediaName') }
    }
    $cells = @{}
    foreach ($label in $sets.Keys) {
        $table = $sets[$label].Table
        if ($null -eq $table -or $table.Rows.Count -ne 1) {
            $rows = if ($null -eq $table) { 0 } else { $table.Rows.Count }
            $problems.Add("$label must have exactly one row, got $rows.")
            continue
        }
        foreach ($column in $sets[$label].Columns) {
            if (-not $table.Columns.Contains($column)) { $problems.Add("$label has no column $column."); continue }
            $value = $table.Rows[0][$column]
            if ($null -eq $value -or $value -is [System.DBNull]) { $problems.Add("$label column $column is NULL."); continue }
            $cells["$label|$column"] = $value
        }
    }
    if ($problems.Count -gt 0) { return (& $verdict $null) }

    $msdbGuid = $null; $headerGuid = $null
    try { $msdbGuid = [Guid]$cells['msdb record|backup_set_uuid'] } catch { $problems.Add('msdb backup_set_uuid is not a GUID.') }
    try { $headerGuid = [Guid]$cells['backup header|BackupSetGUID'] } catch { $problems.Add('header BackupSetGUID is not a GUID.') }
    if ($null -ne $msdbGuid -and $null -ne $headerGuid -and $msdbGuid -ne $headerGuid) {
        $problems.Add("BackupSetGUID $headerGuid does not equal msdb backup_set_uuid $msdbGuid.")
    }

    $textChecks = @(
        @('backup header|DatabaseName', $SourceDatabase), @('msdb record|database_name', $SourceDatabase),
        @('backup header|ServerName', $ServerName),        @('msdb record|server_name', $ServerName),
        @('media label|MediaName', $ScratchName),          @('msdb record|media_name', $ScratchName),
        @('msdb record|backup_type', 'D')
    )
    foreach ($check in $textChecks) {
        $actual = [string]$cells[$check[0]]
        if ($actual -cne $check[1]) { $problems.Add("$($check[0].Replace('|', ' ')) is '$actual', expected '$($check[1])'.") }
    }
    $headerType = $null
    try { $headerType = [Convert]::ToInt32($cells['backup header|BackupType']) } catch { }
    if ($headerType -ne 1) { $problems.Add("backup header BackupType is '$($cells['backup header|BackupType'])', expected 1 (full).") }
    foreach ($flag in @('backup header|IsCopyOnly', 'msdb record|is_copy_only',
                        'backup header|HasBackupChecksums', 'msdb record|has_backup_checksums')) {
        if (-not (Test-ScratchFlag $cells[$flag])) { $problems.Add("$($flag.Replace('|', ' ')) is not 1.") }
    }

    if ($problems.Count -gt 0) { return (& $verdict $null) }
    return (& $verdict $headerGuid.ToString('D').ToLowerInvariant())
}
