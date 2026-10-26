/* =====================================================================
   S4 - READ-ONLY proof that a database is exactly the synthetic one.
   GENERATED, do not edit: Backend/tools/generate_synthetic_sql.py.
   SELECT/IF/THROW only. Run ONLY through Invoke-SyntheticGate.ps1 -Gate S4
   -SynthName ... -TokenSha256 ...

   Refuses (THROW) unless: expected server; connected to exactly the named
   MedMind_SynthConc_* database; ONLINE, writable, not a snapshot, RCSI and
   snapshot isolation OFF; never a RESTORE target; exactly two files, at
   exactly the S1 paths; compatibility level 170 and collation
   SQL_Latin1_General_CP1_CI_AS (as S1 sets them); the marker holds exactly
   one row for this database, kind synthetic, fixture synthetic-v1, this token and the
   manifest SHA-256 below; the revision is c3d9e6a2f8b1; the schema fingerprint
   matches; every seeded table holds exactly its fixture rows; every other
   non-test table is empty; test-written tables hold only rows the tests
   could have created on this fixture.
   Fixture manifest SHA-256 32e97a4d2c4e1971fe1b24c42867113b9c87147cfc9d584ed5e132e61a09d9fa
   ===================================================================== */
SET NOCOUNT ON;

IF @@SERVERNAME <> N'LAPTOP-FACHLL1N\SQLEXPRESS'
    THROW 52400, N'Refused: unexpected server.', 1;
IF @synthetic_name IS NULL
   OR DATALENGTH(@synthetic_name) <> 66
   OR @synthetic_name COLLATE Latin1_General_BIN NOT LIKE
      N'MedMind[_]SynthConc[_][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][_][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'
    THROW 52401, N'Refused: the name is not MedMind_SynthConc_<YYYYMMDD>_<6 lowercase hex>.', 1;
IF LOWER(@synthetic_name) IN (N'medmind_booking_db', N'medmind_audit_final2', N'medmind_audit_final')
   OR LOWER(@synthetic_name) LIKE N'medmind[_]audit%' OR LOWER(@synthetic_name) LIKE N'medmind[_]booking%'
   OR LOWER(@synthetic_name) LIKE N'medmind[_]concscratch%'
    THROW 52402, N'Refused: protected or restored-copy database name.', 1;
IF DB_NAME() COLLATE Latin1_General_BIN <> @synthetic_name COLLATE Latin1_General_BIN
    THROW 52403, N'Refused: not connected to the named synthetic database.', 1;
IF NOT EXISTS (SELECT 1 FROM sys.databases
               WHERE name = DB_NAME() AND state_desc = N'ONLINE' AND is_read_only = 0
                 AND source_database_id IS NULL AND is_read_committed_snapshot_on = 0
                 AND snapshot_isolation_state = 0)
    THROW 52404, N'Refused: database must be ONLINE, writable, not a snapshot, with RCSI and snapshot isolation OFF.', 1;
IF EXISTS (SELECT 1 FROM msdb.dbo.restorehistory WHERE destination_database_name = DB_NAME())
    THROW 52405, N'Refused: this database name was the target of a RESTORE; a synthetic database is never restored.', 1;
DECLARE @data_dir nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(260));
DECLARE @log_dir nvarchar(260) = CAST(SERVERPROPERTY('InstanceDefaultLogPath') AS nvarchar(260));
IF @data_dir IS NULL OR @log_dir IS NULL
    THROW 52411, N'Refused: the instance has no default data or log path.', 1;
IF RIGHT(@data_dir, 1) <> N'\' SET @data_dir += N'\';
IF RIGHT(@log_dir, 1) <> N'\' SET @log_dir += N'\';
IF (SELECT COUNT(*) FROM sys.database_files) <> 2
   OR NOT EXISTS (SELECT 1 FROM sys.database_files
                  WHERE type = 0 AND LOWER(physical_name) = LOWER(@data_dir + DB_NAME() + N'_data.mdf'))
   OR NOT EXISTS (SELECT 1 FROM sys.database_files
                  WHERE type = 1 AND LOWER(physical_name) = LOWER(@log_dir + DB_NAME() + N'_log.ldf'))
    THROW 52412, N'Refused: the database files are not exactly the S1 paths.', 1;
IF NOT EXISTS (SELECT 1 FROM sys.databases
               WHERE name = DB_NAME() AND compatibility_level = 170
                 AND collation_name = N'SQL_Latin1_General_CP1_CI_AS')
    THROW 52413, N'Refused: compatibility level must be 170 and collation SQL_Latin1_General_CP1_CI_AS, as S1 sets them.', 1;
IF @token_sha256 IS NULL
   OR DATALENGTH(@token_sha256) <> 128
   OR @token_sha256 COLLATE Latin1_General_BIN LIKE N'%[^0-9a-f]%'
    THROW 52406, N'Refused: the token hash must be 64 lowercase hex characters.', 1;
IF OBJECT_ID(N'dbo.zz_synthetic_marker', N'U') IS NULL
    THROW 52407, N'Refused: no synthetic marker.', 1;
IF (SELECT COUNT(*) FROM dbo.zz_synthetic_marker) <> 1
   OR NOT EXISTS (SELECT 1 FROM dbo.zz_synthetic_marker
                  WHERE database_name COLLATE Latin1_General_BIN = DB_NAME() COLLATE Latin1_General_BIN
                    AND marker_kind = 'synthetic' AND fixture_version = 'synthetic-v1'
                    AND token_sha256 = @token_sha256 AND manifest_sha256 = '32e97a4d2c4e1971fe1b24c42867113b9c87147cfc9d584ed5e132e61a09d9fa')
    THROW 52408, N'Refused: the synthetic marker does not match this database, token or fixture.', 1;
IF OBJECT_ID(N'dbo.alembic_version', N'U') IS NULL
   OR (SELECT COUNT(*) FROM dbo.alembic_version) <> 1
   OR NOT EXISTS (SELECT 1 FROM dbo.alembic_version WHERE version_num = 'c3d9e6a2f8b1')
    THROW 52409, N'Refused: unexpected alembic revision.', 1;
IF ISNULL((SELECT HASHBYTES('SHA2_256', STRING_AGG(CAST(t.name + N'.' + c.name AS nvarchar(max)), NCHAR(10))
                  WITHIN GROUP (ORDER BY t.name + N'.' + c.name COLLATE Latin1_General_BIN2))
           FROM sys.tables AS t JOIN sys.columns AS c ON c.object_id = t.object_id
           WHERE t.schema_id = SCHEMA_ID(N'dbo') AND t.is_ms_shipped = 0 AND t.name <> N'zz_synthetic_marker'), 0x00)
   <> 0x98FC3E012B8644CBEE3E674102E76708132A58A83CB482B09EAB24FD0A55AFE6
    THROW 52410, N'Refused: the schema is not exactly the generated synthetic schema.', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.branch_mrn_sequences) <> 0
    THROW 52420, N'Refused: dbo.branch_mrn_sequences must hold exactly 0 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.branches) <> 1
    THROW 52421, N'Refused: dbo.branches must hold exactly 1 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.clinical_notes) <> 0
    THROW 52422, N'Refused: dbo.clinical_notes must hold exactly 0 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.department_specialties) <> 0
    THROW 52423, N'Refused: dbo.department_specialties must hold exactly 0 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.departments) <> 0
    THROW 52424, N'Refused: dbo.departments must hold exactly 0 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.diagnostic_assessments) <> 0
    THROW 52425, N'Refused: dbo.diagnostic_assessments must hold exactly 0 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.diagnostic_attachments) <> 0
    THROW 52426, N'Refused: dbo.diagnostic_attachments must hold exactly 0 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.doctor_schedule_exceptions) <> 0
    THROW 52427, N'Refused: dbo.doctor_schedule_exceptions must hold exactly 0 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.doctor_working_hours) <> 0
    THROW 52428, N'Refused: dbo.doctor_working_hours must hold exactly 0 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.ehr_encounters) <> 0
    THROW 52429, N'Refused: dbo.ehr_encounters must hold exactly 0 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.idempotency_requests) <> 0
    THROW 52430, N'Refused: dbo.idempotency_requests must hold exactly 0 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.lab_reports) <> 0
    THROW 52431, N'Refused: dbo.lab_reports must hold exactly 0 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.lab_results) <> 0
    THROW 52432, N'Refused: dbo.lab_results must hold exactly 0 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.patient_access_grants) <> 0
    THROW 52433, N'Refused: dbo.patient_access_grants must hold exactly 0 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.patient_allergies) <> 0
    THROW 52434, N'Refused: dbo.patient_allergies must hold exactly 0 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.patient_branch_profiles) <> 1
    THROW 52435, N'Refused: dbo.patient_branch_profiles must hold exactly 1 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.patient_conditions) <> 0
    THROW 52436, N'Refused: dbo.patient_conditions must hold exactly 0 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.patient_medications) <> 0
    THROW 52437, N'Refused: dbo.patient_medications must hold exactly 0 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.patient_number_sequences) <> 0
    THROW 52438, N'Refused: dbo.patient_number_sequences must hold exactly 0 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.patient_provider_profiles) <> 1
    THROW 52439, N'Refused: dbo.patient_provider_profiles must hold exactly 1 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.patients) <> 1
    THROW 52440, N'Refused: dbo.patients must hold exactly 1 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.provider_memberships) <> 1
    THROW 52441, N'Refused: dbo.provider_memberships must hold exactly 1 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.providers) <> 1
    THROW 52442, N'Refused: dbo.providers must hold exactly 1 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.radiology_reports) <> 0
    THROW 52443, N'Refused: dbo.radiology_reports must hold exactly 0 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.reminders) <> 0
    THROW 52444, N'Refused: dbo.reminders must hold exactly 0 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.service_specialties) <> 0
    THROW 52445, N'Refused: dbo.service_specialties must hold exactly 0 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.services) <> 1
    THROW 52446, N'Refused: dbo.services must hold exactly 1 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.specialties) <> 1
    THROW 52447, N'Refused: dbo.specialties must hold exactly 1 row(s).', 1;
IF (SELECT COUNT_BIG(*) FROM dbo.user_accounts) <> 1
    THROW 52448, N'Refused: dbo.user_accounts must hold exactly 1 row(s).', 1;
IF EXISTS (SELECT 1 FROM dbo.doctors WHERE provider_id <> '5e000001-0000-4000-8000-000000000001' OR license_number IS NULL OR license_number NOT LIKE N'ZZTEST-CC-%')
    THROW 52449, N'Refused: dbo.doctors holds a row the synthetic tests could not have created.', 1;
IF EXISTS (SELECT 1 FROM dbo.doctor_branches WHERE provider_id <> '5e000001-0000-4000-8000-000000000001')
    THROW 52450, N'Refused: dbo.doctor_branches holds a row the synthetic tests could not have created.', 1;
IF EXISTS (SELECT 1 FROM dbo.doctor_services WHERE provider_id <> '5e000001-0000-4000-8000-000000000001')
    THROW 52451, N'Refused: dbo.doctor_services holds a row the synthetic tests could not have created.', 1;
IF EXISTS (SELECT 1 FROM dbo.doctor_availability_slots WHERE provider_id <> '5e000001-0000-4000-8000-000000000001')
    THROW 52452, N'Refused: dbo.doctor_availability_slots holds a row the synthetic tests could not have created.', 1;
IF EXISTS (SELECT 1 FROM dbo.appointments WHERE provider_id <> '5e000001-0000-4000-8000-000000000001' OR patient_id <> '5e000006-0000-4000-8000-000000000001')
    THROW 52453, N'Refused: dbo.appointments holds a row the synthetic tests could not have created.', 1;
IF EXISTS (SELECT 1 FROM dbo.appointment_status_history WHERE provider_id <> '5e000001-0000-4000-8000-000000000001')
    THROW 52454, N'Refused: dbo.appointment_status_history holds a row the synthetic tests could not have created.', 1;
IF EXISTS (SELECT 1 FROM dbo.doctor_verification_decisions WHERE provider_id <> '5e000001-0000-4000-8000-000000000001' OR reviewer_user_id <> '5e000002-0000-4000-8000-000000000001')
    THROW 52455, N'Refused: dbo.doctor_verification_decisions holds a row the synthetic tests could not have created.', 1;
IF EXISTS (SELECT 1 FROM dbo.staff_audit_logs WHERE provider_id <> '5e000001-0000-4000-8000-000000000001' OR user_id <> '5e000002-0000-4000-8000-000000000001')
    THROW 52456, N'Refused: dbo.staff_audit_logs holds a row the synthetic tests could not have created.', 1;

SELECT DB_NAME() AS synthetic_database, 'SYNTHETIC VERIFIED' AS result,
       (SELECT fixture_version FROM dbo.zz_synthetic_marker) AS fixture_version;
