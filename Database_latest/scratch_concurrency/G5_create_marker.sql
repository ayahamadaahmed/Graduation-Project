/* =====================================================================
   G5 - Create the scratch marker in the restored copy.
   WRITE-CAPABLE (scratch copy only): one new table, one row. Never run
   without explicit G5 approval, and only after G4b and the fingerprint
   comparison passed.

   Run ONLY through Invoke-ScratchGate.ps1 -Gate G5 -ScratchName ...
   -TokenSha256 ... -Approved. The runner connects to the validated scratch
   database and binds @scratch_name and @token_sha256 as typed parameters.
   Only the token's SHA-256 is stored; the token itself stays in the test
   process environment (MEDMIND_SCRATCH_TOKEN).
   ===================================================================== */
SET NOCOUNT ON;
SET XACT_ABORT ON;

IF @@SERVERNAME <> N'LAPTOP-FACHLL1N\SQLEXPRESS'
    THROW 50500, N'Refused: unexpected server.', 1;
IF @scratch_name IS NULL
   OR DATALENGTH(@scratch_name) <> 70
   OR @scratch_name COLLATE Latin1_General_BIN NOT LIKE
      N'MedMind[_]ConcScratch[_][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][_][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'
   OR LOWER(@scratch_name) LIKE N'medmind[_]audit%' OR LOWER(@scratch_name) LIKE N'medmind[_]booking%'
    THROW 50501, N'Refused: not a scratch database name.', 1;
IF DB_NAME() COLLATE Latin1_General_BIN <> @scratch_name COLLATE Latin1_General_BIN
    THROW 50502, N'Refused: not connected to the scratch database.', 1;
IF @token_sha256 IS NULL
   OR DATALENGTH(@token_sha256) <> 128
   OR @token_sha256 COLLATE Latin1_General_BIN LIKE N'%[^0-9a-f]%'
    THROW 50503, N'Refused: the token hash must be 64 lowercase hex characters.', 1;
IF (SELECT COUNT(*) FROM dbo.alembic_version) <> 1
   OR NOT EXISTS (SELECT 1 FROM dbo.alembic_version WHERE version_num = 'c3d9e6a2f8b1')
    THROW 50504, N'Refused: unexpected alembic revision.', 1;
IF OBJECT_ID(N'dbo.zz_scratch_marker', N'U') IS NOT NULL
    THROW 50505, N'Refused: the scratch marker already exists.', 1;

BEGIN TRANSACTION;
CREATE TABLE dbo.zz_scratch_marker (
    scratch_name sysname NOT NULL,
    source_db sysname NOT NULL,
    token_sha256 char(64) NOT NULL,
    created_at datetimeoffset NOT NULL CONSTRAINT DF_zz_scratch_marker_created DEFAULT SYSDATETIMEOFFSET()
);
INSERT INTO dbo.zz_scratch_marker (scratch_name, source_db, token_sha256)
VALUES (DB_NAME(), N'MedMind_Audit_Final2', @token_sha256);
COMMIT TRANSACTION;

SELECT scratch_name, source_db, created_at FROM dbo.zz_scratch_marker;
