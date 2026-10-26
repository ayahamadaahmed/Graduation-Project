/* =====================================================================
   G3b - READ-ONLY provenance check of the G3 backup file, before G4.
   Reads the backup file's own header and label and the msdb record for
   that path. No database is created, changed or restored.

   Run ONLY through Invoke-ScratchGate.ps1 -Gate BackupHeader -ScratchName ...
   The runner connects to master (fixed), checks @@SERVERNAME and binds
   @scratch_name. No text substitution.

   Exactly three result sets, in this order:
     1. the msdb record that G3 wrote for that exact path, with its media
        set name;
     2. RESTORE HEADERONLY of the file;
     3. RESTORE LABELONLY of the file.
   The runner compares them itself (ScratchGateChecks.ps1,
   Get-BackupHeaderVerdict) and fails unless: one row each; BackupSetGUID =
   backup_set_uuid; DatabaseName/database_name MedMind_Audit_Final2;
   BackupType 1 / type D; IsCopyOnly and HasBackupChecksums 1 in both;
   ServerName/server_name LAPTOP-FACHLL1N\SQLEXPRESS; MediaName/media_name
   equal to the scratch name (G3 writes MEDIANAME = scratch name). It then
   prints the verified BackupSetGUID, which G4 requires as -BackupSetGuid.
   ===================================================================== */
SET NOCOUNT ON;

IF @@SERVERNAME <> N'LAPTOP-FACHLL1N\SQLEXPRESS'
    THROW 51300, N'Refused: unexpected server.', 1;
IF DB_NAME() <> N'master'
    THROW 51301, N'Refused: BackupHeader must run in master.', 1;
IF @scratch_name IS NULL
   OR DATALENGTH(@scratch_name) <> 70
   OR @scratch_name COLLATE Latin1_General_BIN NOT LIKE
      N'MedMind[_]ConcScratch[_][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][_][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'
    THROW 51302, N'Refused: the scratch name is not MedMind_ConcScratch_<YYYYMMDD>_<6 lowercase hex>.', 1;
IF LOWER(@scratch_name) IN (N'medmind_booking_db', N'medmind_audit_final2', N'medmind_audit_final')
   OR LOWER(@scratch_name) LIKE N'medmind[_]audit%' OR LOWER(@scratch_name) LIKE N'medmind[_]booking%'
    THROW 51303, N'Refused: protected database name.', 1;

DECLARE @scratch sysname = @scratch_name;
DECLARE @dir nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS nvarchar(260));
IF @dir IS NULL
    THROW 51304, N'Refused: the instance has no default backup path.', 1;
IF RIGHT(@dir, 1) <> N'\' SET @dir += N'\';
DECLARE @file nvarchar(400) = @dir + @scratch + N'.bak';
IF NOT EXISTS (SELECT 1 FROM sys.dm_os_file_exists(@file) WHERE file_exists = 1)
    THROW 51305, N'Refused: the G3 backup file does not exist.', 1;

SELECT bs.backup_set_uuid, bs.database_name, bs.type AS backup_type, bs.is_copy_only, bs.has_backup_checksums,
       bs.server_name, bms.name AS media_name, bs.backup_finish_date, bs.backup_size, bmf.physical_device_name
FROM msdb.dbo.backupset AS bs
JOIN msdb.dbo.backupmediafamily AS bmf ON bmf.media_set_id = bs.media_set_id
JOIN msdb.dbo.backupmediaset AS bms ON bms.media_set_id = bs.media_set_id
WHERE bmf.physical_device_name = @file;

RESTORE HEADERONLY FROM DISK = @file;
RESTORE LABELONLY FROM DISK = @file;
