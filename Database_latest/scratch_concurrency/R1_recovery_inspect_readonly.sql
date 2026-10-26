/* =====================================================================
   R1 - READ-ONLY inspection of a scratch copy left by a failed or
   interrupted restore (G4) or a failed verification (G4b): no marker
   needed. SELECT statements only.

   Run ONLY through Invoke-ScratchGate.ps1 -Gate R1 -ScratchName ...
   The runner connects to master (fixed), with read-only intent, checks
   @@SERVERNAME and binds @scratch_name. No text substitution.

   Reports, for that exact scratch name only: the database row(s) and state,
   its files and whether they are exactly the G4 paths, the files present on
   disk at those paths (orphans), any OTHER database using those paths (must
   be none), the msdb restore history for that destination, and the marker
   status: PRESENT, absent, or UNKNOWN. The marker is read with a guarded
   probe; if the database is not ONLINE or the probe fails, the status is
   UNKNOWN and R1 recommends nothing (manual review, see README). R1 only
   says "R2 may be considered" for an ONLINE copy whose probe succeeded and
   found no marker.
   ===================================================================== */
SET NOCOUNT ON;

IF @@SERVERNAME <> N'LAPTOP-FACHLL1N\SQLEXPRESS'
    THROW 51100, N'Refused: unexpected server.', 1;
IF DB_NAME() <> N'master'
    THROW 51101, N'Refused: R1 must run in master.', 1;
IF @scratch_name IS NULL
   OR DATALENGTH(@scratch_name) <> 70
   OR @scratch_name COLLATE Latin1_General_BIN NOT LIKE
      N'MedMind[_]ConcScratch[_][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][_][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'
    THROW 51102, N'Refused: the scratch name is not MedMind_ConcScratch_<YYYYMMDD>_<6 lowercase hex>.', 1;
IF LOWER(@scratch_name) IN (N'medmind_booking_db', N'medmind_audit_final2', N'medmind_audit_final')
   OR LOWER(@scratch_name) LIKE N'medmind[_]audit%' OR LOWER(@scratch_name) LIKE N'medmind[_]booking%'
    THROW 51103, N'Refused: protected database name.', 1;

DECLARE @scratch sysname = @scratch_name;
DECLARE @dir nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS nvarchar(260));
DECLARE @data_dir nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(260));
DECLARE @log_dir nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultLogPath') AS nvarchar(260));
IF RIGHT(@dir, 1) <> N'\' SET @dir += N'\';
IF RIGHT(@data_dir, 1) <> N'\' SET @data_dir += N'\';
IF RIGHT(@log_dir, 1) <> N'\' SET @log_dir += N'\';
DECLARE @file nvarchar(400) = @dir + @scratch + N'.bak';
DECLARE @data_file nvarchar(400) = @data_dir + @scratch + N'_data.mdf';
DECLARE @log_file nvarchar(400) = @log_dir + @scratch + N'_log.ldf';

PRINT N'--- 1. databases with this name (any letter case)';
SELECT name, database_id, state_desc, user_access_desc, create_date, source_database_id, is_read_only
FROM sys.databases WHERE LOWER(name) = LOWER(@scratch);

PRINT N'--- 2. its files, and whether each is exactly the G4 path';
SELECT mf.type_desc, mf.name AS logical_name, mf.physical_name,
       CASE WHEN LOWER(mf.physical_name) = LOWER(CASE mf.type WHEN 0 THEN @data_file WHEN 1 THEN @log_file END)
            THEN 1 ELSE 0 END AS is_expected_path
FROM sys.master_files AS mf WHERE mf.database_id = DB_ID(@scratch);

PRINT N'--- 3. files on disk at the expected paths';
SELECT N'backup' AS kind, @file AS path, f.file_exists FROM sys.dm_os_file_exists(@file) AS f
UNION ALL SELECT N'data', @data_file, f.file_exists FROM sys.dm_os_file_exists(@data_file) AS f
UNION ALL SELECT N'log', @log_file, f.file_exists FROM sys.dm_os_file_exists(@log_file) AS f;

PRINT N'--- 4. OTHER databases using those paths (must be none)';
SELECT DB_NAME(mf.database_id) AS other_database, mf.physical_name
FROM sys.master_files AS mf
WHERE LOWER(mf.physical_name) IN (LOWER(@data_file), LOWER(@log_file))
  AND mf.database_id <> ISNULL(DB_ID(@scratch), -1);

PRINT N'--- 5. msdb restore history for this destination';
SELECT TOP 5 rh.restore_date, rh.restore_type, rh.destination_database_name,
       bs.database_name AS source_database, bs.type AS backup_type, bs.is_copy_only, bs.has_backup_checksums,
       bs.server_name, bmf.physical_device_name,
       CASE WHEN bmf.physical_device_name = @file THEN 1 ELSE 0 END AS from_expected_backup_file
FROM msdb.dbo.restorehistory AS rh
JOIN msdb.dbo.backupset AS bs ON bs.backup_set_id = rh.backup_set_id
JOIN msdb.dbo.backupmediafamily AS bmf ON bmf.media_set_id = bs.media_set_id
WHERE rh.destination_database_name = @scratch
ORDER BY rh.restore_date DESC;

PRINT N'--- 6. marker status (no recommendation when it is unknown)';
DECLARE @state nvarchar(60) = (SELECT state_desc FROM sys.databases
                               WHERE name COLLATE Latin1_General_BIN = @scratch COLLATE Latin1_General_BIN);
DECLARE @marker_tables int = NULL, @probe_error nvarchar(2048) = NULL;
IF @state = N'ONLINE'
BEGIN
    DECLARE @probe nvarchar(max) =
        N'SELECT @n = COUNT(*) FROM ' + QUOTENAME(@scratch) + N'.sys.tables WHERE name = N''zz_scratch_marker''';
    BEGIN TRY
        EXEC sys.sp_executesql @probe, N'@n int OUTPUT', @n = @marker_tables OUTPUT;
    END TRY
    BEGIN CATCH
        SET @marker_tables = NULL;
        SET @probe_error = LEFT(CONCAT(N'SQL error ', ERROR_NUMBER(), N': ', ERROR_MESSAGE()), 2048);
    END CATCH;
END;
SELECT @state AS database_state,
       CASE WHEN @state IS NULL THEN 'no database with exactly this name'
            WHEN @state <> N'ONLINE' THEN 'UNKNOWN (not online; the marker cannot be read)'
            WHEN @probe_error IS NOT NULL OR @marker_tables IS NULL THEN 'UNKNOWN (the marker probe failed)'
            WHEN @marker_tables = 0 THEN 'absent'
            ELSE 'PRESENT' END AS marker_status,
       @probe_error AS marker_probe_error,
       CASE WHEN @state = N'ONLINE' AND @probe_error IS NULL AND @marker_tables > 0
                THEN 'G7 (marked copy; never R2)'
            WHEN @state = N'ONLINE' AND @probe_error IS NULL AND @marker_tables = 0
                THEN 'R2 may be considered, only if all its checks pass'
            ELSE 'no recommendation: manual review (README, recovery)' END AS next_step;
