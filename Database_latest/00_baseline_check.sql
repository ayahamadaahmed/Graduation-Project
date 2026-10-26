/* =====================================================================
   MedMind - |  Script 00: Baseline check
   READ-ONLY. Changes nothing. Run this first on the restored database.

   Select the MedMind database in SSMS before running (not master).
   Expected on the restored .bak:  alembic_version = a5e30b966d98
   ===================================================================== */

IF DB_ID() <= 4 OR OBJECT_ID(N'dbo.providers', N'U') IS NULL
BEGIN
    RAISERROR(N'Select the restored MedMind database first (dbo.providers not found).', 16, 1);
    SET NOEXEC ON;
END
GO

PRINT N'--- 1. Alembic version (expected a5e30b966d98) ---';
SELECT version_num AS alembic_version,
       CASE WHEN version_num = N'a5e30b966d98' THEN N'OK - at head' ELSE N'MISMATCH - investigate before changing anything' END AS verdict
FROM dbo.alembic_version;

PRINT N'--- 2. Table count (script snapshot had 30 incl. alembic_version) ---';
SELECT COUNT(*) AS table_count FROM sys.tables WHERE schema_id = SCHEMA_ID(N'dbo');

PRINT N'--- 3. Row counts per table ---';
SELECT t.name AS table_name, SUM(p.rows) AS row_count
FROM sys.tables t
JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1)
WHERE t.schema_id = SCHEMA_ID(N'dbo')
GROUP BY t.name
ORDER BY t.name;

PRINT N'--- 4. Providers currently configured ---';
SELECT tenant_key, name, org_type, is_active FROM dbo.providers ORDER BY tenant_key;

PRINT N'--- 5. Do the sprint objects already exist? (1 = already there) ---';

SELECT
    CASE WHEN OBJECT_ID(N'dbo.patient_conditions', N'U') IS NOT NULL THEN 1 ELSE 0 END AS patient_conditions,
    CASE WHEN OBJECT_ID(N'dbo.patient_allergies', N'U') IS NOT NULL THEN 1 ELSE 0 END AS patient_allergies,
    CASE WHEN OBJECT_ID(N'dbo.patient_medications', N'U') IS NOT NULL THEN 1 ELSE 0 END AS patient_medications,
    CASE WHEN OBJECT_ID(N'dbo.clinical_notes', N'U') IS NOT NULL THEN 1 ELSE 0 END AS clinical_notes,
    CASE WHEN OBJECT_ID(N'dbo.patient_access_grants', N'U') IS NOT NULL THEN 1 ELSE 0 END AS patient_access_grants;

PRINT N'--- 6. Staff accounts (the sprint needs at least one per role) ---';
SELECT (SELECT COUNT(*) FROM dbo.user_accounts)       AS user_accounts,
       (SELECT COUNT(*) FROM dbo.provider_memberships) AS provider_memberships;

PRINT N'--- 7. Constraints that are disabled or not trusted (should be empty) ---';
SELECT OBJECT_NAME(parent_object_id) AS table_name, name AS constraint_name, N'FOREIGN KEY' AS kind
FROM sys.foreign_keys WHERE is_disabled = 1 OR is_not_trusted = 1
UNION ALL
SELECT OBJECT_NAME(parent_object_id), name, N'CHECK'
FROM sys.check_constraints WHERE is_disabled = 1 OR is_not_trusted = 1;
GO
SET NOEXEC OFF;
GO
