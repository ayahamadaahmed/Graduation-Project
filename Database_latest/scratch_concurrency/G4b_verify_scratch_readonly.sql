/* =====================================================================
   G4b - READ-ONLY identity check of a freshly restored scratch copy.
   SELECT statements only. Run before the marker (G5).

   Run ONLY through Invoke-ScratchGate.ps1 -Gate G4b -ScratchName ...
   The runner connects to the validated scratch database (read-only intent),
   checks @@SERVERNAME and binds @scratch_name. No text substitution.

   Refuses (THROW) unless connected to exactly that scratch database at the
   expected revision. Then run -Gate ScratchFingerprint and compare with
   -Gate ReferenceFingerprint: they must be identical.
   ===================================================================== */
SET NOCOUNT ON;

IF @@SERVERNAME <> N'LAPTOP-FACHLL1N\SQLEXPRESS'
    THROW 50450, N'Refused: unexpected server.', 1;
IF @scratch_name IS NULL
   OR DATALENGTH(@scratch_name) <> 70
   OR @scratch_name COLLATE Latin1_General_BIN NOT LIKE
      N'MedMind[_]ConcScratch[_][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][_][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'
   OR LOWER(@scratch_name) LIKE N'medmind[_]audit%' OR LOWER(@scratch_name) LIKE N'medmind[_]booking%'
    THROW 50451, N'Refused: not a scratch database name.', 1;
IF DB_NAME() COLLATE Latin1_General_BIN <> @scratch_name COLLATE Latin1_General_BIN
    THROW 50452, N'Refused: not connected to the scratch database.', 1;
IF (SELECT COUNT(*) FROM dbo.alembic_version) <> 1
   OR NOT EXISTS (SELECT 1 FROM dbo.alembic_version WHERE version_num = 'c3d9e6a2f8b1')
    THROW 50453, N'Refused: unexpected alembic revision.', 1;

SELECT DB_NAME() AS database_name, @@SERVERNAME AS server_name,
       (SELECT version_num FROM dbo.alembic_version) AS alembic_version,
       CASE WHEN OBJECT_ID(N'dbo.zz_scratch_marker', N'U') IS NULL THEN 'absent (expected before G5)' ELSE 'PRESENT' END AS marker;
SELECT d.state_desc, d.is_read_only, d.source_database_id, d.is_read_committed_snapshot_on,
       d.snapshot_isolation_state_desc, d.recovery_model_desc
FROM sys.databases AS d WHERE d.name = DB_NAME();
SELECT type_desc, name AS logical_name, physical_name FROM sys.database_files ORDER BY type;
SELECT COUNT(*) AS kept_zztest_dv_doctors FROM dbo.doctors WHERE license_number LIKE N'ZZTEST-DV-%';
