/* =====================================================================
   S6 - DROP a synthetic concurrency database. DESTRUCTIVE AND IRREVERSIBLE.
   Never run without explicit S6 approval.

   Run ONLY through Invoke-SyntheticGate.ps1 -Gate S6 -SynthName ...
   -ConfirmName ... -TokenSha256 ... -Approved. The runner connects to master
   (fixed), checks @@SERVERNAME and binds @synthetic_name, @confirm_name and
   @token_sha256 as typed parameters. The identifier is only ever built with
   QUOTENAME() from the validated name.

   Fails closed. Drops nothing unless ALL of these hold:
     - expected server, in master; the name is exactly
       MedMind_SynthConc_<YYYYMMDD>_<6 lowercase hex>, the confirmation
       equals it (binary), it is not protected and not a restored scratch
       copy (MedMind_ConcScratch_*);
     - exactly one database has exactly that name; not a snapshot; ONLINE
       (any other state is refused: manual review);
     - msdb has never restored into that name (a restored database is never
       synthetic: refused);
     - exactly two files, at exactly the S1 paths, used by no other database;
     - a guarded inspection of the database succeeds (any error is refused
       with the original SQL error), and EITHER
         (a) the synthetic marker exists, holds exactly one row for this
             database, kind synthetic, with this token, AND the schema is
             exactly the generated synthetic schema (38 tables + marker);
       OR, for a partially created database (S1 done, S2 or S3 failed; both
       are all-or-nothing transactions):
         (b) no user object at all (S2 never committed), or
         (c) exactly the generated schema (38 tables, fingerprint below) with
             no marker and no row in any table except alembic_version (S3
             never committed). Row counts come from sys.partitions.
   Anything else (a database with data but no marker, a different schema,
   a marker for another token) is refused.
   Schema fingerprint: 98FC3E012B8644CBEE3E674102E76708132A58A83CB482B09EAB24FD0A55AFE6
   ===================================================================== */
SET NOCOUNT ON;
SET XACT_ABORT ON;

IF @@SERVERNAME <> N'LAPTOP-FACHLL1N\SQLEXPRESS'
    THROW 52600, N'Refused: unexpected server.', 1;
IF DB_NAME() <> N'master'
    THROW 52601, N'Refused: S6 must run in master.', 1;
IF @synthetic_name IS NULL
   OR DATALENGTH(@synthetic_name) <> 66
   OR @synthetic_name COLLATE Latin1_General_BIN NOT LIKE
      N'MedMind[_]SynthConc[_][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][_][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'
    THROW 52602, N'Refused: the name is not MedMind_SynthConc_<YYYYMMDD>_<6 lowercase hex>.', 1;
IF @confirm_name IS NULL OR @confirm_name COLLATE Latin1_General_BIN <> @synthetic_name COLLATE Latin1_General_BIN
    THROW 52603, N'Refused: the confirmation does not equal the synthetic name.', 1;
IF LOWER(@synthetic_name) IN (N'medmind_booking_db', N'medmind_audit_final2', N'medmind_audit_final')
   OR LOWER(@synthetic_name) LIKE N'medmind[_]audit%' OR LOWER(@synthetic_name) LIKE N'medmind[_]booking%'
   OR LOWER(@synthetic_name) LIKE N'medmind[_]concscratch%'
    THROW 52604, N'Refused: protected or restored-copy database name.', 1;
IF @token_sha256 IS NULL
   OR DATALENGTH(@token_sha256) <> 128
   OR @token_sha256 COLLATE Latin1_General_BIN LIKE N'%[^0-9a-f]%'
    THROW 52605, N'Refused: the token hash must be 64 lowercase hex characters.', 1;

DECLARE @db sysname = @synthetic_name;
IF (SELECT COUNT(*) FROM sys.databases WHERE name COLLATE Latin1_General_BIN = @db COLLATE Latin1_General_BIN) <> 1
    THROW 52606, N'Refused: exactly one database with exactly this name must exist.', 1;
DECLARE @db_id int = DB_ID(@db);
IF @db_id IS NULL
   OR EXISTS (SELECT 1 FROM sys.databases WHERE database_id = @db_id AND source_database_id IS NOT NULL)
    THROW 52607, N'Refused: the target is missing or a database snapshot.', 1;
IF NOT EXISTS (SELECT 1 FROM sys.databases WHERE database_id = @db_id AND state_desc = N'ONLINE')
    THROW 52608, N'Refused: the database is not ONLINE; S6 handles only ONLINE databases (manual review).', 1;
IF EXISTS (SELECT 1 FROM msdb.dbo.restorehistory WHERE destination_database_name = @db)
    THROW 52609, N'Refused: msdb shows a RESTORE into this name; a synthetic database is never restored.', 1;

DECLARE @data_dir nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(260));
DECLARE @log_dir nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultLogPath') AS nvarchar(260));
IF @data_dir IS NULL OR @log_dir IS NULL
    THROW 52610, N'Refused: the instance has no default data or log path.', 1;
IF RIGHT(@data_dir, 1) <> N'\' SET @data_dir += N'\';
IF RIGHT(@log_dir, 1) <> N'\' SET @log_dir += N'\';
DECLARE @data_file nvarchar(400) = @data_dir + @db + N'_data.mdf';
DECLARE @log_file nvarchar(400) = @log_dir + @db + N'_log.ldf';
IF (SELECT COUNT(*) FROM sys.master_files WHERE database_id = @db_id) <> 2
   OR NOT EXISTS (SELECT 1 FROM sys.master_files
                  WHERE database_id = @db_id AND type = 0 AND LOWER(physical_name) = LOWER(@data_file))
   OR NOT EXISTS (SELECT 1 FROM sys.master_files
                  WHERE database_id = @db_id AND type = 1 AND LOWER(physical_name) = LOWER(@log_file))
    THROW 52611, N'Refused: the database files are not exactly the S1 paths.', 1;
IF EXISTS (SELECT 1 FROM sys.master_files
           WHERE database_id <> @db_id AND LOWER(physical_name) IN (LOWER(@data_file), LOWER(@log_file)))
    THROW 52612, N'Refused: another database uses the synthetic file paths.', 1;

-- Guarded inspection, executed inside the target database through its own
-- sp_executesql. Any error (unreadable, single-user held, ...) is a refusal.
DECLARE @proc nvarchar(400) = QUOTENAME(@db) + N'.sys.sp_executesql';
DECLARE @user_tables int = NULL, @user_objects int = NULL, @marker int = NULL, @total_rows bigint = NULL,
        @fingerprint varbinary(32) = NULL, @marker_rows int = NULL, @marker_matching int = NULL,
        @probe_error nvarchar(2048) = NULL;
DECLARE @probe nvarchar(max) = N'SELECT
    @user_tables = (SELECT COUNT(*) FROM sys.tables WHERE is_ms_shipped = 0),
    @user_objects = (SELECT COUNT(*) FROM sys.objects WHERE is_ms_shipped = 0),
    @marker = CASE WHEN OBJECT_ID(N''dbo.zz_synthetic_marker'', N''U'') IS NULL THEN 0 ELSE 1 END,
    @total_rows = (SELECT ISNULL(SUM(p.rows), 0) FROM sys.partitions AS p
                   JOIN sys.tables AS t ON t.object_id = p.object_id
                   WHERE t.is_ms_shipped = 0 AND p.index_id IN (0, 1)
                     AND t.name <> N''zz_synthetic_marker'' AND t.name <> N''alembic_version''),
    @fingerprint = (SELECT HASHBYTES(''SHA2_256'', STRING_AGG(CAST(t.name + N''.'' + c.name AS nvarchar(max)), NCHAR(10))
        WITHIN GROUP (ORDER BY t.name + N''.'' + c.name COLLATE Latin1_General_BIN2))
 FROM sys.tables AS t JOIN sys.columns AS c ON c.object_id = t.object_id
 WHERE t.schema_id = SCHEMA_ID(N''dbo'') AND t.is_ms_shipped = 0 AND t.name <> N''zz_synthetic_marker'');';
BEGIN TRY
    EXEC @proc @probe,
        N'@user_tables int OUTPUT, @user_objects int OUTPUT, @marker int OUTPUT, @total_rows bigint OUTPUT, @fingerprint varbinary(32) OUTPUT',
        @user_tables = @user_tables OUTPUT, @user_objects = @user_objects OUTPUT, @marker = @marker OUTPUT,
        @total_rows = @total_rows OUTPUT, @fingerprint = @fingerprint OUTPUT;
    IF @marker = 1
        EXEC @proc
            N'SELECT @rows = COUNT(*), @matching = SUM(CASE WHEN database_name COLLATE Latin1_General_BIN = @name COLLATE Latin1_General_BIN
                AND marker_kind = ''synthetic'' AND token_sha256 = @hash THEN 1 ELSE 0 END) FROM dbo.zz_synthetic_marker;',
            N'@name sysname, @hash char(64), @rows int OUTPUT, @matching int OUTPUT',
            @name = @db, @hash = @token_sha256, @rows = @marker_rows OUTPUT, @matching = @marker_matching OUTPUT;
END TRY
BEGIN CATCH
    SET @probe_error = LEFT(CONCAT(N'Refused: the synthetic database could not be inspected (SQL error ',
                                   ERROR_NUMBER(), N': ', ERROR_MESSAGE(), N'); nothing was dropped.'), 2048);
END CATCH;
IF @probe_error IS NOT NULL
    THROW 52613, @probe_error, 1;
IF @user_tables IS NULL OR @user_objects IS NULL OR @marker IS NULL OR @total_rows IS NULL
    THROW 52614, N'Refused: the inspection returned no result; nothing was dropped.', 1;

DECLARE @expected_fingerprint varbinary(32) = 0x98FC3E012B8644CBEE3E674102E76708132A58A83CB482B09EAB24FD0A55AFE6;
DECLARE @case nvarchar(40) = NULL;
IF @marker = 1
BEGIN
    IF @marker_rows IS NULL OR @marker_rows <> 1 OR ISNULL(@marker_matching, 0) <> 1
        THROW 52615, N'Refused: the synthetic marker does not hold exactly one row for this database and token.', 1;
    IF @user_tables <> 39 OR ISNULL(@fingerprint, 0x00) <> @expected_fingerprint
        THROW 52616, N'Refused: a marked database whose schema is not the generated synthetic schema.', 1;
    SET @case = N'marked';
END
ELSE IF @user_tables = 0 AND @user_objects = 0
    SET @case = N'partial: empty database';
ELSE IF @user_tables = 38 AND ISNULL(@fingerprint, 0x00) = @expected_fingerprint AND @total_rows = 0
    SET @case = N'partial: empty schema, no marker';
ELSE
    THROW 52617, N'Refused: no marker, and not an empty or schema-only synthetic database (manual review).', 1;

PRINT N'S6: dropping ' + @db + N' (' + @case + N')';
DECLARE @drop nvarchar(max) =
    N'ALTER DATABASE ' + QUOTENAME(@db) + N' SET SINGLE_USER WITH ROLLBACK IMMEDIATE; '
  + N'DROP DATABASE ' + QUOTENAME(@db) + N';';
EXEC (@drop);

IF DB_ID(@db) IS NOT NULL
    THROW 52618, N'S6: the synthetic database still exists (it may be left SINGLE_USER).', 1;
SELECT @db AS dropped_database, @case AS dropped_case,
       (SELECT file_exists FROM sys.dm_os_file_exists(@data_file)) AS data_file_left,
       (SELECT file_exists FROM sys.dm_os_file_exists(@log_file)) AS log_file_left;
