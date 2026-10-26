/* =====================================================================
   S0 - READ-ONLY instance readiness for a synthetic concurrency database.
   SELECT/IF/THROW only, in master. Reads no user database at all (in
   particular never MedMind_Booking_DB or MedMind_Audit_Final2).

   Run ONLY through Invoke-SyntheticGate.ps1 -Gate S0 -SynthName ...
   The runner connects to master (fixed), checks @@SERVERNAME and binds
   @synthetic_name as a typed parameter. No text substitution.

   Reports: server and version; default data/log paths; the model
   database's isolation settings (a new database inherits them; S1 sets
   them explicitly anyway), compatibility level and collation (a new
   database inherits both; S1 does not set them yet, see
   PROPOSED_S1_COMPATIBILITY_LEVEL.md) and its count of user objects (a new
   database starts with a copy of them); whether any database already has this name (any
   case); whether the S1 target files already exist; whether msdb has ever
   restored into this name; free space on the master data volume.
   ===================================================================== */
SET NOCOUNT ON;

IF @@SERVERNAME <> N'LAPTOP-FACHLL1N\SQLEXPRESS'
    THROW 52000, N'Refused: unexpected server.', 1;
IF @synthetic_name IS NULL
   OR DATALENGTH(@synthetic_name) <> 66
   OR @synthetic_name COLLATE Latin1_General_BIN NOT LIKE
      N'MedMind[_]SynthConc[_][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][_][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'
    THROW 52001, N'Refused: the name is not MedMind_SynthConc_<YYYYMMDD>_<6 lowercase hex>.', 1;
IF LOWER(@synthetic_name) IN (N'medmind_booking_db', N'medmind_audit_final2', N'medmind_audit_final')
   OR LOWER(@synthetic_name) LIKE N'medmind[_]audit%' OR LOWER(@synthetic_name) LIKE N'medmind[_]booking%'
   OR LOWER(@synthetic_name) LIKE N'medmind[_]concscratch%'
    THROW 52002, N'Refused: protected or restored-copy database name.', 1;
IF DB_NAME() <> N'master'
    THROW 52003, N'Refused: S0 must run in master.', 1;

DECLARE @db sysname = @synthetic_name;
DECLARE @data_dir nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(260));
DECLARE @log_dir nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultLogPath') AS nvarchar(260));
IF @data_dir IS NULL OR @log_dir IS NULL
    THROW 52004, N'Refused: the instance has no default data or log path.', 1;
IF RIGHT(@data_dir, 1) <> N'\' SET @data_dir += N'\';
IF RIGHT(@log_dir, 1) <> N'\' SET @log_dir += N'\';
DECLARE @data_file nvarchar(400) = @data_dir + @db + N'_data.mdf';
DECLARE @log_file nvarchar(400) = @log_dir + @db + N'_log.ldf';

SELECT @@SERVERNAME AS server_name,
       CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(128)) AS product_version,
       CAST(SERVERPROPERTY('Edition') AS nvarchar(128)) AS edition,
       @data_dir AS default_data_path, @log_dir AS default_log_path;
SELECT name, is_read_committed_snapshot_on, snapshot_isolation_state_desc, recovery_model_desc,
       compatibility_level, collation_name,
       (SELECT COUNT(*) FROM model.sys.objects WHERE is_ms_shipped = 0) AS user_objects
FROM sys.databases WHERE name = N'model';
SELECT COUNT(*) AS databases_with_this_name_any_case FROM sys.databases WHERE LOWER(name) = LOWER(@db);
SELECT N'data' AS kind, @data_file AS path, f.file_exists FROM sys.dm_os_file_exists(@data_file) AS f
UNION ALL SELECT N'log', @log_file, f.file_exists FROM sys.dm_os_file_exists(@log_file) AS f;
SELECT COUNT(*) AS restore_history_rows_for_this_name
FROM msdb.dbo.restorehistory WHERE destination_database_name = @db;
SELECT vs.available_bytes / 1048576 AS free_mb_on_master_data_volume
FROM sys.master_files AS mf
CROSS APPLY sys.dm_os_volume_stats(mf.database_id, mf.file_id) AS vs
WHERE mf.database_id = 1 AND mf.file_id = 1;
