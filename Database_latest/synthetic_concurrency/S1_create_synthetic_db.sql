/* =====================================================================
   S1 - CREATE an empty synthetic concurrency database.
   WRITE-CAPABLE (instance level): creates ONE new database and its two
   files. Never run without explicit S1 approval.

   Run ONLY through Invoke-SyntheticGate.ps1 -Gate S1 -SynthName ... -Approved.
   The runner connects to master (fixed), checks @@SERVERNAME and binds
   @synthetic_name as a typed parameter. No text substitution: the name is
   only ever used through QUOTENAME(); file paths are embedded as escaped
   N'...' literals (QUOTENAME is not used for paths: it returns NULL for
   input over 128 characters, which would silently empty the statement).

   Refuses unless: expected server, in master; the name is exactly
   MedMind_SynthConc_<YYYYMMDD>_<6 lowercase hex> and not protected; no
   database has this name in any letter case; msdb has never restored into
   this name; the two target files do not exist.
   Creates the database with files <data path>\<name>_data.mdf and
   <log path>\<name>_log.ldf and COLLATE SQL_Latin1_General_CP1_CI_AS, then
   sets RECOVERY SIMPLE, READ_COMMITTED_SNAPSHOT OFF, ALLOW_SNAPSHOT_ISOLATION
   OFF, AUTO_CLOSE OFF and COMPATIBILITY_LEVEL = 170 (never inherited from
   model or the instance), and verifies all of it: state, recovery model,
   isolation, AUTO_CLOSE, compatibility level, collation and file paths.
   Level 170 and the collation are option B of
   PROPOSED_S1_COMPATIBILITY_LEVEL.md: the values S0 reported for model,
   not values taken from MedMind_Audit_Final2.

   If it fails after the database exists (for example while setting
   options), do not improvise: S6 drops a database that is still empty.
   ===================================================================== */
SET NOCOUNT ON;
SET XACT_ABORT ON;

IF @@SERVERNAME <> N'LAPTOP-FACHLL1N\SQLEXPRESS'
    THROW 52100, N'Refused: unexpected server.', 1;
IF @synthetic_name IS NULL
   OR DATALENGTH(@synthetic_name) <> 66
   OR @synthetic_name COLLATE Latin1_General_BIN NOT LIKE
      N'MedMind[_]SynthConc[_][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][_][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'
    THROW 52101, N'Refused: the name is not MedMind_SynthConc_<YYYYMMDD>_<6 lowercase hex>.', 1;
IF LOWER(@synthetic_name) IN (N'medmind_booking_db', N'medmind_audit_final2', N'medmind_audit_final')
   OR LOWER(@synthetic_name) LIKE N'medmind[_]audit%' OR LOWER(@synthetic_name) LIKE N'medmind[_]booking%'
   OR LOWER(@synthetic_name) LIKE N'medmind[_]concscratch%'
    THROW 52102, N'Refused: protected or restored-copy database name.', 1;
IF DB_NAME() <> N'master'
    THROW 52103, N'Refused: S1 must run in master.', 1;

DECLARE @db sysname = @synthetic_name;
IF DB_ID(@db) IS NOT NULL
   OR EXISTS (SELECT 1 FROM sys.databases WHERE LOWER(name) = LOWER(@db))
    THROW 52104, N'Refused: a database with this name already exists.', 1;
IF EXISTS (SELECT 1 FROM msdb.dbo.restorehistory WHERE destination_database_name = @db)
    THROW 52105, N'Refused: msdb shows a RESTORE into this name; choose a new synthetic name.', 1;

DECLARE @data_dir nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(260));
DECLARE @log_dir nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultLogPath') AS nvarchar(260));
IF @data_dir IS NULL OR @log_dir IS NULL
    THROW 52106, N'Refused: the instance has no default data or log path.', 1;
IF RIGHT(@data_dir, 1) <> N'\' SET @data_dir += N'\';
IF RIGHT(@log_dir, 1) <> N'\' SET @log_dir += N'\';
DECLARE @data_file nvarchar(400) = @data_dir + @db + N'_data.mdf';
DECLARE @log_file nvarchar(400) = @log_dir + @db + N'_log.ldf';
IF EXISTS (SELECT 1 FROM sys.dm_os_file_exists(@data_file) WHERE file_exists = 1)
   OR EXISTS (SELECT 1 FROM sys.dm_os_file_exists(@log_file) WHERE file_exists = 1)
    THROW 52107, N'Refused: a target file already exists.', 1;

DECLARE @create nvarchar(max) =
    N'CREATE DATABASE ' + QUOTENAME(@db)
  + N' ON PRIMARY (NAME = N''' + REPLACE(@db + N'_data', N'''', N'''''')
  + N''', FILENAME = N''' + REPLACE(@data_file, N'''', N'''''') + N''')'
  + N' LOG ON (NAME = N''' + REPLACE(@db + N'_log', N'''', N'''''')
  + N''', FILENAME = N''' + REPLACE(@log_file, N'''', N'''''') + N''')'
  + N' COLLATE SQL_Latin1_General_CP1_CI_AS;';
IF @create IS NULL
    THROW 52108, N'Refused: internal: the CREATE DATABASE statement is empty.', 1;

PRINT N'S1: creating ' + @db;
EXEC (@create);

DECLARE @options nvarchar(max) =
    N'ALTER DATABASE ' + QUOTENAME(@db) + N' SET RECOVERY SIMPLE; '
  + N'ALTER DATABASE ' + QUOTENAME(@db) + N' SET READ_COMMITTED_SNAPSHOT OFF; '
  + N'ALTER DATABASE ' + QUOTENAME(@db) + N' SET ALLOW_SNAPSHOT_ISOLATION OFF; '
  + N'ALTER DATABASE ' + QUOTENAME(@db) + N' SET AUTO_CLOSE OFF; '
  + N'ALTER DATABASE ' + QUOTENAME(@db) + N' SET COMPATIBILITY_LEVEL = 170;';
IF @options IS NULL
    THROW 52109, N'S1: internal: the ALTER DATABASE statement is empty (the empty database exists: use S6).', 1;
EXEC (@options);

DECLARE @db_id int = DB_ID(@db);
IF @db_id IS NULL
   OR NOT EXISTS (SELECT 1 FROM sys.databases
                  WHERE database_id = @db_id AND state_desc = N'ONLINE' AND is_read_only = 0
                    AND source_database_id IS NULL AND recovery_model_desc = N'SIMPLE'
                    AND is_read_committed_snapshot_on = 0 AND snapshot_isolation_state = 0
                    AND is_auto_close_on = 0 AND compatibility_level = 170
                    AND collation_name = N'SQL_Latin1_General_CP1_CI_AS')
    THROW 52110, N'S1: the database exists but its settings are not as required (it is empty: use S6).', 1;
IF (SELECT COUNT(*) FROM sys.master_files WHERE database_id = @db_id) <> 2
   OR NOT EXISTS (SELECT 1 FROM sys.master_files
                  WHERE database_id = @db_id AND type = 0 AND LOWER(physical_name) = LOWER(@data_file))
   OR NOT EXISTS (SELECT 1 FROM sys.master_files
                  WHERE database_id = @db_id AND type = 1 AND LOWER(physical_name) = LOWER(@log_file))
    THROW 52111, N'S1: the database files are not exactly the planned paths (it is empty: use S6).', 1;

SELECT d.name, d.state_desc, d.recovery_model_desc, d.is_read_committed_snapshot_on,
       d.snapshot_isolation_state_desc, d.is_auto_close_on, d.compatibility_level, d.collation_name,
       mf.type_desc, mf.physical_name
FROM sys.databases AS d
JOIN sys.master_files AS mf ON mf.database_id = d.database_id
WHERE d.database_id = @db_id;
