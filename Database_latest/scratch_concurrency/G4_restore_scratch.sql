/* =====================================================================
   G4 - Restore the G3 backup as a NEW scratch database.
   WRITE-CAPABLE: creates ONE new database and its two files. Never run
   without explicit G4 approval.

   Run ONLY through Invoke-ScratchGate.ps1 -Gate G4 -ScratchName ...
   -BackupSetGuid <guid printed by -Gate BackupHeader> -Approved.
   The runner connects to master (fixed), checks @@SERVERNAME, and binds
   @scratch_name and @backup_set_guid as typed SQL parameters
   (nvarchar(4000)). No value is text-substituted.

   Refuses unless: on the expected server, in master; the scratch name is
   exactly the scratch pattern and not protected; NO database with that name
   exists (never overwrites: no REPLACE); the backup file exists and msdb
   records it as a FULL, COPY_ONLY, checksummed backup of
   MedMind_Audit_Final2 taken on this server; the backup holds exactly the
   two expected logical files; the two new physical files do not exist yet.

   Logical file names: the source keeps the logical names MedMind_Booking_DB
   (data) and MedMind_Booking_DB_log (log) from its original backup. They are
   file labels only, mapped here to NEW physical files named after the
   scratch database. They never name, open or touch a database called
   MedMind_Booking_DB.

   Binding to the approved backup set (@backup_set_guid, the GUID that
   -Gate BackupHeader verified and printed):
     - before the restore: msdb's record for the file must be that set, with
       media set name = scratch name;
     - during the restore: WITH MEDIANAME = scratch name, so SQL Server
       itself refuses a file whose media set has another name;
     - after the restore: the latest msdb restore history row for the
       scratch name must reference that backup set (THROW 50415 otherwise:
       the copy must not be used; inspect with R1).
   This narrows, but does not provably close, the window between
   BackupHeader and G4 (README.md, "Backup provenance").

   If the RESTORE itself fails part-way, do NOT improvise: use the recovery
   gates R1 (read-only inspection) and R2 (guarded drop), see README.md.
   ===================================================================== */
SET NOCOUNT ON;
SET XACT_ABORT ON;

IF @@SERVERNAME <> N'LAPTOP-FACHLL1N\SQLEXPRESS'
    THROW 50400, N'Refused: unexpected server.', 1;
IF DB_NAME() <> N'master'
    THROW 50401, N'Refused: G4 must run in master.', 1;
IF @scratch_name IS NULL
   OR DATALENGTH(@scratch_name) <> 70
   OR @scratch_name COLLATE Latin1_General_BIN NOT LIKE
      N'MedMind[_]ConcScratch[_][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][_][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'
    THROW 50402, N'Refused: the scratch name is not MedMind_ConcScratch_<YYYYMMDD>_<6 lowercase hex>.', 1;
IF LOWER(@scratch_name) IN (N'medmind_booking_db', N'medmind_audit_final2', N'medmind_audit_final')
   OR LOWER(@scratch_name) LIKE N'medmind[_]audit%' OR LOWER(@scratch_name) LIKE N'medmind[_]booking%'
    THROW 50403, N'Refused: protected database name.', 1;
-- The approved backup set: a lowercase canonical GUID (8-4-4-4-12).
DECLARE @approved_set uniqueidentifier = TRY_CONVERT(uniqueidentifier, @backup_set_guid);
IF @backup_set_guid IS NULL
   OR DATALENGTH(@backup_set_guid) <> 72
   OR @approved_set IS NULL
   OR LOWER(CONVERT(nchar(36), @approved_set)) COLLATE Latin1_General_BIN <> @backup_set_guid COLLATE Latin1_General_BIN
    THROW 50413, N'Refused: the approved backup set GUID (from -Gate BackupHeader) is missing or malformed.', 1;

DECLARE @scratch sysname = @scratch_name;
DECLARE @source sysname = N'MedMind_Audit_Final2';
DECLARE @data_logical sysname = N'MedMind_Booking_DB';
DECLARE @log_logical sysname = N'MedMind_Booking_DB_log';

IF DB_ID(@scratch) IS NOT NULL
   OR EXISTS (SELECT 1 FROM sys.databases WHERE LOWER(name) = LOWER(@scratch))
    THROW 50404, N'Refused: the scratch database already exists (restore never overwrites).', 1;

DECLARE @dir nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS nvarchar(260));
IF @dir IS NULL
    THROW 50411, N'Refused: the instance has no default backup path.', 1;
IF RIGHT(@dir, 1) <> N'\' SET @dir += N'\';
DECLARE @file nvarchar(400) = @dir + @scratch + N'.bak';
IF NOT EXISTS (SELECT 1 FROM sys.dm_os_file_exists(@file) WHERE file_exists = 1)
    THROW 50405, N'Refused: the G3 backup file does not exist.', 1;

-- Backup metadata recorded by this server for exactly this file.
DECLARE @set_id int;
SELECT TOP 1 @set_id = bs.backup_set_id
FROM msdb.dbo.backupset AS bs
JOIN msdb.dbo.backupmediafamily AS bmf ON bmf.media_set_id = bs.media_set_id
WHERE bmf.physical_device_name = @file
ORDER BY bs.backup_finish_date DESC;
IF @set_id IS NULL
    THROW 50406, N'Refused: msdb has no backup record for this file.', 1;
IF NOT EXISTS (SELECT 1 FROM msdb.dbo.backupset
               WHERE backup_set_id = @set_id AND database_name = @source AND type = 'D'
                 AND is_copy_only = 1 AND has_backup_checksums = 1 AND server_name = @@SERVERNAME)
    THROW 50407, N'Refused: not a FULL, COPY_ONLY, checksummed backup of MedMind_Audit_Final2 from this server.', 1;
IF (SELECT COUNT(*) FROM msdb.dbo.backupfile WHERE backup_set_id = @set_id AND is_present = 1) <> 2
   OR NOT EXISTS (SELECT 1 FROM msdb.dbo.backupfile
                  WHERE backup_set_id = @set_id AND is_present = 1 AND file_type = 'D' AND logical_name = @data_logical)
   OR NOT EXISTS (SELECT 1 FROM msdb.dbo.backupfile
                  WHERE backup_set_id = @set_id AND is_present = 1 AND file_type = 'L' AND logical_name = @log_logical)
    THROW 50408, N'Refused: the backup does not hold exactly the two expected logical files.', 1;
IF NOT EXISTS (SELECT 1 FROM msdb.dbo.backupset AS bs
               JOIN msdb.dbo.backupmediaset AS bms ON bms.media_set_id = bs.media_set_id
               WHERE bs.backup_set_id = @set_id AND bs.backup_set_uuid = @approved_set
                 AND bms.name COLLATE Latin1_General_BIN = @scratch COLLATE Latin1_General_BIN)
    THROW 50414, N'Refused: msdb record for this file is not the approved backup set with this media name.', 1;

RESTORE VERIFYONLY FROM DISK = @file WITH CHECKSUM;

DECLARE @data_dir nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(260));
DECLARE @log_dir nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultLogPath') AS nvarchar(260));
IF @data_dir IS NULL OR @log_dir IS NULL
    THROW 50412, N'Refused: the instance has no default data or log path.', 1;
IF RIGHT(@data_dir, 1) <> N'\' SET @data_dir += N'\';
IF RIGHT(@log_dir, 1) <> N'\' SET @log_dir += N'\';
DECLARE @data_file nvarchar(400) = @data_dir + @scratch + N'_data.mdf';
DECLARE @log_file nvarchar(400) = @log_dir + @scratch + N'_log.ldf';
IF EXISTS (SELECT 1 FROM sys.dm_os_file_exists(@data_file) WHERE file_exists = 1)
   OR EXISTS (SELECT 1 FROM sys.dm_os_file_exists(@log_file) WHERE file_exists = 1)
    THROW 50409, N'Refused: a target physical file already exists.', 1;

PRINT N'G4: restoring ' + @file + N' as ' + @scratch;
RESTORE DATABASE @scratch FROM DISK = @file
    WITH MEDIANAME = @scratch,
         MOVE @data_logical TO @data_file,
         MOVE @log_logical TO @log_file,
         CHECKSUM, RECOVERY, STATS = 25;

IF DB_ID(@scratch) IS NULL
    THROW 50410, N'G4: the restored database is missing.', 1;
DECLARE @restored_set uniqueidentifier;
SELECT TOP 1 @restored_set = bs.backup_set_uuid
FROM msdb.dbo.restorehistory AS rh
JOIN msdb.dbo.backupset AS bs ON bs.backup_set_id = rh.backup_set_id
WHERE rh.destination_database_name = @scratch
ORDER BY rh.restore_history_id DESC;
IF @restored_set IS NULL OR @restored_set <> @approved_set
    THROW 50415, N'G4: msdb does not show the approved backup set restored into the scratch copy. Do NOT use it: run R1 and review.', 1;
SELECT d.name, d.state_desc, d.is_read_only, d.source_database_id, mf.type_desc, mf.physical_name
FROM sys.databases AS d
JOIN sys.master_files AS mf ON mf.database_id = d.database_id
WHERE d.name = @scratch;
