/* =====================================================================
   S3 - SEED of a synthetic concurrency database. GENERATED, do not edit:
   Backend/tools/generate_synthetic_sql.py (then re-pin in the runner).
   WRITE-CAPABLE: inserts the fake fixture rows and the synthetic marker.
   Run ONLY through Invoke-SyntheticGate.ps1 -Gate S3 -SynthName ...
   -TokenSha256 ... -Approved.

   Every value is fake (tests/synthetic_fixture.py): nothing is copied from
   any database; the staff password hash is a sentinel that never verifies.
   Refuses unless: the S2 checks pass; the schema fingerprint equals the
   generated one; the revision is c3d9e6a2f8b1; no marker exists; every table is
   still empty. Rows and marker are written in one transaction.
   Fixture synthetic-v1, manifest SHA-256 32e97a4d2c4e1971fe1b24c42867113b9c87147cfc9d584ed5e132e61a09d9fa
   ===================================================================== */
SET NOCOUNT ON;
SET XACT_ABORT ON;

IF @@SERVERNAME <> N'LAPTOP-FACHLL1N\SQLEXPRESS'
    THROW 52300, N'Refused: unexpected server.', 1;
IF @synthetic_name IS NULL
   OR DATALENGTH(@synthetic_name) <> 66
   OR @synthetic_name COLLATE Latin1_General_BIN NOT LIKE
      N'MedMind[_]SynthConc[_][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][_][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'
    THROW 52301, N'Refused: the name is not MedMind_SynthConc_<YYYYMMDD>_<6 lowercase hex>.', 1;
IF LOWER(@synthetic_name) IN (N'medmind_booking_db', N'medmind_audit_final2', N'medmind_audit_final')
   OR LOWER(@synthetic_name) LIKE N'medmind[_]audit%' OR LOWER(@synthetic_name) LIKE N'medmind[_]booking%'
   OR LOWER(@synthetic_name) LIKE N'medmind[_]concscratch%'
    THROW 52302, N'Refused: protected or restored-copy database name.', 1;
IF DB_NAME() COLLATE Latin1_General_BIN <> @synthetic_name COLLATE Latin1_General_BIN
    THROW 52303, N'Refused: not connected to the named synthetic database.', 1;
IF NOT EXISTS (SELECT 1 FROM sys.databases
               WHERE name = DB_NAME() AND state_desc = N'ONLINE' AND is_read_only = 0
                 AND source_database_id IS NULL AND is_read_committed_snapshot_on = 0
                 AND snapshot_isolation_state = 0)
    THROW 52304, N'Refused: database must be ONLINE, writable, not a snapshot, with RCSI and snapshot isolation OFF.', 1;
IF EXISTS (SELECT 1 FROM msdb.dbo.restorehistory WHERE destination_database_name = DB_NAME())
    THROW 52305, N'Refused: this database name was the target of a RESTORE; a synthetic database is never restored.', 1;
IF @token_sha256 IS NULL
   OR DATALENGTH(@token_sha256) <> 128
   OR @token_sha256 COLLATE Latin1_General_BIN LIKE N'%[^0-9a-f]%'
    THROW 52306, N'Refused: the token hash must be 64 lowercase hex characters.', 1;
IF ISNULL((SELECT HASHBYTES('SHA2_256', STRING_AGG(CAST(t.name + N'.' + c.name AS nvarchar(max)), NCHAR(10))
                  WITHIN GROUP (ORDER BY t.name + N'.' + c.name COLLATE Latin1_General_BIN2))
           FROM sys.tables AS t JOIN sys.columns AS c ON c.object_id = t.object_id
           WHERE t.schema_id = SCHEMA_ID(N'dbo') AND t.is_ms_shipped = 0 AND t.name <> N'zz_synthetic_marker'), 0x00)
   <> 0x98FC3E012B8644CBEE3E674102E76708132A58A83CB482B09EAB24FD0A55AFE6
    THROW 52307, N'Refused: the schema is not exactly the generated synthetic schema.', 1;
IF OBJECT_ID(N'dbo.alembic_version', N'U') IS NULL
   OR (SELECT COUNT(*) FROM dbo.alembic_version) <> 1
   OR NOT EXISTS (SELECT 1 FROM dbo.alembic_version WHERE version_num = 'c3d9e6a2f8b1')
    THROW 52308, N'Refused: unexpected alembic revision.', 1;
IF OBJECT_ID(N'dbo.zz_synthetic_marker', N'U') IS NOT NULL
    THROW 52309, N'Refused: the synthetic marker already exists.', 1;
IF EXISTS (SELECT 1 FROM dbo.appointment_status_history)
   OR EXISTS (SELECT 1 FROM dbo.appointments)
   OR EXISTS (SELECT 1 FROM dbo.branch_mrn_sequences)
   OR EXISTS (SELECT 1 FROM dbo.branches)
   OR EXISTS (SELECT 1 FROM dbo.clinical_notes)
   OR EXISTS (SELECT 1 FROM dbo.department_specialties)
   OR EXISTS (SELECT 1 FROM dbo.departments)
   OR EXISTS (SELECT 1 FROM dbo.diagnostic_assessments)
   OR EXISTS (SELECT 1 FROM dbo.diagnostic_attachments)
   OR EXISTS (SELECT 1 FROM dbo.doctor_availability_slots)
   OR EXISTS (SELECT 1 FROM dbo.doctor_branches)
   OR EXISTS (SELECT 1 FROM dbo.doctor_schedule_exceptions)
   OR EXISTS (SELECT 1 FROM dbo.doctor_services)
   OR EXISTS (SELECT 1 FROM dbo.doctor_verification_decisions)
   OR EXISTS (SELECT 1 FROM dbo.doctor_working_hours)
   OR EXISTS (SELECT 1 FROM dbo.doctors)
   OR EXISTS (SELECT 1 FROM dbo.ehr_encounters)
   OR EXISTS (SELECT 1 FROM dbo.idempotency_requests)
   OR EXISTS (SELECT 1 FROM dbo.lab_reports)
   OR EXISTS (SELECT 1 FROM dbo.lab_results)
   OR EXISTS (SELECT 1 FROM dbo.patient_access_grants)
   OR EXISTS (SELECT 1 FROM dbo.patient_allergies)
   OR EXISTS (SELECT 1 FROM dbo.patient_branch_profiles)
   OR EXISTS (SELECT 1 FROM dbo.patient_conditions)
   OR EXISTS (SELECT 1 FROM dbo.patient_medications)
   OR EXISTS (SELECT 1 FROM dbo.patient_number_sequences)
   OR EXISTS (SELECT 1 FROM dbo.patient_provider_profiles)
   OR EXISTS (SELECT 1 FROM dbo.patients)
   OR EXISTS (SELECT 1 FROM dbo.provider_memberships)
   OR EXISTS (SELECT 1 FROM dbo.providers)
   OR EXISTS (SELECT 1 FROM dbo.radiology_reports)
   OR EXISTS (SELECT 1 FROM dbo.reminders)
   OR EXISTS (SELECT 1 FROM dbo.service_specialties)
   OR EXISTS (SELECT 1 FROM dbo.services)
   OR EXISTS (SELECT 1 FROM dbo.specialties)
   OR EXISTS (SELECT 1 FROM dbo.staff_audit_logs)
   OR EXISTS (SELECT 1 FROM dbo.user_accounts)
    THROW 52310, N'Refused: a table already holds rows; seeding needs the empty S2 schema.', 1;

BEGIN TRANSACTION;

INSERT INTO dbo.providers (id, tenant_key, name, slug, org_type, verification_status, default_language, timezone, currency_code, is_active)
VALUES ('5e000001-0000-4000-8000-000000000001', 'synthetic-clinic-01', N'Synthetic Clinic 01', 'synthetic-clinic-01', 'clinic', 'verified', 'en', 'Africa/Cairo', 'EGP', 1);
INSERT INTO dbo.user_accounts (id, email, password_hash, is_active)
VALUES ('5e000002-0000-4000-8000-000000000001', 'synthetic.admin@example.invalid', '!synthetic-account-no-login', 1);
INSERT INTO dbo.branches (id, provider_id, code, name_ar, name_en, timezone, is_active, mrn_code)
VALUES ('5e000003-0000-4000-8000-000000000001', '5e000001-0000-4000-8000-000000000001', 'SYN-B1', N'Synthetic Branch 1', N'Synthetic Branch 1', 'Africa/Cairo', 1, 'SYN');
INSERT INTO dbo.specialties (id, provider_id, code, name_ar, name_en, is_active)
VALUES ('5e000004-0000-4000-8000-000000000001', '5e000001-0000-4000-8000-000000000001', 'SYN-GEN', N'Synthetic Specialty', N'Synthetic Specialty', 1);
INSERT INTO dbo.services (id, provider_id, code, name_ar, name_en, duration_minutes, service_type, requires_preparation, is_active)
VALUES ('5e000005-0000-4000-8000-000000000001', '5e000001-0000-4000-8000-000000000001', 'SYN-CONSULT', N'Synthetic Consultation', N'Synthetic Consultation', 15, 'consultation', 0, 1);
INSERT INTO dbo.patients (id, phone, preferred_language, is_active, patient_code, national_id_hash, national_id_encrypted, national_id_last4, full_name_ar, full_name_en)
VALUES ('5e000006-0000-4000-8000-000000000001', '+200000000001', 'en', 1, '9000001', '6b546875fa3eb7b0880d8a49a8966b63d205213f0ac54fa19136c37bf82d1b06', 0x53594E544845544943, '0000', N'Synthetic Patient 0001', N'Synthetic Patient 0001');
INSERT INTO dbo.patient_provider_profiles (id, patient_id, provider_id, medical_record_number, preferred_channel, consent_status, is_active)
VALUES ('5e000007-0000-4000-8000-000000000001', '5e000006-0000-4000-8000-000000000001', '5e000001-0000-4000-8000-000000000001', 'SYN-MRN-0001', 'web', 'pending', 1);
INSERT INTO dbo.patient_branch_profiles (id, provider_id, branch_id, patient_id, medical_record_number, is_active)
VALUES ('5e000008-0000-4000-8000-000000000001', '5e000001-0000-4000-8000-000000000001', '5e000003-0000-4000-8000-000000000001', '5e000006-0000-4000-8000-000000000001', 'SYN-000001', 1);
INSERT INTO dbo.provider_memberships (id, user_id, provider_id, role, is_active)
VALUES ('5e000009-0000-4000-8000-000000000001', '5e000002-0000-4000-8000-000000000001', '5e000001-0000-4000-8000-000000000001', 'provider_admin', 1);

CREATE TABLE dbo.zz_synthetic_marker (
	database_name sysname NOT NULL,
	marker_kind VARCHAR(20) NOT NULL,
	fixture_version VARCHAR(40) NOT NULL,
	token_sha256 CHAR(64) NOT NULL,
	manifest_sha256 CHAR(64) NOT NULL,
	created_at DATETIMEOFFSET NOT NULL CONSTRAINT DF_zz_synthetic_marker_created DEFAULT SYSDATETIMEOFFSET()
);
INSERT INTO dbo.zz_synthetic_marker (database_name, marker_kind, fixture_version, token_sha256, manifest_sha256)
VALUES (DB_NAME(), 'synthetic', 'synthetic-v1', @token_sha256, '32e97a4d2c4e1971fe1b24c42867113b9c87147cfc9d584ed5e132e61a09d9fa');

COMMIT TRANSACTION;

SELECT database_name, marker_kind, fixture_version, manifest_sha256 FROM dbo.zz_synthetic_marker;
