/* =====================================================================
   S2 - SCHEMA of a synthetic concurrency database. GENERATED, do not edit:
   Backend/tools/generate_synthetic_sql.py (then re-pin in the runner).
   WRITE-CAPABLE: creates tables in the (empty) synthetic database only.
   Run ONLY through Invoke-SyntheticGate.ps1 -Gate S2 -SynthName ... -Approved.

   Compiled from the SQLAlchemy models (37 tables + alembic_version),
   SQL Server dialect, schema dbo. NOT claimed to match MedMind_Audit_Final2:
   database-only objects (triggers, named defaults, computed columns, views,
   procedures, extra indexes, different column types) are absent.
   Refuses unless: expected server; connected to exactly the named
   MedMind_SynthConc_* database; ONLINE, writable, not a snapshot, RCSI and
   snapshot isolation OFF; never a RESTORE target; NO user object exists yet.
   All DDL runs in one transaction: either the whole schema or nothing.
   Schema fingerprint (SHA-256, see generator): 98fc3e012b8644cbee3e674102e76708132a58a83cb482b09eab24fd0a55afe6
   ===================================================================== */
SET NOCOUNT ON;
SET XACT_ABORT ON;

IF @@SERVERNAME <> N'LAPTOP-FACHLL1N\SQLEXPRESS'
    THROW 52200, N'Refused: unexpected server.', 1;
IF @synthetic_name IS NULL
   OR DATALENGTH(@synthetic_name) <> 66
   OR @synthetic_name COLLATE Latin1_General_BIN NOT LIKE
      N'MedMind[_]SynthConc[_][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][_][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'
    THROW 52201, N'Refused: the name is not MedMind_SynthConc_<YYYYMMDD>_<6 lowercase hex>.', 1;
IF LOWER(@synthetic_name) IN (N'medmind_booking_db', N'medmind_audit_final2', N'medmind_audit_final')
   OR LOWER(@synthetic_name) LIKE N'medmind[_]audit%' OR LOWER(@synthetic_name) LIKE N'medmind[_]booking%'
   OR LOWER(@synthetic_name) LIKE N'medmind[_]concscratch%'
    THROW 52202, N'Refused: protected or restored-copy database name.', 1;
IF DB_NAME() COLLATE Latin1_General_BIN <> @synthetic_name COLLATE Latin1_General_BIN
    THROW 52203, N'Refused: not connected to the named synthetic database.', 1;
IF NOT EXISTS (SELECT 1 FROM sys.databases
               WHERE name = DB_NAME() AND state_desc = N'ONLINE' AND is_read_only = 0
                 AND source_database_id IS NULL AND is_read_committed_snapshot_on = 0
                 AND snapshot_isolation_state = 0)
    THROW 52204, N'Refused: database must be ONLINE, writable, not a snapshot, with RCSI and snapshot isolation OFF.', 1;
IF EXISTS (SELECT 1 FROM msdb.dbo.restorehistory WHERE destination_database_name = DB_NAME())
    THROW 52205, N'Refused: this database name was the target of a RESTORE; a synthetic database is never restored.', 1;
IF EXISTS (SELECT 1 FROM sys.objects WHERE is_ms_shipped = 0)
    THROW 52206, N'Refused: the database is not empty.', 1;

BEGIN TRANSACTION;

CREATE TABLE dbo.appointment_status_history (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	appointment_id UNIQUEIDENTIFIER NOT NULL,
	event_type VARCHAR(20) NOT NULL,
	previous_status VARCHAR(20) NULL,
	new_status VARCHAR(20) NOT NULL,
	old_slot_id UNIQUEIDENTIFIER NULL,
	new_slot_id UNIQUEIDENTIFIER NULL,
	changed_by VARCHAR(20) NOT NULL,
	actor_reference VARCHAR(100) NULL,
	reason NVARCHAR(500) NULL,
	changed_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [CK_appointment_history_changed_by] CHECK (changed_by='ai_agent' OR changed_by='staff' OR changed_by='patient' OR changed_by='system'),
	CONSTRAINT [CK_appointment_history_event_type] CHECK (event_type='no_show' OR event_type='completed' OR event_type='rescheduled' OR event_type='cancelled' OR event_type='confirmed' OR event_type='created'),
	CONSTRAINT [CK_appointment_history_new_status] CHECK (new_status='no_show' OR new_status='completed' OR new_status='cancelled' OR new_status='confirmed' OR new_status='pending'),
	CONSTRAINT [CK_appointment_history_previous_required] CHECK (event_type='created' AND previous_status IS NULL OR event_type<>'created' AND previous_status IS NOT NULL),
	CONSTRAINT [CK_appointment_history_previous_status] CHECK (previous_status IS NULL OR (previous_status='no_show' OR previous_status='completed' OR previous_status='cancelled' OR previous_status='confirmed' OR previous_status='pending'))
);

CREATE TABLE dbo.appointments (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	appointment_reference VARCHAR(40) NOT NULL,
	patient_id UNIQUEIDENTIFIER NOT NULL,
	patient_name NVARCHAR(200) NOT NULL,
	phone VARCHAR(30) NOT NULL,
	slot_id UNIQUEIDENTIFIER NOT NULL,
	doctor_id UNIQUEIDENTIFIER NULL,
	branch_id UNIQUEIDENTIFIER NOT NULL,
	service_id UNIQUEIDENTIFIER NULL,
	scheduled_date DATE NOT NULL,
	start_time TIME NOT NULL,
	end_time TIME NOT NULL,
	channel VARCHAR(20) NOT NULL DEFAULT 'web',
	status VARCHAR(20) NOT NULL DEFAULT 'pending',
	notes NVARCHAR(max) NULL,
	cancellation_reason NVARCHAR(500) NULL,
	confirmed_at DATETIMEOFFSET NULL,
	cancelled_at DATETIMEOFFSET NULL,
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	created_by_type VARCHAR(20) NOT NULL DEFAULT 'system',
	created_by_reference VARCHAR(150) NULL,
	reschedule_count INTEGER NOT NULL DEFAULT 0,
	PRIMARY KEY (id),
	CONSTRAINT [UQ_appointments_id_provider] UNIQUE (id, provider_id),
	CONSTRAINT [UQ_appointments_provider_reference] UNIQUE (provider_id, appointment_reference),
	CONSTRAINT [CK_appointments_cancellation] CHECK (status='cancelled' AND cancelled_at IS NOT NULL OR status<>'cancelled' AND cancelled_at IS NULL AND cancellation_reason IS NULL),
	CONSTRAINT [CK_appointments_channel] CHECK (channel='ai_agent' OR channel='staff' OR channel='mobile' OR channel='web' OR channel='whatsapp' OR channel='voice'),
	CONSTRAINT [CK_appointments_confirmation] CHECK ((status='no_show' OR status='completed' OR status='confirmed') AND confirmed_at IS NOT NULL OR status='pending' AND confirmed_at IS NULL OR status='cancelled'),
	CONSTRAINT [CK_appointments_created_by_type] CHECK (created_by_type='system' OR created_by_type='ai_agent' OR created_by_type='staff' OR created_by_type='patient'),
	CONSTRAINT [CK_appointments_reschedule_count] CHECK (reschedule_count>=(0)),
	CONSTRAINT [CK_appointments_status] CHECK (status='no_show' OR status='completed' OR status='cancelled' OR status='confirmed' OR status='pending'),
	CONSTRAINT [CK_appointments_time_range] CHECK (end_time>start_time)
);

CREATE TABLE dbo.branch_mrn_sequences (
	provider_id UNIQUEIDENTIFIER NOT NULL,
	branch_id UNIQUEIDENTIFIER NOT NULL,
	sequence_year SMALLINT NOT NULL,
	last_number INTEGER NOT NULL DEFAULT 0,
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (provider_id, branch_id, sequence_year),
	CONSTRAINT [CK_branch_mrn_sequences_number] CHECK (last_number>=(0) AND last_number<=(999))
);

CREATE TABLE dbo.branches (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	code VARCHAR(50) NOT NULL,
	name_ar NVARCHAR(200) NOT NULL,
	name_en NVARCHAR(200) NOT NULL,
	address_ar NVARCHAR(500) NULL,
	address_en NVARCHAR(500) NULL,
	governorate NVARCHAR(100) NULL,
	latitude NUMERIC(9, 6) NULL,
	longitude NUMERIC(9, 6) NULL,
	phone VARCHAR(30) NULL,
	whatsapp VARCHAR(30) NULL,
	timezone VARCHAR(64) NOT NULL DEFAULT 'Africa/Cairo',
	is_active BIT NOT NULL DEFAULT 1,
	created_at DATETIME NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIME NOT NULL DEFAULT sysutcdatetime(),
	mrn_code CHAR(3) NULL,
	PRIMARY KEY (id),
	CONSTRAINT [UQ_branches_id_provider] UNIQUE (id, provider_id),
	CONSTRAINT [UQ_branches_provider_code] UNIQUE (provider_id, code),
	CONSTRAINT [CK_branches_latitude] CHECK (latitude>=(-90) AND latitude<=(90) OR latitude IS NULL),
	CONSTRAINT [CK_branches_longitude] CHECK (longitude>=(-180) AND longitude<=(180) OR longitude IS NULL)
);

CREATE TABLE dbo.clinical_notes (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	patient_id UNIQUEIDENTIFIER NOT NULL,
	encounter_id UNIQUEIDENTIFIER NOT NULL,
	doctor_id UNIQUEIDENTIFIER NOT NULL,
	note_type VARCHAR(20) NOT NULL DEFAULT 'progress',
	title NVARCHAR(200) NULL,
	note_text NVARCHAR(max) NOT NULL,
	status VARCHAR(20) NOT NULL DEFAULT 'draft',
	signed_at DATETIMEOFFSET NULL,
	addendum_to_note_id UNIQUEIDENTIFIER NULL,
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [CK_clinical_notes_addendum] CHECK (note_type <> 'addendum' OR addendum_to_note_id IS NOT NULL),
	CONSTRAINT [CK_clinical_notes_signed] CHECK ((status = 'signed' AND signed_at IS NOT NULL) OR (status = 'draft' AND signed_at IS NULL)),
	CONSTRAINT [CK_clinical_notes_status] CHECK (status IN ('draft','signed')),
	CONSTRAINT [CK_clinical_notes_type] CHECK (note_type IN ('progress','consultation','soap','discharge','addendum'))
);

CREATE TABLE dbo.department_specialties (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	department_id UNIQUEIDENTIFIER NOT NULL,
	specialty_id UNIQUEIDENTIFIER NOT NULL,
	created_at DATETIME NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [UQ_department_specialties_department_specialty] UNIQUE (department_id, specialty_id)
);

CREATE TABLE dbo.departments (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	branch_id UNIQUEIDENTIFIER NULL,
	code VARCHAR(100) NOT NULL,
	name_ar NVARCHAR(150) NOT NULL,
	name_en NVARCHAR(150) NOT NULL,
	description_ar NVARCHAR(1000) NULL,
	description_en NVARCHAR(1000) NULL,
	phone VARCHAR(30) NULL,
	is_active BIT NOT NULL DEFAULT 1,
	created_at DATETIME NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIME NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [UQ_departments_id_provider] UNIQUE (id, provider_id),
	CONSTRAINT [UQ_departments_provider_code] UNIQUE (provider_id, code)
);

CREATE TABLE dbo.diagnostic_assessments (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	radiology_report_id UNIQUEIDENTIFIER NOT NULL,
	assessment_type VARCHAR(30) NOT NULL DEFAULT 'radiology_model',
	classification VARCHAR(100) NOT NULL,
	probabilities_json NVARCHAR(max) NOT NULL,
	confidence NUMERIC(9, 8) NOT NULL,
	inference_latency_ms NUMERIC(12, 3) NOT NULL,
	model_name NVARCHAR(150) NOT NULL,
	model_version NVARCHAR(100) NOT NULL,
	limitations_json NVARCHAR(max) NOT NULL,
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [CK_diagnostic_assessments_confidence] CHECK (confidence>=(0) AND confidence<=(1)),
	CONSTRAINT [CK_diagnostic_assessments_latency] CHECK (inference_latency_ms>=(0))
);

CREATE TABLE dbo.diagnostic_attachments (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	attachment_id VARCHAR(32) NOT NULL,
	provider_id UNIQUEIDENTIFIER NOT NULL,
	patient_id UNIQUEIDENTIFIER NULL,
	encounter_id UNIQUEIDENTIFIER NULL,
	session_id VARCHAR(128) NOT NULL,
	original_filename NVARCHAR(255) NOT NULL,
	content_type VARCHAR(100) NOT NULL,
	size_bytes BIGINT NOT NULL,
	sha256 VARCHAR(64) NOT NULL,
	storage_key NVARCHAR(500) NOT NULL,
	status VARCHAR(20) NOT NULL DEFAULT 'stored',
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [UQ_diagnostic_attachments_attachment_id] UNIQUE (attachment_id)
);

CREATE TABLE dbo.doctor_availability_slots (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	doctor_id UNIQUEIDENTIFIER NULL,
	branch_id UNIQUEIDENTIFIER NOT NULL,
	working_hours_id UNIQUEIDENTIFIER NULL,
	slot_date DATE NOT NULL,
	start_time TIME NOT NULL,
	end_time TIME NOT NULL,
	status VARCHAR(20) NOT NULL DEFAULT 'available',
	hold_expires_at DATETIMEOFFSET NULL,
	hold_reference VARCHAR(100) NULL,
	is_waitlist_fill BIT NOT NULL DEFAULT 0,
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [CK_availability_slots_hold] CHECK (status='held' AND hold_expires_at IS NOT NULL OR status<>'held' AND hold_expires_at IS NULL),
	CONSTRAINT [CK_availability_slots_status] CHECK (status='blocked' OR status='booked' OR status='held' OR status='available'),
	CONSTRAINT [CK_availability_slots_time_range] CHECK (end_time>start_time)
);

CREATE TABLE dbo.doctor_branches (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	doctor_id UNIQUEIDENTIFIER NOT NULL,
	branch_id UNIQUEIDENTIFIER NOT NULL,
	is_primary BIT NOT NULL DEFAULT 0,
	is_active BIT NOT NULL DEFAULT 1,
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [UQ_doctor_branches_doctor_branch] UNIQUE (doctor_id, branch_id)
);

CREATE TABLE dbo.doctor_schedule_exceptions (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	doctor_id UNIQUEIDENTIFIER NOT NULL,
	branch_id UNIQUEIDENTIFIER NOT NULL,
	exception_date DATE NOT NULL,
	exception_type VARCHAR(20) NOT NULL,
	start_time TIME NULL,
	end_time TIME NULL,
	reason NVARCHAR(300) NULL,
	is_active BIT NOT NULL DEFAULT 1,
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [UQ_schedule_exceptions_doctor_branch_date] UNIQUE (doctor_id, branch_id, exception_date),
	CONSTRAINT [CK_schedule_exceptions_time_values] CHECK (exception_type='unavailable' AND start_time IS NULL AND end_time IS NULL OR exception_type='custom_hours' AND start_time IS NOT NULL AND end_time IS NOT NULL AND end_time>start_time),
	CONSTRAINT [CK_schedule_exceptions_type] CHECK (exception_type='custom_hours' OR exception_type='unavailable')
);

CREATE TABLE dbo.doctor_services (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	doctor_id UNIQUEIDENTIFIER NOT NULL,
	service_id UNIQUEIDENTIFIER NOT NULL,
	fee_override NUMERIC(10, 2) NULL,
	duration_override_minutes INTEGER NULL,
	is_active BIT NOT NULL DEFAULT 1,
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [UQ_doctor_services_doctor_service] UNIQUE (doctor_id, service_id),
	CONSTRAINT [CK_doctor_services_duration_override] CHECK (duration_override_minutes IS NULL OR duration_override_minutes>(0)),
	CONSTRAINT [CK_doctor_services_fee_override] CHECK (fee_override IS NULL OR fee_override>=(0))
);

CREATE TABLE dbo.doctor_verification_decisions (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	doctor_id UNIQUEIDENTIFIER NOT NULL,
	decision VARCHAR(20) NOT NULL,
	previous_status VARCHAR(20) NOT NULL,
	reason NVARCHAR(500) NULL,
	reviewer_user_id UNIQUEIDENTIFIER NOT NULL,
	reviewer_membership_id UNIQUEIDENTIFIER NOT NULL,
	decided_at DATETIMEOFFSET NOT NULL DEFAULT TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00'),
	PRIMARY KEY (id),
	CONSTRAINT [CK_doctor_verification_decisions_decision] CHECK (decision='verified' OR decision='rejected' OR decision='resubmitted'),
	CONSTRAINT [CK_doctor_verification_decisions_previous_status] CHECK (previous_status='pending' OR previous_status='verified' OR previous_status='rejected'),
	CONSTRAINT [CK_doctor_verification_decisions_reason] CHECK (decision='rejected' AND reason IS NOT NULL AND LEN(LTRIM(RTRIM(reason)))>(0) OR decision<>'rejected' AND reason IS NULL)
);

CREATE TABLE dbo.doctor_working_hours (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	doctor_id UNIQUEIDENTIFIER NULL,
	branch_id UNIQUEIDENTIFIER NOT NULL,
	day_of_week INTEGER NOT NULL,
	start_time TIME NOT NULL,
	end_time TIME NOT NULL,
	slot_duration_minutes INTEGER NOT NULL DEFAULT 30,
	is_active BIT NOT NULL DEFAULT 1,
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [CK_working_hours_day_of_week] CHECK (day_of_week>=(0) AND day_of_week<=(6)),
	CONSTRAINT [CK_working_hours_slot_duration] CHECK (slot_duration_minutes>=(5) AND slot_duration_minutes<=(240)),
	CONSTRAINT [CK_working_hours_time_range] CHECK (end_time>start_time)
);

CREATE TABLE dbo.doctors (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	specialty_id UNIQUEIDENTIFIER NOT NULL,
	full_name_ar NVARCHAR(200) NOT NULL,
	full_name_en NVARCHAR(200) NOT NULL,
	license_number VARCHAR(100) NULL,
	bio_ar NVARCHAR(max) NULL,
	bio_en NVARCHAR(max) NULL,
	consultation_fee NUMERIC(10, 2) NULL,
	teleconsultation_fee NUMERIC(10, 2) NULL,
	experience_years INTEGER NULL,
	gender VARCHAR(10) NULL,
	photo_url VARCHAR(500) NULL,
	rating_avg NUMERIC(3, 2) NULL,
	review_count INTEGER NOT NULL DEFAULT 0,
	accepting_new_patients BIT NOT NULL DEFAULT 1,
	verification_status VARCHAR(20) NOT NULL DEFAULT 'pending',
	is_active BIT NOT NULL DEFAULT 1,
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [UQ_doctors_id_provider] UNIQUE (id, provider_id),
	CONSTRAINT [CK_doctors_consultation_fee] CHECK (consultation_fee IS NULL OR consultation_fee>=(0)),
	CONSTRAINT [CK_doctors_experience_years] CHECK (experience_years IS NULL OR experience_years>=(0)),
	CONSTRAINT [CK_doctors_gender] CHECK (gender IS NULL OR (gender='female' OR gender='male')),
	CONSTRAINT [CK_doctors_rating_avg] CHECK (rating_avg IS NULL OR rating_avg>=(0) AND rating_avg<=(5)),
	CONSTRAINT [CK_doctors_review_count] CHECK (review_count>=(0)),
	CONSTRAINT [CK_doctors_teleconsultation_fee] CHECK (teleconsultation_fee IS NULL OR teleconsultation_fee>=(0)),
	CONSTRAINT [CK_doctors_verification_status] CHECK (verification_status='rejected' OR verification_status='verified' OR verification_status='pending')
);

CREATE TABLE dbo.ehr_encounters (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	patient_id UNIQUEIDENTIFIER NOT NULL,
	provider_id UNIQUEIDENTIFIER NOT NULL,
	doctor_id UNIQUEIDENTIFIER NULL,
	branch_id UNIQUEIDENTIFIER NULL,
	appointment_id UNIQUEIDENTIFIER NULL,
	encounter_type VARCHAR(30) NOT NULL,
	status VARCHAR(20) NOT NULL,
	started_at DATETIMEOFFSET NOT NULL,
	ended_at DATETIMEOFFSET NULL,
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [UQ_ehr_encounters_id_provider_patient] UNIQUE (id, provider_id, patient_id)
);

CREATE TABLE dbo.idempotency_requests (
	id VARCHAR(36) NOT NULL,
	tenant_id VARCHAR(100) NOT NULL,
	operation VARCHAR(50) NOT NULL,
	idempotency_key VARCHAR(128) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	status VARCHAR(20) NOT NULL DEFAULT 'pending',
	response_body NVARCHAR(max) NULL,
	error_code VARCHAR(100) NULL,
	created_at DATETIMEOFFSET NOT NULL DEFAULT TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00'),
	completed_at DATETIMEOFFSET NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_idempotency_tenant_operation_key UNIQUE (tenant_id, operation, idempotency_key)
);

CREATE TABLE dbo.lab_reports (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	patient_id UNIQUEIDENTIFIER NULL,
	provider_id UNIQUEIDENTIFIER NOT NULL,
	encounter_id UNIQUEIDENTIFIER NULL,
	diagnostic_attachment_id UNIQUEIDENTIFIER NOT NULL,
	document_type VARCHAR(50) NULL,
	unreadable_fields_json NVARCHAR(max) NULL,
	status VARCHAR(20) NOT NULL DEFAULT 'pending',
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [UQ_lab_reports_diagnostic_attachment] UNIQUE (diagnostic_attachment_id)
);

CREATE TABLE dbo.lab_results (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	lab_report_id UNIQUEIDENTIFIER NOT NULL,
	result_index INTEGER NOT NULL,
	panel VARCHAR(30) NULL,
	raw_name NVARCHAR(200) NOT NULL,
	canonical_name VARCHAR(100) NULL,
	value NUMERIC(18, 6) NULL,
	unit NVARCHAR(50) NULL,
	reference_min NUMERIC(18, 6) NULL,
	reference_max NUMERIC(18, 6) NULL,
	reference_text NVARCHAR(200) NULL,
	flag VARCHAR(20) NOT NULL DEFAULT 'unknown',
	mapping_status VARCHAR(20) NOT NULL,
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [UQ_lab_results_report_index] UNIQUE (lab_report_id, result_index)
);

CREATE TABLE dbo.patient_access_grants (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	patient_id UNIQUEIDENTIFIER NOT NULL,
	owner_provider_id UNIQUEIDENTIFIER NOT NULL,
	grantee_provider_id UNIQUEIDENTIFIER NOT NULL,
	scope VARCHAR(20) NOT NULL DEFAULT 'full_record',
	granted_by VARCHAR(20) NOT NULL DEFAULT 'patient',
	granted_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	expires_at DATETIMEOFFSET NULL,
	revoked_at DATETIMEOFFSET NULL,
	revoked_reason NVARCHAR(300) NULL,
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [CK_patient_access_grants_by] CHECK (granted_by IN ('patient','staff')),
	CONSTRAINT [CK_patient_access_grants_distinct] CHECK (owner_provider_id <> grantee_provider_id),
	CONSTRAINT [CK_patient_access_grants_expiry] CHECK (expires_at IS NULL OR expires_at > granted_at),
	CONSTRAINT [CK_patient_access_grants_revoked] CHECK (revoked_at IS NULL OR revoked_at >= granted_at),
	CONSTRAINT [CK_patient_access_grants_scope] CHECK (scope IN ('full_record','history_only','reports_only'))
);

CREATE TABLE dbo.patient_allergies (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	patient_id UNIQUEIDENTIFIER NOT NULL,
	encounter_id UNIQUEIDENTIFIER NULL,
	recorded_by_doctor_id UNIQUEIDENTIFIER NULL,
	allergen NVARCHAR(200) NOT NULL,
	allergen_type VARCHAR(20) NOT NULL,
	reaction NVARCHAR(300) NULL,
	severity VARCHAR(20) NOT NULL DEFAULT 'mild',
	status VARCHAR(20) NOT NULL DEFAULT 'active',
	noted_date DATE NULL,
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [CK_patient_allergies_severity] CHECK (severity IN ('mild','moderate','severe','life_threatening')),
	CONSTRAINT [CK_patient_allergies_status] CHECK (status IN ('active','inactive','resolved')),
	CONSTRAINT [CK_patient_allergies_type] CHECK (allergen_type IN ('drug','food','environmental','other'))
);

CREATE TABLE dbo.patient_branch_profiles (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	branch_id UNIQUEIDENTIFIER NOT NULL,
	patient_id UNIQUEIDENTIFIER NOT NULL,
	medical_record_number VARCHAR(20) NOT NULL,
	is_active BIT NOT NULL DEFAULT 1,
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id)
);

CREATE TABLE dbo.patient_conditions (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	patient_id UNIQUEIDENTIFIER NOT NULL,
	encounter_id UNIQUEIDENTIFIER NULL,
	recorded_by_doctor_id UNIQUEIDENTIFIER NULL,
	condition_name NVARCHAR(200) NOT NULL,
	icd10_code VARCHAR(10) NULL,
	clinical_status VARCHAR(20) NOT NULL DEFAULT 'active',
	severity VARCHAR(20) NULL,
	onset_date DATE NULL,
	resolved_date DATE NULL,
	notes NVARCHAR(1000) NULL,
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [CK_patient_conditions_dates] CHECK (resolved_date IS NULL OR onset_date IS NULL OR resolved_date >= onset_date),
	CONSTRAINT [CK_patient_conditions_resolved] CHECK (clinical_status <> 'resolved' OR resolved_date IS NOT NULL),
	CONSTRAINT [CK_patient_conditions_severity] CHECK (severity IS NULL OR severity IN ('mild','moderate','severe')),
	CONSTRAINT [CK_patient_conditions_status] CHECK (clinical_status IN ('active','resolved','inactive'))
);

CREATE TABLE dbo.patient_medications (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	patient_id UNIQUEIDENTIFIER NOT NULL,
	encounter_id UNIQUEIDENTIFIER NULL,
	prescribed_by_doctor_id UNIQUEIDENTIFIER NULL,
	medication_name NVARCHAR(200) NOT NULL,
	dosage NVARCHAR(100) NULL,
	frequency NVARCHAR(100) NULL,
	route VARCHAR(30) NULL,
	start_date DATE NULL,
	end_date DATE NULL,
	status VARCHAR(20) NOT NULL DEFAULT 'active',
	notes NVARCHAR(500) NULL,
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [CK_patient_medications_dates] CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date),
	CONSTRAINT [CK_patient_medications_status] CHECK (status IN ('active','completed','stopped'))
);

CREATE TABLE dbo.patient_number_sequences (
	year INTEGER NOT NULL,
	last_number INTEGER NOT NULL,
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (year)
);

CREATE TABLE dbo.patient_provider_profiles (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	patient_id UNIQUEIDENTIFIER NOT NULL,
	provider_id UNIQUEIDENTIFIER NOT NULL,
	medical_record_number VARCHAR(100) NULL,
	preferred_channel VARCHAR(20) NOT NULL DEFAULT 'whatsapp',
	consent_status VARCHAR(20) NOT NULL DEFAULT 'pending',
	consent_timestamp DATETIMEOFFSET NULL,
	is_active BIT NOT NULL DEFAULT 1,
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [UQ_patient_provider_profiles_patient_provider] UNIQUE (patient_id, provider_id),
	CONSTRAINT [CK_patient_provider_profiles_consent_status] CHECK (consent_status='pending' OR consent_status='withdrawn' OR consent_status='granted'),
	CONSTRAINT [CK_patient_provider_profiles_consent_timestamp] CHECK (consent_status='pending' OR (consent_status='withdrawn' OR consent_status='granted') AND consent_timestamp IS NOT NULL),
	CONSTRAINT [CK_patient_provider_profiles_preferred_channel] CHECK (preferred_channel='mobile' OR preferred_channel='web' OR preferred_channel='whatsapp' OR preferred_channel='voice')
);

CREATE TABLE dbo.patients (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	date_of_birth DATE NULL,
	gender VARCHAR(10) NULL,
	phone VARCHAR(30) NOT NULL,
	email VARCHAR(254) NULL,
	preferred_language VARCHAR(10) NOT NULL DEFAULT 'ar',
	location NVARCHAR(150) NULL,
	digital_literacy_flag VARCHAR(20) NULL,
	is_active BIT NOT NULL DEFAULT 1,
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	patient_code VARCHAR(20) NOT NULL,
	national_id_hash VARCHAR(64) NOT NULL,
	national_id_encrypted VARBINARY(max) NOT NULL,
	national_id_last4 VARCHAR(4) NOT NULL,
	full_name_ar NVARCHAR(200) NOT NULL,
	full_name_en NVARCHAR(200) NULL,
	PRIMARY KEY (id),
	CONSTRAINT [UQ_patients_national_id_hash] UNIQUE (national_id_hash),
	CONSTRAINT [UQ_patients_patient_code] UNIQUE (patient_code),
	CONSTRAINT [CK_patients_digital_literacy] CHECK (digital_literacy_flag IS NULL OR (digital_literacy_flag='app_capable' OR digital_literacy_flag='phone_only')),
	CONSTRAINT [CK_patients_gender] CHECK (gender IS NULL OR (gender='female' OR gender='male')),
	CONSTRAINT [CK_patients_national_id_hash] CHECK (len(national_id_hash)=(64)),
	CONSTRAINT [CK_patients_national_id_last4] CHECK (len(national_id_last4)=(4) AND NOT national_id_last4 like '%[^0-9]%'),
	CONSTRAINT [CK_patients_patient_code] CHECK (len(patient_code)>=(7) AND NOT patient_code like '%[^0-9]%'),
	CONSTRAINT [CK_patients_preferred_language] CHECK (preferred_language='en' OR preferred_language='ar')
);

CREATE TABLE dbo.provider_memberships (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	user_id UNIQUEIDENTIFIER NOT NULL,
	provider_id UNIQUEIDENTIFIER NOT NULL,
	role VARCHAR(30) NOT NULL,
	doctor_id UNIQUEIDENTIFIER NULL,
	is_active BIT NOT NULL DEFAULT 1,
	created_at DATETIMEOFFSET NOT NULL DEFAULT TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00'),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00'),
	PRIMARY KEY (id),
	CONSTRAINT uq_provider_memberships_id_user_provider UNIQUE (id, user_id, provider_id),
	CONSTRAINT uq_provider_memberships_user_provider UNIQUE (user_id, provider_id),
	CONSTRAINT ck_provider_memberships_doctor_role CHECK (role='doctor' AND doctor_id IS NOT NULL OR role<>'doctor' AND doctor_id IS NULL),
	CONSTRAINT ck_provider_memberships_role CHECK (role='lab_staff' OR role='receptionist' OR role='doctor' OR role='provider_admin')
);

CREATE TABLE dbo.providers (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	tenant_key VARCHAR(100) NOT NULL,
	name NVARCHAR(200) NOT NULL,
	slug VARCHAR(150) NOT NULL,
	org_type VARCHAR(30) NOT NULL DEFAULT 'clinic',
	verification_status VARCHAR(20) NOT NULL DEFAULT 'pending',
	default_language VARCHAR(5) NOT NULL DEFAULT 'ar',
	timezone VARCHAR(64) NOT NULL DEFAULT 'Africa/Cairo',
	currency_code VARCHAR(3) NOT NULL DEFAULT 'EGP',
	phone VARCHAR(30) NULL,
	email VARCHAR(254) NULL,
	address NVARCHAR(500) NULL,
	is_active BIT NOT NULL DEFAULT 1,
	created_at DATETIME NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIME NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [UQ_providers_slug] UNIQUE (slug),
	CONSTRAINT [UQ_providers_tenant_key] UNIQUE (tenant_key),
	CONSTRAINT [CK_providers_default_language] CHECK (default_language='en' OR default_language='ar'),
	CONSTRAINT [CK_providers_org_type] CHECK (org_type='pharmacy' OR org_type='diagnostic_lab' OR org_type='hospital' OR org_type='clinic'),
	CONSTRAINT [CK_providers_verification_status] CHECK (verification_status='rejected' OR verification_status='pending' OR verification_status='verified')
);

CREATE TABLE dbo.radiology_reports (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	patient_id UNIQUEIDENTIFIER NULL,
	provider_id UNIQUEIDENTIFIER NOT NULL,
	encounter_id UNIQUEIDENTIFIER NULL,
	diagnostic_attachment_id UNIQUEIDENTIFIER NOT NULL,
	modality VARCHAR(30) NOT NULL,
	status VARCHAR(20) NOT NULL DEFAULT 'pending',
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [UQ_radiology_reports_diagnostic_attachment] UNIQUE (diagnostic_attachment_id)
);

CREATE TABLE dbo.reminders (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	appointment_id UNIQUEIDENTIFIER NOT NULL,
	patient_id UNIQUEIDENTIFIER NULL,
	recipient_phone VARCHAR(30) NOT NULL,
	recipient_name NVARCHAR(200) NULL,
	channel VARCHAR(30) NOT NULL,
	reminder_type VARCHAR(30) NOT NULL,
	template_key VARCHAR(100) NULL,
	content NVARCHAR(max) NULL,
	scheduled_for DATETIMEOFFSET NOT NULL,
	delivery_status VARCHAR(20) NOT NULL DEFAULT 'pending',
	attempt_count INTEGER NOT NULL DEFAULT 0,
	last_attempt_at DATETIMEOFFSET NULL,
	sent_at DATETIMEOFFSET NULL,
	delivered_at DATETIMEOFFSET NULL,
	provider_message_id VARCHAR(200) NULL,
	last_error NVARCHAR(max) NULL,
	patient_response VARCHAR(20) NULL,
	response_at DATETIMEOFFSET NULL,
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [UQ_reminders_appointment_type_channel] UNIQUE (appointment_id, reminder_type, channel),
	CONSTRAINT [CK_reminders_attempt_count] CHECK (attempt_count>=(0)),
	CONSTRAINT [CK_reminders_channel] CHECK (channel='push_notification' OR channel='voice_call' OR channel='whatsapp' OR channel='sms'),
	CONSTRAINT [CK_reminders_delivery_status] CHECK (delivery_status='cancelled' OR delivery_status='failed' OR delivery_status='delivered' OR delivery_status='sent' OR delivery_status='pending'),
	CONSTRAINT [CK_reminders_patient_response] CHECK (patient_response IS NULL OR (patient_response='no_response' OR patient_response='cancelled' OR patient_response='confirmed')),
	CONSTRAINT [CK_reminders_type] CHECK (reminder_type='pre_session_task' OR reminder_type='2h_reminder' OR reminder_type='24h_reminder' OR reminder_type='confirmation')
);

CREATE TABLE dbo.service_specialties (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	service_id UNIQUEIDENTIFIER NOT NULL,
	specialty_id UNIQUEIDENTIFIER NOT NULL,
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [UQ_service_specialties_service_specialty] UNIQUE (service_id, specialty_id)
);

CREATE TABLE dbo.services (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	code VARCHAR(50) NOT NULL,
	name_ar NVARCHAR(150) NOT NULL,
	name_en NVARCHAR(150) NOT NULL,
	description_ar NVARCHAR(max) NULL,
	description_en NVARCHAR(max) NULL,
	duration_minutes INTEGER NOT NULL,
	price NUMERIC(10, 2) NULL,
	service_type VARCHAR(30) NOT NULL DEFAULT 'consultation',
	requires_preparation BIT NOT NULL DEFAULT 0,
	preparation_instructions_ar NVARCHAR(max) NULL,
	preparation_instructions_en NVARCHAR(max) NULL,
	is_active BIT NOT NULL DEFAULT 1,
	created_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT sysutcdatetime(),
	voice_label_ar NVARCHAR(160) NULL,
	voice_label_en NVARCHAR(160) NULL,
	voice_featured_rank INTEGER NULL,
	PRIMARY KEY (id),
	CONSTRAINT [UQ_services_provider_code] UNIQUE (provider_id, code),
	CONSTRAINT [CK_services_duration_minutes] CHECK (duration_minutes>(0)),
	CONSTRAINT [CK_services_price] CHECK (price IS NULL OR price>=(0)),
	CONSTRAINT [CK_services_service_type] CHECK (service_type='surgery' OR service_type='procedure' OR service_type='diagnostic' OR service_type='follow_up' OR service_type='teleconsultation' OR service_type='consultation'),
	CONSTRAINT ck_services_voice_featured_rank_positive CHECK (voice_featured_rank IS NULL OR voice_featured_rank>(0))
);

CREATE TABLE dbo.specialties (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	code VARCHAR(100) NOT NULL,
	name_ar NVARCHAR(150) NOT NULL,
	name_en NVARCHAR(150) NOT NULL,
	description_ar NVARCHAR(1000) NULL,
	description_en NVARCHAR(1000) NULL,
	is_active BIT NOT NULL DEFAULT 1,
	created_at DATETIME NOT NULL DEFAULT sysutcdatetime(),
	updated_at DATETIME NOT NULL DEFAULT sysutcdatetime(),
	PRIMARY KEY (id),
	CONSTRAINT [UQ_specialties_id_provider] UNIQUE (id, provider_id),
	CONSTRAINT [UQ_specialties_provider_code] UNIQUE (provider_id, code)
);

CREATE TABLE dbo.staff_audit_logs (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	provider_id UNIQUEIDENTIFIER NOT NULL,
	user_id UNIQUEIDENTIFIER NOT NULL,
	membership_id UNIQUEIDENTIFIER NOT NULL,
	patient_id UNIQUEIDENTIFIER NULL,
	action VARCHAR(100) NOT NULL,
	resource_type VARCHAR(50) NOT NULL,
	resource_id VARCHAR(100) NULL,
	outcome VARCHAR(30) NOT NULL,
	created_at DATETIMEOFFSET NOT NULL DEFAULT TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00'),
	PRIMARY KEY (id),
	CONSTRAINT ck_staff_audit_logs_outcome CHECK (outcome='error' OR outcome='denied' OR outcome='not_found' OR outcome='success')
);

CREATE TABLE dbo.user_accounts (
	id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
	email VARCHAR(254) NOT NULL,
	password_hash VARCHAR(255) NOT NULL,
	is_active BIT NOT NULL DEFAULT 1,
	created_at DATETIMEOFFSET NOT NULL DEFAULT TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00'),
	updated_at DATETIMEOFFSET NOT NULL DEFAULT TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00'),
	PRIMARY KEY (id),
	CONSTRAINT uq_user_accounts_email UNIQUE (email)
);

CREATE INDEX [IX_appointment_history_appointment_date] ON dbo.appointment_status_history (appointment_id, changed_at);

CREATE INDEX [IX_appointment_history_provider_date] ON dbo.appointment_status_history (provider_id, changed_at);

CREATE INDEX [IX_appointments_doctor_date] ON dbo.appointments (doctor_id, scheduled_date);

CREATE INDEX [IX_appointments_patient] ON dbo.appointments (patient_id);

CREATE INDEX [IX_appointments_provider_date_status] ON dbo.appointments (provider_id, scheduled_date, status);

CREATE INDEX [IX_appointments_provider_reference] ON dbo.appointments (provider_id, appointment_reference);

CREATE UNIQUE INDEX [UX_appointments_active_slot] ON dbo.appointments (slot_id) WHERE status<>'cancelled';

CREATE INDEX [IX_branches_provider_active] ON dbo.branches (provider_id, is_active);

CREATE UNIQUE INDEX [UX_branches_provider_mrn_code] ON dbo.branches (provider_id, mrn_code) WHERE mrn_code IS NOT NULL;

CREATE INDEX [IX_clinical_notes_encounter] ON dbo.clinical_notes (encounter_id);

CREATE INDEX [IX_clinical_notes_patient] ON dbo.clinical_notes (provider_id, patient_id, created_at);

CREATE INDEX [IX_department_specialties_provider_specialty] ON dbo.department_specialties (provider_id, specialty_id);

CREATE INDEX [IX_departments_provider_active] ON dbo.departments (provider_id, is_active);

CREATE INDEX [IX_departments_provider_branch] ON dbo.departments (provider_id, branch_id);

CREATE INDEX [IX_diagnostic_assessments_model] ON dbo.diagnostic_assessments (model_name, model_version);

CREATE INDEX [IX_diagnostic_assessments_report_created] ON dbo.diagnostic_assessments (radiology_report_id, created_at);

CREATE INDEX [IX_diagnostic_attachments_patient_created] ON dbo.diagnostic_attachments (patient_id, created_at);

CREATE INDEX [IX_diagnostic_attachments_provider_session] ON dbo.diagnostic_attachments (provider_id, session_id);

CREATE INDEX [IX_availability_slots_branch_date] ON dbo.doctor_availability_slots (branch_id, slot_date, status);

CREATE INDEX [IX_availability_slots_doctor_date] ON dbo.doctor_availability_slots (doctor_id, slot_date, start_time);

CREATE INDEX [IX_availability_slots_provider_date_status] ON dbo.doctor_availability_slots (provider_id, slot_date, status);

CREATE UNIQUE INDEX [UX_availability_slots_branch_date_time] ON dbo.doctor_availability_slots (branch_id, slot_date, start_time) WHERE doctor_id IS NULL;

CREATE UNIQUE INDEX [UX_availability_slots_doctor_date_time] ON dbo.doctor_availability_slots (doctor_id, slot_date, start_time) WHERE doctor_id IS NOT NULL;

CREATE INDEX [IX_doctor_branches_doctor_active] ON dbo.doctor_branches (doctor_id, is_active);

CREATE INDEX [IX_doctor_branches_provider_active] ON dbo.doctor_branches (provider_id, is_active);

CREATE UNIQUE INDEX [UX_doctor_branches_primary] ON dbo.doctor_branches (doctor_id) WHERE is_primary=(1) AND is_active=(1);

CREATE INDEX [IX_schedule_exceptions_doctor_date] ON dbo.doctor_schedule_exceptions (doctor_id, exception_date, is_active);

CREATE INDEX [IX_schedule_exceptions_provider_date] ON dbo.doctor_schedule_exceptions (provider_id, exception_date, is_active);

CREATE INDEX [IX_doctor_services_doctor_active] ON dbo.doctor_services (doctor_id, is_active);

CREATE INDEX [IX_doctor_services_provider_active] ON dbo.doctor_services (provider_id, is_active);

CREATE INDEX [IX_doctor_services_service_active] ON dbo.doctor_services (service_id, is_active);

CREATE INDEX [IX_doctor_verification_decisions_provider_doctor_decided] ON dbo.doctor_verification_decisions (provider_id, doctor_id, decided_at);

CREATE INDEX [IX_working_hours_branch_day] ON dbo.doctor_working_hours (branch_id, day_of_week, is_active);

CREATE INDEX [IX_working_hours_doctor_day] ON dbo.doctor_working_hours (doctor_id, day_of_week, is_active);

CREATE INDEX [IX_working_hours_provider_active] ON dbo.doctor_working_hours (provider_id, is_active);

CREATE UNIQUE INDEX [UX_working_hours_branch_day_start] ON dbo.doctor_working_hours (branch_id, day_of_week, start_time) WHERE doctor_id IS NULL;

CREATE UNIQUE INDEX [UX_working_hours_doctor_branch_day_start] ON dbo.doctor_working_hours (doctor_id, branch_id, day_of_week, start_time) WHERE doctor_id IS NOT NULL;

CREATE INDEX [IX_doctors_provider_active] ON dbo.doctors (provider_id, is_active);

CREATE INDEX [IX_doctors_provider_specialty] ON dbo.doctors (provider_id, specialty_id);

CREATE UNIQUE INDEX [UX_doctors_provider_license] ON dbo.doctors (provider_id, license_number) WHERE license_number IS NOT NULL;

CREATE INDEX [IX_ehr_encounters_patient_started] ON dbo.ehr_encounters (patient_id, started_at);

CREATE INDEX [IX_ehr_encounters_provider_started] ON dbo.ehr_encounters (provider_id, started_at);

CREATE INDEX ix_idempotency_created_at ON dbo.idempotency_requests (created_at);

CREATE INDEX [IX_lab_reports_patient_created] ON dbo.lab_reports (patient_id, created_at);

CREATE INDEX [IX_lab_reports_provider_created] ON dbo.lab_reports (provider_id, created_at);

CREATE INDEX [IX_lab_results_canonical_name] ON dbo.lab_results (canonical_name);

CREATE INDEX [IX_lab_results_report] ON dbo.lab_results (lab_report_id);

CREATE INDEX [IX_patient_access_grants_grantee] ON dbo.patient_access_grants (grantee_provider_id, patient_id);

CREATE UNIQUE INDEX [UX_patient_access_grants_active] ON dbo.patient_access_grants (patient_id, owner_provider_id, grantee_provider_id, scope) WHERE revoked_at IS NULL;

CREATE INDEX [IX_patient_allergies_patient] ON dbo.patient_allergies (provider_id, patient_id, status);

CREATE UNIQUE INDEX [UX_patient_branch_profiles_mrn] ON dbo.patient_branch_profiles (provider_id, branch_id, medical_record_number);

CREATE UNIQUE INDEX [UX_patient_branch_profiles_patient] ON dbo.patient_branch_profiles (provider_id, branch_id, patient_id);

CREATE INDEX [IX_patient_conditions_patient] ON dbo.patient_conditions (provider_id, patient_id, clinical_status);

CREATE INDEX [IX_patient_medications_patient] ON dbo.patient_medications (provider_id, patient_id, status);

CREATE INDEX [IX_patient_provider_profiles_patient] ON dbo.patient_provider_profiles (patient_id);

CREATE INDEX [IX_patient_provider_profiles_provider] ON dbo.patient_provider_profiles (provider_id, is_active);

CREATE UNIQUE INDEX [UX_patient_provider_profiles_mrn] ON dbo.patient_provider_profiles (provider_id, medical_record_number) WHERE medical_record_number IS NOT NULL;

CREATE INDEX [IX_patients_active] ON dbo.patients (is_active);

CREATE INDEX [IX_patients_last4] ON dbo.patients (national_id_last4);

CREATE INDEX [IX_patients_phone] ON dbo.patients (phone);

CREATE INDEX ix_provider_memberships_provider ON dbo.provider_memberships (provider_id, is_active);

CREATE INDEX [IX_radiology_reports_patient_created] ON dbo.radiology_reports (patient_id, created_at);

CREATE INDEX [IX_radiology_reports_provider_created] ON dbo.radiology_reports (provider_id, created_at);

CREATE INDEX [IX_reminders_appointment] ON dbo.reminders (appointment_id);

CREATE INDEX [IX_reminders_pending_schedule] ON dbo.reminders (delivery_status, scheduled_for);

CREATE INDEX [IX_reminders_provider_schedule] ON dbo.reminders (provider_id, scheduled_for);

CREATE INDEX [IX_service_specialties_provider] ON dbo.service_specialties (provider_id);

CREATE INDEX [IX_service_specialties_specialty] ON dbo.service_specialties (specialty_id);

CREATE INDEX [IX_services_provider_active] ON dbo.services (provider_id, is_active);

CREATE INDEX [IX_services_provider_type] ON dbo.services (provider_id, service_type);

CREATE INDEX [IX_specialties_provider_active] ON dbo.specialties (provider_id, is_active);

CREATE INDEX ix_staff_audit_logs_patient_created ON dbo.staff_audit_logs (patient_id, created_at);

CREATE INDEX ix_staff_audit_logs_provider_created ON dbo.staff_audit_logs (provider_id, created_at);

CREATE INDEX ix_staff_audit_logs_user_created ON dbo.staff_audit_logs (user_id, created_at);

ALTER TABLE dbo.appointment_status_history ADD FOREIGN KEY(appointment_id) REFERENCES dbo.appointments (id);

ALTER TABLE dbo.appointment_status_history ADD FOREIGN KEY(new_slot_id) REFERENCES dbo.doctor_availability_slots (id);

ALTER TABLE dbo.appointment_status_history ADD FOREIGN KEY(old_slot_id) REFERENCES dbo.doctor_availability_slots (id);

ALTER TABLE dbo.appointment_status_history ADD FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.appointments ADD FOREIGN KEY(branch_id) REFERENCES dbo.branches (id);

ALTER TABLE dbo.appointments ADD FOREIGN KEY(patient_id) REFERENCES dbo.patients (id);

ALTER TABLE dbo.appointments ADD FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.appointments ADD FOREIGN KEY(service_id) REFERENCES dbo.services (id);

ALTER TABLE dbo.appointments ADD FOREIGN KEY(slot_id) REFERENCES dbo.doctor_availability_slots (id);

ALTER TABLE dbo.appointments ADD CONSTRAINT [FK_appointments_doctor] FOREIGN KEY(doctor_id) REFERENCES dbo.doctors (id);

ALTER TABLE dbo.branch_mrn_sequences ADD CONSTRAINT [FK_branch_mrn_sequences_branch] FOREIGN KEY(branch_id) REFERENCES dbo.branches (id);

ALTER TABLE dbo.branch_mrn_sequences ADD CONSTRAINT [FK_branch_mrn_sequences_provider] FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.branches ADD FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.clinical_notes ADD CONSTRAINT [FK_clinical_notes_addendum] FOREIGN KEY(addendum_to_note_id) REFERENCES dbo.clinical_notes (id);

ALTER TABLE dbo.clinical_notes ADD CONSTRAINT [FK_clinical_notes_doctor] FOREIGN KEY(doctor_id, provider_id) REFERENCES dbo.doctors (id, provider_id);

ALTER TABLE dbo.clinical_notes ADD CONSTRAINT [FK_clinical_notes_encounter] FOREIGN KEY(encounter_id, provider_id, patient_id) REFERENCES dbo.ehr_encounters (id, provider_id, patient_id);

ALTER TABLE dbo.clinical_notes ADD CONSTRAINT [FK_clinical_notes_profile] FOREIGN KEY(patient_id, provider_id) REFERENCES dbo.patient_provider_profiles (patient_id, provider_id);

ALTER TABLE dbo.department_specialties ADD CONSTRAINT [FK_department_specialties_department_provider] FOREIGN KEY(department_id, provider_id) REFERENCES dbo.departments (id, provider_id);

ALTER TABLE dbo.department_specialties ADD CONSTRAINT [FK_department_specialties_provider] FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.department_specialties ADD CONSTRAINT [FK_department_specialties_specialty_provider] FOREIGN KEY(specialty_id, provider_id) REFERENCES dbo.specialties (id, provider_id);

ALTER TABLE dbo.departments ADD CONSTRAINT [FK_departments_branch_provider] FOREIGN KEY(branch_id, provider_id) REFERENCES dbo.branches (id, provider_id);

ALTER TABLE dbo.departments ADD CONSTRAINT [FK_departments_provider] FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.diagnostic_assessments ADD CONSTRAINT [FK_diagnostic_assessments_radiology_report] FOREIGN KEY(radiology_report_id) REFERENCES dbo.radiology_reports (id);

ALTER TABLE dbo.diagnostic_attachments ADD CONSTRAINT [FK_diagnostic_attachments_encounter] FOREIGN KEY(encounter_id) REFERENCES dbo.ehr_encounters (id);

ALTER TABLE dbo.diagnostic_attachments ADD CONSTRAINT [FK_diagnostic_attachments_encounter_provider_patient] FOREIGN KEY(encounter_id, provider_id, patient_id) REFERENCES dbo.ehr_encounters (id, provider_id, patient_id);

ALTER TABLE dbo.diagnostic_attachments ADD CONSTRAINT [FK_diagnostic_attachments_patient] FOREIGN KEY(patient_id) REFERENCES dbo.patients (id);

ALTER TABLE dbo.diagnostic_attachments ADD CONSTRAINT [FK_diagnostic_attachments_provider] FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.doctor_availability_slots ADD FOREIGN KEY(branch_id) REFERENCES dbo.branches (id);

ALTER TABLE dbo.doctor_availability_slots ADD FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.doctor_availability_slots ADD FOREIGN KEY(working_hours_id) REFERENCES dbo.doctor_working_hours (id);

ALTER TABLE dbo.doctor_availability_slots ADD CONSTRAINT [FK_availability_slots_doctor] FOREIGN KEY(doctor_id) REFERENCES dbo.doctors (id);

ALTER TABLE dbo.doctor_branches ADD FOREIGN KEY(branch_id) REFERENCES dbo.branches (id);

ALTER TABLE dbo.doctor_branches ADD FOREIGN KEY(doctor_id) REFERENCES dbo.doctors (id);

ALTER TABLE dbo.doctor_branches ADD FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.doctor_schedule_exceptions ADD FOREIGN KEY(branch_id) REFERENCES dbo.branches (id);

ALTER TABLE dbo.doctor_schedule_exceptions ADD FOREIGN KEY(doctor_id) REFERENCES dbo.doctors (id);

ALTER TABLE dbo.doctor_schedule_exceptions ADD FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.doctor_services ADD FOREIGN KEY(doctor_id) REFERENCES dbo.doctors (id);

ALTER TABLE dbo.doctor_services ADD FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.doctor_services ADD FOREIGN KEY(service_id) REFERENCES dbo.services (id);

ALTER TABLE dbo.doctor_verification_decisions ADD CONSTRAINT [FK_doctor_verification_decisions_doctor_provider] FOREIGN KEY(doctor_id, provider_id) REFERENCES dbo.doctors (id, provider_id);

ALTER TABLE dbo.doctor_verification_decisions ADD CONSTRAINT [FK_doctor_verification_decisions_provider] FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.doctor_verification_decisions ADD CONSTRAINT [FK_doctor_verification_decisions_reviewer_membership] FOREIGN KEY(reviewer_membership_id, reviewer_user_id, provider_id) REFERENCES dbo.provider_memberships (id, user_id, provider_id);

ALTER TABLE dbo.doctor_working_hours ADD FOREIGN KEY(branch_id) REFERENCES dbo.branches (id);

ALTER TABLE dbo.doctor_working_hours ADD FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.doctor_working_hours ADD CONSTRAINT [FK_working_hours_doctor] FOREIGN KEY(doctor_id) REFERENCES dbo.doctors (id);

ALTER TABLE dbo.doctors ADD FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.doctors ADD FOREIGN KEY(specialty_id) REFERENCES dbo.specialties (id);

ALTER TABLE dbo.ehr_encounters ADD CONSTRAINT [FK_ehr_encounters_appointment_provider] FOREIGN KEY(appointment_id, provider_id) REFERENCES dbo.appointments (id, provider_id);

ALTER TABLE dbo.ehr_encounters ADD CONSTRAINT [FK_ehr_encounters_branch] FOREIGN KEY(branch_id) REFERENCES dbo.branches (id);

ALTER TABLE dbo.ehr_encounters ADD CONSTRAINT [FK_ehr_encounters_branch_provider] FOREIGN KEY(branch_id, provider_id) REFERENCES dbo.branches (id, provider_id);

ALTER TABLE dbo.ehr_encounters ADD CONSTRAINT [FK_ehr_encounters_doctor] FOREIGN KEY(doctor_id) REFERENCES dbo.doctors (id);

ALTER TABLE dbo.ehr_encounters ADD CONSTRAINT [FK_ehr_encounters_doctor_provider] FOREIGN KEY(doctor_id, provider_id) REFERENCES dbo.doctors (id, provider_id);

ALTER TABLE dbo.ehr_encounters ADD CONSTRAINT [FK_ehr_encounters_patient] FOREIGN KEY(patient_id) REFERENCES dbo.patients (id);

ALTER TABLE dbo.ehr_encounters ADD CONSTRAINT [FK_ehr_encounters_provider] FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.lab_reports ADD CONSTRAINT [FK_lab_reports_diagnostic_attachment] FOREIGN KEY(diagnostic_attachment_id) REFERENCES dbo.diagnostic_attachments (id);

ALTER TABLE dbo.lab_reports ADD CONSTRAINT [FK_lab_reports_encounter] FOREIGN KEY(encounter_id) REFERENCES dbo.ehr_encounters (id);

ALTER TABLE dbo.lab_reports ADD CONSTRAINT [FK_lab_reports_encounter_provider_patient] FOREIGN KEY(encounter_id, provider_id, patient_id) REFERENCES dbo.ehr_encounters (id, provider_id, patient_id);

ALTER TABLE dbo.lab_reports ADD CONSTRAINT [FK_lab_reports_patient] FOREIGN KEY(patient_id) REFERENCES dbo.patients (id);

ALTER TABLE dbo.lab_reports ADD CONSTRAINT [FK_lab_reports_provider] FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.lab_results ADD CONSTRAINT [FK_lab_results_report] FOREIGN KEY(lab_report_id) REFERENCES dbo.lab_reports (id);

ALTER TABLE dbo.patient_access_grants ADD CONSTRAINT [FK_patient_access_grants_grantee] FOREIGN KEY(grantee_provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.patient_access_grants ADD CONSTRAINT [FK_patient_access_grants_owner_profile] FOREIGN KEY(patient_id, owner_provider_id) REFERENCES dbo.patient_provider_profiles (patient_id, provider_id);

ALTER TABLE dbo.patient_allergies ADD CONSTRAINT [FK_patient_allergies_doctor] FOREIGN KEY(recorded_by_doctor_id, provider_id) REFERENCES dbo.doctors (id, provider_id);

ALTER TABLE dbo.patient_allergies ADD CONSTRAINT [FK_patient_allergies_encounter] FOREIGN KEY(encounter_id, provider_id, patient_id) REFERENCES dbo.ehr_encounters (id, provider_id, patient_id);

ALTER TABLE dbo.patient_allergies ADD CONSTRAINT [FK_patient_allergies_profile] FOREIGN KEY(patient_id, provider_id) REFERENCES dbo.patient_provider_profiles (patient_id, provider_id);

ALTER TABLE dbo.patient_branch_profiles ADD CONSTRAINT [FK_patient_branch_profiles_branch] FOREIGN KEY(branch_id) REFERENCES dbo.branches (id);

ALTER TABLE dbo.patient_branch_profiles ADD CONSTRAINT [FK_patient_branch_profiles_patient] FOREIGN KEY(patient_id) REFERENCES dbo.patients (id);

ALTER TABLE dbo.patient_branch_profiles ADD CONSTRAINT [FK_patient_branch_profiles_provider] FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.patient_conditions ADD CONSTRAINT [FK_patient_conditions_doctor] FOREIGN KEY(recorded_by_doctor_id, provider_id) REFERENCES dbo.doctors (id, provider_id);

ALTER TABLE dbo.patient_conditions ADD CONSTRAINT [FK_patient_conditions_encounter] FOREIGN KEY(encounter_id, provider_id, patient_id) REFERENCES dbo.ehr_encounters (id, provider_id, patient_id);

ALTER TABLE dbo.patient_conditions ADD CONSTRAINT [FK_patient_conditions_profile] FOREIGN KEY(patient_id, provider_id) REFERENCES dbo.patient_provider_profiles (patient_id, provider_id);

ALTER TABLE dbo.patient_medications ADD CONSTRAINT [FK_patient_medications_doctor] FOREIGN KEY(prescribed_by_doctor_id, provider_id) REFERENCES dbo.doctors (id, provider_id);

ALTER TABLE dbo.patient_medications ADD CONSTRAINT [FK_patient_medications_encounter] FOREIGN KEY(encounter_id, provider_id, patient_id) REFERENCES dbo.ehr_encounters (id, provider_id, patient_id);

ALTER TABLE dbo.patient_medications ADD CONSTRAINT [FK_patient_medications_profile] FOREIGN KEY(patient_id, provider_id) REFERENCES dbo.patient_provider_profiles (patient_id, provider_id);

ALTER TABLE dbo.patient_provider_profiles ADD FOREIGN KEY(patient_id) REFERENCES dbo.patients (id);

ALTER TABLE dbo.patient_provider_profiles ADD FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.provider_memberships ADD CONSTRAINT fk_provider_memberships_doctor FOREIGN KEY(doctor_id) REFERENCES dbo.doctors (id);

ALTER TABLE dbo.provider_memberships ADD CONSTRAINT fk_provider_memberships_provider FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.provider_memberships ADD CONSTRAINT fk_provider_memberships_user_account FOREIGN KEY(user_id) REFERENCES dbo.user_accounts (id);

ALTER TABLE dbo.radiology_reports ADD CONSTRAINT [FK_radiology_reports_diagnostic_attachment] FOREIGN KEY(diagnostic_attachment_id) REFERENCES dbo.diagnostic_attachments (id);

ALTER TABLE dbo.radiology_reports ADD CONSTRAINT [FK_radiology_reports_encounter] FOREIGN KEY(encounter_id) REFERENCES dbo.ehr_encounters (id);

ALTER TABLE dbo.radiology_reports ADD CONSTRAINT [FK_radiology_reports_encounter_provider_patient] FOREIGN KEY(encounter_id, provider_id, patient_id) REFERENCES dbo.ehr_encounters (id, provider_id, patient_id);

ALTER TABLE dbo.radiology_reports ADD CONSTRAINT [FK_radiology_reports_patient] FOREIGN KEY(patient_id) REFERENCES dbo.patients (id);

ALTER TABLE dbo.radiology_reports ADD CONSTRAINT [FK_radiology_reports_provider] FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.reminders ADD FOREIGN KEY(appointment_id) REFERENCES dbo.appointments (id);

ALTER TABLE dbo.reminders ADD FOREIGN KEY(patient_id) REFERENCES dbo.patients (id);

ALTER TABLE dbo.reminders ADD FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.service_specialties ADD FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.service_specialties ADD FOREIGN KEY(service_id) REFERENCES dbo.services (id);

ALTER TABLE dbo.service_specialties ADD FOREIGN KEY(specialty_id) REFERENCES dbo.specialties (id);

ALTER TABLE dbo.services ADD FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

ALTER TABLE dbo.specialties ADD FOREIGN KEY(provider_id) REFERENCES dbo.providers (id);

CREATE TABLE dbo.alembic_version (
	version_num VARCHAR(32) NOT NULL,
	CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
INSERT INTO dbo.alembic_version (version_num) VALUES ('c3d9e6a2f8b1');

COMMIT TRANSACTION;

SELECT DB_NAME() AS synthetic_database,
       (SELECT COUNT(*) FROM sys.tables WHERE is_ms_shipped = 0) AS user_tables,
       (SELECT version_num FROM dbo.alembic_version) AS alembic_version;
