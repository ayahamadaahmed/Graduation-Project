/* =====================================================================
   G7 - DROP the scratch database. DESTRUCTIVE AND IRREVERSIBLE.
   Never run without explicit G7 approval.

   Run ONLY through Invoke-ScratchGate.ps1 -Gate G7 -ScratchName ...
   -ConfirmName ... -TokenSha256 ... -Approved. The runner connects to
   master (fixed), checks @@SERVERNAME, and binds @scratch_name,
   @confirm_name and @token_sha256 as typed parameters. No value is
   text-substituted; the database identifier is only ever built with
   QUOTENAME() from the validated name.

   Fails closed. Drops nothing unless ALL of these hold:
     - expected server, in master;
     - the scratch name is exactly the scratch pattern, and the confirmation
       equals it (binary comparison);
     - the name is not protected (MedMind_Booking_DB, MedMind_Audit_Final2,
       MedMind_Audit_Final, MedMind_Audit*, MedMind_Booking*), in any case;
     - exactly one database has exactly that name, and it is not a snapshot;
     - its dbo.zz_scratch_marker holds exactly one row whose scratch_name is
       that name, source_db is MedMind_Audit_Final2 and token_sha256 matches.
   If the marker cannot be read (missing table, database not online or held
   by another session), THROW 50710 stops the batch before the drop and
   carries the original SQL error number and message. If it can be read but
   does not hold exactly one matching row, THROW 50708 stops it. A scratch
   copy WITHOUT a marker (partial restore, failed G4b) is handled only by
   the recovery gates R1/R2.
   ===================================================================== */
SET NOCOUNT ON;
SET XACT_ABORT ON;

IF @@SERVERNAME <> N'LAPTOP-FACHLL1N\SQLEXPRESS'
    THROW 50700, N'Refused: unexpected server.', 1;
IF DB_NAME() <> N'master'
    THROW 50701, N'Refused: G7 must run in master.', 1;
IF @scratch_name IS NULL
   OR DATALENGTH(@scratch_name) <> 70
   OR @scratch_name COLLATE Latin1_General_BIN NOT LIKE
      N'MedMind[_]ConcScratch[_][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][_][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'
    THROW 50702, N'Refused: the scratch name is not MedMind_ConcScratch_<YYYYMMDD>_<6 lowercase hex>.', 1;
IF @confirm_name IS NULL OR @confirm_name COLLATE Latin1_General_BIN <> @scratch_name COLLATE Latin1_General_BIN
    THROW 50703, N'Refused: the confirmation does not equal the scratch name.', 1;
IF LOWER(@scratch_name) IN (N'medmind_booking_db', N'medmind_audit_final2', N'medmind_audit_final')
   OR LOWER(@scratch_name) LIKE N'medmind[_]audit%' OR LOWER(@scratch_name) LIKE N'medmind[_]booking%'
    THROW 50704, N'Refused: protected database name.', 1;
IF @token_sha256 IS NULL
   OR DATALENGTH(@token_sha256) <> 128
   OR @token_sha256 COLLATE Latin1_General_BIN LIKE N'%[^0-9a-f]%'
    THROW 50705, N'Refused: the token hash must be 64 lowercase hex characters.', 1;

DECLARE @scratch sysname = @scratch_name;
IF (SELECT COUNT(*) FROM sys.databases WHERE name COLLATE Latin1_General_BIN = @scratch COLLATE Latin1_General_BIN) <> 1
    THROW 50706, N'Refused: exactly one database with exactly this name must exist.', 1;
IF EXISTS (SELECT 1 FROM sys.databases WHERE name = @scratch AND source_database_id IS NOT NULL)
    THROW 50707, N'Refused: the target is a database snapshot.', 1;

DECLARE @rows int, @matching int, @probe_error nvarchar(2048) = NULL;
DECLARE @check nvarchar(max) =
    N'SELECT @rows = COUNT(*), '
  + N'@matching = SUM(CASE WHEN scratch_name = @name AND source_db = N''MedMind_Audit_Final2'' '
  + N'AND token_sha256 = @hash THEN 1 ELSE 0 END) FROM ' + QUOTENAME(@scratch) + N'.dbo.zz_scratch_marker';
BEGIN TRY
    EXEC sys.sp_executesql @check,
        N'@name sysname, @hash char(64), @rows int OUTPUT, @matching int OUTPUT',
        @name = @scratch, @hash = @token_sha256, @rows = @rows OUTPUT, @matching = @matching OUTPUT;
END TRY
BEGIN CATCH
    SET @rows = NULL;
    SET @probe_error = LEFT(CONCAT(N'Refused: the scratch marker could not be read (SQL error ',
                                   ERROR_NUMBER(), N': ', ERROR_MESSAGE(), N'); nothing was dropped.'), 2048);
END CATCH;
IF @probe_error IS NOT NULL
    THROW 50710, @probe_error, 1;
IF @rows IS NULL OR @rows <> 1 OR ISNULL(@matching, 0) <> 1
    THROW 50708, N'Refused: the scratch marker does not hold exactly one row matching this name, source and token.', 1;

PRINT N'G7: dropping ' + @scratch;
DECLARE @drop nvarchar(max) =
    N'ALTER DATABASE ' + QUOTENAME(@scratch) + N' SET SINGLE_USER WITH ROLLBACK IMMEDIATE; '
  + N'DROP DATABASE ' + QUOTENAME(@scratch) + N';';
EXEC (@drop);

IF DB_ID(@scratch) IS NOT NULL
    THROW 50709, N'G7: the scratch database still exists (it may be left SINGLE_USER).', 1;
SELECT @scratch AS dropped_database, CASE WHEN DB_ID(@scratch) IS NULL THEN 'gone' ELSE 'STILL PRESENT' END AS state;
