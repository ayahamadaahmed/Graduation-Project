/* =====================================================================
   G3 - COPY_ONLY backup of MedMind_Audit_Final2 for a scratch copy.
   WRITE-CAPABLE: creates ONE new .bak file in the instance default backup
   folder. Never run without explicit G3 approval.

   Run ONLY through Invoke-ScratchGate.ps1 -Gate G3 -ScratchName ... -Approved.
   The runner connects to MedMind_Audit_Final2 (fixed), checks @@SERVERNAME,
   and binds @scratch_name as a typed SQL parameter (nvarchar(4000)). No value
   is ever text-substituted into this script.

   Refuses unless: on server LAPTOP-FACHLL1N\SQLEXPRESS and database
   MedMind_Audit_Final2; @scratch_name is exactly
   MedMind_ConcScratch_<8 digits>_<6 lowercase hex> and not protected; no
   database with that name exists; the backup folder exists; the .bak file
   does not exist yet. COPY_ONLY leaves the backup chain untouched. The
   source database is only read.

   The new media set is named after the scratch name (FORMAT, MEDIANAME).
   G4 restores WITH MEDIANAME = the same name, so SQL Server itself refuses
   a file at that path whose media set has another name. FORMAT only ever
   applies to this new file: the script refuses if the file already exists.

   If G3 fails after the file was created (BACKUP or RESTORE VERIFYONLY
   error), do NOT rerun it: follow "If G3 fails" in README.md.
   ===================================================================== */
SET NOCOUNT ON;
SET XACT_ABORT ON;

IF @@SERVERNAME <> N'LAPTOP-FACHLL1N\SQLEXPRESS'
    THROW 50300, N'Refused: unexpected server.', 1;
IF DB_NAME() <> N'MedMind_Audit_Final2'
    THROW 50301, N'Refused: G3 must run on MedMind_Audit_Final2.', 1;
IF @scratch_name IS NULL
   OR DATALENGTH(@scratch_name) <> 70
   OR @scratch_name COLLATE Latin1_General_BIN NOT LIKE
      N'MedMind[_]ConcScratch[_][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][_][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'
    THROW 50302, N'Refused: the scratch name is not MedMind_ConcScratch_<YYYYMMDD>_<6 lowercase hex>.', 1;
IF LOWER(@scratch_name) IN (N'medmind_booking_db', N'medmind_audit_final2', N'medmind_audit_final')
   OR LOWER(@scratch_name) LIKE N'medmind[_]audit%' OR LOWER(@scratch_name) LIKE N'medmind[_]booking%'
    THROW 50303, N'Refused: protected database name.', 1;

DECLARE @scratch sysname = @scratch_name;
IF DB_ID(@scratch) IS NOT NULL
   OR EXISTS (SELECT 1 FROM sys.databases WHERE LOWER(name) = LOWER(@scratch))
    THROW 50304, N'Refused: a database with the scratch name already exists.', 1;

DECLARE @dir nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS nvarchar(260));
IF @dir IS NULL
    THROW 50305, N'Refused: the instance has no default backup path.', 1;
IF RIGHT(@dir, 1) <> N'\' SET @dir += N'\';
IF NOT EXISTS (SELECT 1 FROM sys.dm_os_file_exists(@dir) WHERE file_is_a_directory = 1)
    THROW 50306, N'Refused: the default backup folder does not exist.', 1;

DECLARE @file nvarchar(400) = @dir + @scratch + N'.bak';
IF EXISTS (SELECT 1 FROM sys.dm_os_file_exists(@file) WHERE file_exists = 1)
    THROW 50307, N'Refused: the backup file already exists.', 1;

PRINT N'G3: backing up MedMind_Audit_Final2 (COPY_ONLY, CHECKSUM, media ' + @scratch + N') to ' + @file;
BACKUP DATABASE [MedMind_Audit_Final2] TO DISK = @file WITH COPY_ONLY, CHECKSUM, FORMAT, INIT, MEDIANAME = @scratch, STATS = 25;
RESTORE VERIFYONLY FROM DISK = @file WITH CHECKSUM;

-- The backup's own metadata, as recorded by the server (read only).
SELECT TOP 1 bs.database_name, bs.type AS backup_type, bs.is_copy_only, bs.has_backup_checksums,
       bs.server_name, bs.backup_finish_date, bs.backup_size, bs.backup_set_uuid, bms.name AS media_name,
       bmf.physical_device_name
FROM msdb.dbo.backupset AS bs
JOIN msdb.dbo.backupmediafamily AS bmf ON bmf.media_set_id = bs.media_set_id
JOIN msdb.dbo.backupmediaset AS bms ON bms.media_set_id = bs.media_set_id
WHERE bmf.physical_device_name = @file
ORDER BY bs.backup_finish_date DESC;
SELECT bf.logical_name, bf.file_type, bf.is_present
FROM msdb.dbo.backupfile AS bf
WHERE bf.backup_set_id = (SELECT TOP 1 bs.backup_set_id FROM msdb.dbo.backupset AS bs
                          JOIN msdb.dbo.backupmediafamily AS bmf ON bmf.media_set_id = bs.media_set_id
                          WHERE bmf.physical_device_name = @file ORDER BY bs.backup_finish_date DESC)
ORDER BY bf.file_type, bf.logical_name;
