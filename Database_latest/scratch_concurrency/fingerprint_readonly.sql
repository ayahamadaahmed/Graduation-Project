/* =====================================================================
   READ-ONLY fingerprint of every dbo table (row count + checksum) and the
   object counts. SELECT statements only (one dynamic SELECT built from
   sys.tables, no writes, no temp tables).

   Run ONLY through Invoke-ScratchGate.ps1 -Gate ReferenceFingerprint
   (MedMind_Audit_Final2) or -Gate ScratchFingerprint -ScratchName ...
   The runner chooses the database itself and binds @expected_db to that
   same fixed value. No text substitution. The two outputs (minus the first
   identity line) must be identical.
   ===================================================================== */
SET NOCOUNT ON;

IF @@SERVERNAME <> N'LAPTOP-FACHLL1N\SQLEXPRESS'
    THROW 50460, N'Refused: unexpected server.', 1;
IF @expected_db IS NULL
   OR NOT (@expected_db COLLATE Latin1_General_BIN = N'MedMind_Audit_Final2'
           OR (DATALENGTH(@expected_db) = 70
               AND @expected_db COLLATE Latin1_General_BIN LIKE
                   N'MedMind[_]ConcScratch[_][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][_][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'))
    THROW 50461, N'Refused: the database must be MedMind_Audit_Final2 or a scratch name.', 1;
IF DB_NAME() COLLATE Latin1_General_BIN <> @expected_db COLLATE Latin1_General_BIN
    THROW 50462, N'Refused: not connected to the expected database.', 1;

SELECT DB_NAME() AS fingerprinted_database;

DECLARE @sql nvarchar(max);
SELECT @sql = STRING_AGG(CAST(
    N'SELECT N''' + REPLACE(t.name, N'''', N'''''') + N''' AS table_name, COUNT_BIG(*) AS row_count, '
    + N'CHECKSUM_AGG(BINARY_CHECKSUM(*)) AS table_checksum FROM dbo.' + QUOTENAME(t.name)
    AS nvarchar(max)), N' UNION ALL ') WITHIN GROUP (ORDER BY t.name)
FROM sys.tables AS t
WHERE t.schema_id = SCHEMA_ID(N'dbo') AND t.is_ms_shipped = 0 AND t.name <> N'zz_scratch_marker';
SET @sql = @sql + N' ORDER BY table_name';
EXEC sys.sp_executesql @sql;

SELECT (SELECT COUNT(*) FROM sys.tables WHERE is_ms_shipped = 0 AND name <> N'zz_scratch_marker') AS tables,
       (SELECT COUNT(*) FROM sys.foreign_keys) AS foreign_keys,
       (SELECT COUNT(*) FROM sys.check_constraints) AS check_constraints,
       (SELECT COUNT(*) FROM sys.indexes WHERE object_id > 100) AS indexes,
       (SELECT COUNT(*) FROM sys.triggers) AS triggers,
       (SELECT COUNT(*) FROM sys.views) AS views,
       (SELECT version_num FROM dbo.alembic_version) AS alembic_version;
