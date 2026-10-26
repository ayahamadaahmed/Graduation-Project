/* =====================================================================
   R2 - DROP a scratch copy that has NO marker (failed/interrupted G4 or a
   failed G4b). DESTRUCTIVE AND IRREVERSIBLE. Never run without explicit R2
   approval, and only after R1 was run and reviewed for the same name.

   Run ONLY through Invoke-ScratchGate.ps1 -Gate R2 -ScratchName ...
   -ConfirmName ... -Approved. The runner connects to master (fixed),
   checks @@SERVERNAME, and binds @scratch_name and @confirm_name as typed
   parameters. No text substitution; the identifier is only built with
   QUOTENAME() from the validated name.

   It does not use the marker (which may not exist). Instead it requires
   proof that this exact database was created by restoring OUR G3 backup:
     - expected server, in master;
     - exact scratch pattern, confirmation equal (binary), not protected
       (MedMind_Booking_DB, MedMind_Audit_Final2, MedMind_Audit_Final,
       MedMind_Audit*, MedMind_Booking*), in any case;
     - exactly one database with exactly that name; not a snapshot; state
       ONLINE, RESTORING, RECOVERY_PENDING or SUSPECT (an OFFLINE database
       is refused: dropping it would leave its files);
     - exactly two files, at exactly the G4 paths
       <data path>\<name>_data.mdf and <log path>\<name>_log.ldf;
     - no other database uses those paths;
     - msdb restore history: the latest restore into that name is a FULL
       restore from <backup path>\<name>.bak, a FULL, COPY_ONLY,
       checksummed backup of MedMind_Audit_Final2 taken on this server. If
       msdb has no such row (for example a restore that failed before it
       completed), R2 refuses (51211): that case is manual, see README;
     - if ONLINE: a guarded probe of <name>.sys.tables must succeed and find
       no table named zz_scratch_marker (a marked copy must use G7, 51212).
       If the probe fails, the marker status is unknown and R2 refuses
       (51214); it is never treated as unmarked. RESTORING,
       RECOVERY_PENDING and SUSPECT copies cannot be opened, so the marker
       is not consulted for them: only the checks above apply.
   Orphan files with no database at all are NOT handled here: R1 reports
   them, and removing them is a separate, manual, approved step.
   ===================================================================== */
SET NOCOUNT ON;
SET XACT_ABORT ON;

IF @@SERVERNAME <> N'LAPTOP-FACHLL1N\SQLEXPRESS'
    THROW 51200, N'Refused: unexpected server.', 1;
IF DB_NAME() <> N'master'
    THROW 51201, N'Refused: R2 must run in master.', 1;
IF @scratch_name IS NULL
   OR DATALENGTH(@scratch_name) <> 70
   OR @scratch_name COLLATE Latin1_General_BIN NOT LIKE
      N'MedMind[_]ConcScratch[_][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][_][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'
    THROW 51202, N'Refused: the scratch name is not MedMind_ConcScratch_<YYYYMMDD>_<6 lowercase hex>.', 1;
IF @confirm_name IS NULL OR @confirm_name COLLATE Latin1_General_BIN <> @scratch_name COLLATE Latin1_General_BIN
    THROW 51203, N'Refused: the confirmation does not equal the scratch name.', 1;
IF LOWER(@scratch_name) IN (N'medmind_booking_db', N'medmind_audit_final2', N'medmind_audit_final')
   OR LOWER(@scratch_name) LIKE N'medmind[_]audit%' OR LOWER(@scratch_name) LIKE N'medmind[_]booking%'
    THROW 51204, N'Refused: protected database name.', 1;

DECLARE @scratch sysname = @scratch_name;
DECLARE @source sysname = N'MedMind_Audit_Final2';
DECLARE @dir nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS nvarchar(260));
DECLARE @data_dir nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(260));
DECLARE @log_dir nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultLogPath') AS nvarchar(260));
IF @dir IS NULL OR @data_dir IS NULL OR @log_dir IS NULL
    THROW 51205, N'Refused: the instance default paths are unknown.', 1;
IF RIGHT(@dir, 1) <> N'\' SET @dir += N'\';
IF RIGHT(@data_dir, 1) <> N'\' SET @data_dir += N'\';
IF RIGHT(@log_dir, 1) <> N'\' SET @log_dir += N'\';
DECLARE @file nvarchar(400) = @dir + @scratch + N'.bak';
DECLARE @data_file nvarchar(400) = @data_dir + @scratch + N'_data.mdf';
DECLARE @log_file nvarchar(400) = @log_dir + @scratch + N'_log.ldf';

IF (SELECT COUNT(*) FROM sys.databases WHERE name COLLATE Latin1_General_BIN = @scratch COLLATE Latin1_General_BIN) <> 1
    THROW 51206, N'Refused: exactly one database with exactly this name must exist.', 1;
DECLARE @db_id int = DB_ID(@scratch);
DECLARE @state nvarchar(60) = (SELECT state_desc FROM sys.databases WHERE database_id = @db_id);
IF EXISTS (SELECT 1 FROM sys.databases WHERE database_id = @db_id AND source_database_id IS NOT NULL)
    THROW 51207, N'Refused: the target is a database snapshot.', 1;
IF @state IS NULL OR @state NOT IN (N'ONLINE', N'RESTORING', N'RECOVERY_PENDING', N'SUSPECT')
    THROW 51208, N'Refused: database state not handled by R2 (e.g. OFFLINE).', 1;

IF (SELECT COUNT(*) FROM sys.master_files WHERE database_id = @db_id) <> 2
   OR NOT EXISTS (SELECT 1 FROM sys.master_files
                  WHERE database_id = @db_id AND type = 0 AND LOWER(physical_name) = LOWER(@data_file))
   OR NOT EXISTS (SELECT 1 FROM sys.master_files
                  WHERE database_id = @db_id AND type = 1 AND LOWER(physical_name) = LOWER(@log_file))
    THROW 51209, N'Refused: the database files are not exactly the G4 scratch paths.', 1;
IF EXISTS (SELECT 1 FROM sys.master_files
           WHERE database_id <> @db_id AND LOWER(physical_name) IN (LOWER(@data_file), LOWER(@log_file)))
    THROW 51210, N'Refused: another database uses the scratch file paths.', 1;

DECLARE @restored_from nvarchar(400), @restore_type char(1), @source_ok bit = 0;
SELECT TOP 1 @restored_from = bmf.physical_device_name, @restore_type = rh.restore_type,
       @source_ok = CASE WHEN bs.database_name = @source AND bs.type = 'D' AND bs.is_copy_only = 1
                              AND bs.has_backup_checksums = 1 AND bs.server_name = @@SERVERNAME THEN 1 ELSE 0 END
FROM msdb.dbo.restorehistory AS rh
JOIN msdb.dbo.backupset AS bs ON bs.backup_set_id = rh.backup_set_id
JOIN msdb.dbo.backupmediafamily AS bmf ON bmf.media_set_id = bs.media_set_id
WHERE rh.destination_database_name = @scratch
ORDER BY rh.restore_date DESC;
IF @restored_from IS NULL OR @restored_from <> @file OR @restore_type <> 'D' OR @source_ok <> 1
    THROW 51211, N'Refused: msdb does not show this database restored from our G3 backup of MedMind_Audit_Final2.', 1;

-- Marker probe (ONLINE only). OBJECT_ID() would return NULL for a database
-- it cannot open, which would look like "no marker"; this probe instead
-- refuses whenever the marker status cannot be read.
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
        SET @probe_error = LEFT(CONCAT(N'Refused: the marker status of the ONLINE copy cannot be read (SQL error ',
                                       ERROR_NUMBER(), N': ', ERROR_MESSAGE(), N'); nothing was dropped.'), 2048);
    END CATCH;
    IF @probe_error IS NOT NULL
        THROW 51214, @probe_error, 1;
    IF @marker_tables IS NULL
        THROW 51214, N'Refused: the marker status of the ONLINE copy is unknown; nothing was dropped.', 1;
    IF @marker_tables <> 0
        THROW 51212, N'Refused: the scratch copy has a marker; use G7.', 1;
END;

PRINT N'R2: dropping unmarked scratch copy ' + @scratch + N' (state ' + @state + N')';
DECLARE @drop nvarchar(max) =
    CASE WHEN @state = N'ONLINE'
         THEN N'ALTER DATABASE ' + QUOTENAME(@scratch) + N' SET SINGLE_USER WITH ROLLBACK IMMEDIATE; '
         ELSE N'' END
  + N'DROP DATABASE ' + QUOTENAME(@scratch) + N';';
EXEC (@drop);

IF DB_ID(@scratch) IS NOT NULL
    THROW 51213, N'R2: the scratch database still exists.', 1;
SELECT @scratch AS dropped_database,
       (SELECT file_exists FROM sys.dm_os_file_exists(@data_file)) AS data_file_left,
       (SELECT file_exists FROM sys.dm_os_file_exists(@log_file)) AS log_file_left;
