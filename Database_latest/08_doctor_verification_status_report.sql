/* =====================================================================
   MedMind - Doctor verification rollout  |  Script 08: Status report
   READ-ONLY. Changes nothing: queries, PRINT and session SET options only;
   no INSERT, UPDATE, DELETE, MERGE, DDL, EXEC or dynamic SQL. OPT-IN: run
   it yourself, only on MedMind_Audit_Final2, before the migration
   c3d9e6a2f8b1 is applied and before DOCTOR_VERIFICATION_ENFORCED=true is
   considered. Nothing here implies that either has happened.

   RUN THE WHOLE SCRIPT, NEVER A PARTIAL SELECTION. The database guard
   below protects only a full run: a highlighted selection skips it.
   First confirm the target with:  SELECT DB_NAME();
   Recommended (-C trusts the local server certificate, -I sets
   QUOTED_IDENTIFIER ON, needed by section 2; -b stops at the first error):
     sqlcmd -S localhost\SQLEXPRESS -E -C -I -b -d MedMind_Audit_Final2 -i 08_doctor_verification_status_report.sql

   It refuses to run on any other database, and stops if a table or column
   it needs is missing. Output: provider id and tenant key, counts, the
   alembic version, key and constraint metadata. No doctor names, licence
   numbers, contact details or patient data.

   "Future" means on or after today's date on the SQL Server (its local
   date, not each provider's time zone): an approximation for planning.
   ===================================================================== */

IF DB_NAME() <> N'MedMind_Audit_Final2'
BEGIN
    RAISERROR(N'Refused: this report runs only on MedMind_Audit_Final2.', 16, 1);
    SET NOEXEC ON;
END
GO

/* Required objects (columns per the checked-in schema export,
   Database file.sql). COL_LENGTH is NULL for a missing table or column. */
DECLARE @missing nvarchar(1000) = N'';
IF COL_LENGTH(N'dbo.doctors', N'provider_id') IS NULL SET @missing += N' doctors.provider_id';
IF COL_LENGTH(N'dbo.doctors', N'verification_status') IS NULL SET @missing += N' doctors.verification_status';
IF COL_LENGTH(N'dbo.doctors', N'is_active') IS NULL SET @missing += N' doctors.is_active';
IF COL_LENGTH(N'dbo.providers', N'tenant_key') IS NULL SET @missing += N' providers.tenant_key';
IF COL_LENGTH(N'dbo.doctor_availability_slots', N'doctor_id') IS NULL SET @missing += N' doctor_availability_slots.doctor_id';
IF COL_LENGTH(N'dbo.doctor_availability_slots', N'provider_id') IS NULL SET @missing += N' doctor_availability_slots.provider_id';
IF COL_LENGTH(N'dbo.doctor_availability_slots', N'slot_date') IS NULL SET @missing += N' doctor_availability_slots.slot_date';
IF COL_LENGTH(N'dbo.doctor_availability_slots', N'status') IS NULL SET @missing += N' doctor_availability_slots.status';
IF COL_LENGTH(N'dbo.appointments', N'doctor_id') IS NULL SET @missing += N' appointments.doctor_id';
IF COL_LENGTH(N'dbo.appointments', N'provider_id') IS NULL SET @missing += N' appointments.provider_id';
IF COL_LENGTH(N'dbo.appointments', N'scheduled_date') IS NULL SET @missing += N' appointments.scheduled_date';
IF COL_LENGTH(N'dbo.appointments', N'status') IS NULL SET @missing += N' appointments.status';
IF @missing <> N''
BEGIN
    RAISERROR(N'Refused: required objects not found:%s', 16, 1, @missing);
    SET NOEXEC ON;
END
GO

SET NOCOUNT ON;
DECLARE @today date = CAST(SYSDATETIME() AS date);

PRINT N'--- 1. Alembic version (code head c3d9e6a2f8b1; before the migration expect a8c2e5f1b7d4) ---';
IF OBJECT_ID(N'dbo.alembic_version', N'U') IS NOT NULL
    SELECT version_num AS alembic_version FROM dbo.alembic_version;
ELSE
    SELECT N'alembic_version table not found' AS alembic_version;

PRINT N'--- 2. Unique keys and unique indexes on the foreign-key target tables ---';
SELECT
    OBJECT_NAME(i.object_id) AS table_name,
    i.name AS key_name,
    CASE WHEN i.is_primary_key = 1 THEN N'primary key'
         WHEN i.is_unique_constraint = 1 THEN N'unique constraint'
         ELSE N'unique index' END AS key_type,
    i.has_filter,
    i.is_disabled,
    STUFF((
        SELECT N', ' + c.name
        FROM sys.index_columns AS ic
        JOIN sys.columns AS c
            ON c.object_id = ic.object_id AND c.column_id = ic.column_id
        WHERE ic.object_id = i.object_id
          AND ic.index_id = i.index_id
          AND ic.is_included_column = 0
        ORDER BY ic.key_ordinal
        FOR XML PATH(''), TYPE
    ).value(N'.', N'nvarchar(400)'), 1, 2, N'') AS key_columns
FROM sys.indexes AS i
WHERE i.object_id IN (OBJECT_ID(N'dbo.doctors'), OBJECT_ID(N'dbo.provider_memberships'))
  AND i.is_unique = 1
ORDER BY table_name, key_name;

PRINT N'--- 3. Migration prerequisites (from section 2) ---';
/* doctors: an enabled PRIMARY KEY or UNIQUE constraint on exactly
   (id, provider_id), in that key order. Constraints cannot be filtered.
   Conservative: a plain unique index is not counted (see section 2). */
SELECT
    CASE WHEN EXISTS (
        SELECT 1 FROM sys.key_constraints AS kc
        JOIN sys.indexes AS i
            ON i.object_id = kc.parent_object_id AND i.index_id = kc.unique_index_id
        WHERE kc.parent_object_id = OBJECT_ID(N'dbo.doctors')
          AND kc.type IN ('PK', 'UQ')
          AND i.is_disabled = 0
          AND (SELECT COUNT(*) FROM sys.index_columns AS ic
               WHERE ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id
                 AND ic.is_included_column = 0) = 2
          AND EXISTS (SELECT 1 FROM sys.index_columns AS ic JOIN sys.columns AS c
                      ON c.object_id = ic.object_id AND c.column_id = ic.column_id
                      WHERE ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id
                        AND ic.key_ordinal = 1 AND c.name = N'id')
          AND EXISTS (SELECT 1 FROM sys.index_columns AS ic JOIN sys.columns AS c
                      ON c.object_id = ic.object_id AND c.column_id = ic.column_id
                      WHERE ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id
                        AND ic.key_ordinal = 2 AND c.name = N'provider_id'))
         THEN N'present' ELSE N'MISSING - the migration would fail (needs an enabled unique key on doctors (id, provider_id))'
    END AS doctors_id_provider_key,
    /* The new constraint's name must be free as a schema object of any type
       (OBJECT_ID without a type) and as an index name on provider_memberships
       (indexes are not schema objects, so OBJECT_ID cannot see them). */
    CASE WHEN OBJECT_ID(N'dbo.uq_provider_memberships_id_user_provider') IS NULL
          AND NOT EXISTS (SELECT 1 FROM sys.indexes AS i
                          WHERE i.object_id = OBJECT_ID(N'dbo.provider_memberships')
                            AND i.name = N'uq_provider_memberships_id_user_provider')
         THEN N'absent (expected: the migration creates it)'
         ELSE N'ALREADY PRESENT - the migration would fail on a duplicate name'
    END AS memberships_id_user_provider_key;

PRINT N'--- 4. Verification check constraints on dbo.doctors (by definition, any name) ---';
SELECT
    cc.name AS constraint_name,
    cc.definition,
    cc.is_disabled,
    cc.is_not_trusted
FROM sys.check_constraints AS cc
WHERE cc.parent_object_id = OBJECT_ID(N'dbo.doctors')
  AND cc.definition LIKE N'%verification_status%';
SELECT COUNT(*) AS verification_check_constraint_count
FROM sys.check_constraints AS cc
WHERE cc.parent_object_id = OBJECT_ID(N'dbo.doctors')
  AND cc.definition LIKE N'%verification_status%';

PRINT N'--- 5. Doctors per provider by verification_status and is_active ---';
SELECT
    d.provider_id,
    p.tenant_key,
    d.verification_status,
    d.is_active,
    COUNT(*) AS doctor_count
FROM dbo.doctors AS d
LEFT JOIN dbo.providers AS p
    ON p.id = d.provider_id
GROUP BY d.provider_id, p.tenant_key, d.verification_status, d.is_active
ORDER BY p.tenant_key, d.verification_status, d.is_active;

PRINT N'--- 6. Totals by verification_status and is_active ---';
SELECT
    d.verification_status,
    d.is_active,
    COUNT(*) AS doctor_count
FROM dbo.doctors AS d
GROUP BY d.verification_status, d.is_active
ORDER BY d.verification_status, d.is_active;

PRINT N'--- 7. Active doctors that enforcement would hide (active, not verified), per provider ---';
SELECT
    d.provider_id,
    p.tenant_key,
    SUM(CASE WHEN d.verification_status = N'verified' THEN 1 ELSE 0 END) AS active_verified,
    SUM(CASE WHEN d.verification_status IS NULL OR d.verification_status <> N'verified' THEN 1 ELSE 0 END)
        AS active_would_be_hidden
FROM dbo.doctors AS d
LEFT JOIN dbo.providers AS p
    ON p.id = d.provider_id
WHERE d.is_active = 1
GROUP BY d.provider_id, p.tenant_key
ORDER BY p.tenant_key;

PRINT N'--- 8. Future available slots of doctors that would be hidden, per provider ---';
SELECT
    s.provider_id,
    p.tenant_key,
    COUNT(*) AS future_available_slots
FROM dbo.doctor_availability_slots AS s
JOIN dbo.doctors AS d
    ON d.id = s.doctor_id AND d.provider_id = s.provider_id
LEFT JOIN dbo.providers AS p
    ON p.id = s.provider_id
WHERE d.is_active = 1
  AND (d.verification_status IS NULL OR d.verification_status <> N'verified')
  AND s.status = N'available'
  AND s.slot_date >= @today
GROUP BY s.provider_id, p.tenant_key
ORDER BY p.tenant_key;

PRINT N'--- 9. Future active appointments (pending or confirmed) with doctors that would be hidden, per provider ---';
SELECT
    a.provider_id,
    p.tenant_key,
    COUNT(*) AS future_active_appointments
FROM dbo.appointments AS a
JOIN dbo.doctors AS d
    ON d.id = a.doctor_id AND d.provider_id = a.provider_id
LEFT JOIN dbo.providers AS p
    ON p.id = a.provider_id
WHERE d.is_active = 1
  AND (d.verification_status IS NULL OR d.verification_status <> N'verified')
  AND a.status IN (N'pending', N'confirmed')
  AND a.scheduled_date >= @today
GROUP BY a.provider_id, p.tenant_key
ORDER BY p.tenant_key;

PRINT N'--- 10. Is the decision-history table present (migration c3d9e6a2f8b1)? ---';
SELECT
    CASE WHEN OBJECT_ID(N'dbo.doctor_verification_decisions', N'U') IS NULL
         THEN N'absent (the migration has not been applied)'
         ELSE N'present'
    END AS doctor_verification_decisions_table;
GO

/* Resets the session option only after every query above. */
SET NOEXEC OFF;
GO
