/* =====================================================================
   MedMind -  |  Script 01: EHR schema
   Additive and idempotent: safe to run more than once.
   Rollback: 01b_rollback_ehr_schema.sql

   WHAT THIS ADDS
   1. Composite unique keys on existing tables (doctors, branches,
      appointments, ehr_encounters) so child tables can prove that
      provider / patient / doctor / encounter all belong together.
   2. Composite foreign keys on ehr_encounters, lab_reports,
      radiology_reports and diagnostic_attachments (skipped with a
      warning if existing rows would violate them).
   3. New tables: patient_conditions, patient_allergies,
      patient_medications, clinical_notes, patient_access_grants.
   4. A trigger that makes SIGNED clinical notes immutable (corrections
      are new rows, e.g. an addendum note).
   5. View dbo.vw_active_access_grants.

   Existing tables/columns are NOT altered or dropped.

   Select the MedMind database in SSMS first.  Take a backup first.

   ===================================================================== */
IF DB_ID() <= 4 OR OBJECT_ID(N'dbo.ehr_encounters', N'U') IS NULL
BEGIN
    RAISERROR(N'Select the restored MedMind database first.', 16, 1);
    SET NOEXEC ON;
END
GO
SET XACT_ABORT ON;
GO

/* ---------- 1. Composite unique keys on existing tables ---------- */
IF NOT EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = N'UQ_doctors_id_provider')
    ALTER TABLE dbo.doctors ADD CONSTRAINT UQ_doctors_id_provider UNIQUE (id, provider_id);
IF NOT EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = N'UQ_branches_id_provider')
    ALTER TABLE dbo.branches ADD CONSTRAINT UQ_branches_id_provider UNIQUE (id, provider_id);
IF NOT EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = N'UQ_appointments_id_provider')
    ALTER TABLE dbo.appointments ADD CONSTRAINT UQ_appointments_id_provider UNIQUE (id, provider_id);
IF NOT EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = N'UQ_ehr_encounters_id_provider_patient')
    ALTER TABLE dbo.ehr_encounters ADD CONSTRAINT UQ_ehr_encounters_id_provider_patient UNIQUE (id, provider_id, patient_id);
GO

/* ---------- 2. Composite foreign keys on existing tables ----------
   Each one is added only if the current data already satisfies it.
   SQL Server skips a composite FK when any of its columns is NULL, so
   optional links (encounter_id / doctor_id / branch_id NULL) stay legal. */

-- ehr_encounters (doctor_id, provider_id) -> doctors
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_ehr_encounters_doctor_provider')
BEGIN
    IF EXISTS (SELECT 1 FROM dbo.ehr_encounters e
               WHERE e.doctor_id IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM dbo.doctors d WHERE d.id = e.doctor_id AND d.provider_id = e.provider_id))
        RAISERROR(N'SKIPPED FK_ehr_encounters_doctor_provider: existing encounters use a doctor from another provider.', 10, 1) WITH NOWAIT;
    ELSE
        ALTER TABLE dbo.ehr_encounters WITH CHECK ADD CONSTRAINT FK_ehr_encounters_doctor_provider
            FOREIGN KEY (doctor_id, provider_id) REFERENCES dbo.doctors (id, provider_id);
END
GO
-- ehr_encounters (branch_id, provider_id) -> branches
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_ehr_encounters_branch_provider')
BEGIN
    IF EXISTS (SELECT 1 FROM dbo.ehr_encounters e
               WHERE e.branch_id IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM dbo.branches b WHERE b.id = e.branch_id AND b.provider_id = e.provider_id))
        RAISERROR(N'SKIPPED FK_ehr_encounters_branch_provider: existing encounters use a branch from another provider.', 10, 1) WITH NOWAIT;
    ELSE
        ALTER TABLE dbo.ehr_encounters WITH CHECK ADD CONSTRAINT FK_ehr_encounters_branch_provider
            FOREIGN KEY (branch_id, provider_id) REFERENCES dbo.branches (id, provider_id);
END
GO
-- ehr_encounters (appointment_id, provider_id) -> appointments (the original table had no FK on appointment_id at all)
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_ehr_encounters_appointment_provider')
BEGIN
    IF EXISTS (SELECT 1 FROM dbo.ehr_encounters e
               WHERE e.appointment_id IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM dbo.appointments a WHERE a.id = e.appointment_id AND a.provider_id = e.provider_id))
        RAISERROR(N'SKIPPED FK_ehr_encounters_appointment_provider: existing encounters point to a missing/foreign appointment.', 10, 1) WITH NOWAIT;
    ELSE
        ALTER TABLE dbo.ehr_encounters WITH CHECK ADD CONSTRAINT FK_ehr_encounters_appointment_provider
            FOREIGN KEY (appointment_id, provider_id) REFERENCES dbo.appointments (id, provider_id);
END
GO
-- lab_reports (encounter, provider, patient) -> ehr_encounters
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_lab_reports_encounter_provider_patient')
BEGIN
    IF EXISTS (SELECT 1 FROM dbo.lab_reports r
               WHERE r.encounter_id IS NOT NULL AND r.patient_id IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM dbo.ehr_encounters e
                                 WHERE e.id = r.encounter_id AND e.provider_id = r.provider_id AND e.patient_id = r.patient_id))
        RAISERROR(N'SKIPPED FK_lab_reports_encounter_provider_patient: existing lab reports disagree with their encounter.', 10, 1) WITH NOWAIT;
    ELSE
        ALTER TABLE dbo.lab_reports WITH CHECK ADD CONSTRAINT FK_lab_reports_encounter_provider_patient
            FOREIGN KEY (encounter_id, provider_id, patient_id) REFERENCES dbo.ehr_encounters (id, provider_id, patient_id);
END
GO
-- radiology_reports
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_radiology_reports_encounter_provider_patient')
BEGIN
    IF EXISTS (SELECT 1 FROM dbo.radiology_reports r
               WHERE r.encounter_id IS NOT NULL AND r.patient_id IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM dbo.ehr_encounters e
                                 WHERE e.id = r.encounter_id AND e.provider_id = r.provider_id AND e.patient_id = r.patient_id))
        RAISERROR(N'SKIPPED FK_radiology_reports_encounter_provider_patient: existing radiology reports disagree with their encounter.', 10, 1) WITH NOWAIT;
    ELSE
        ALTER TABLE dbo.radiology_reports WITH CHECK ADD CONSTRAINT FK_radiology_reports_encounter_provider_patient
            FOREIGN KEY (encounter_id, provider_id, patient_id) REFERENCES dbo.ehr_encounters (id, provider_id, patient_id);
END
GO
-- diagnostic_attachments
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_diagnostic_attachments_encounter_provider_patient')
BEGIN
    IF EXISTS (SELECT 1 FROM dbo.diagnostic_attachments r
               WHERE r.encounter_id IS NOT NULL AND r.patient_id IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM dbo.ehr_encounters e
                                 WHERE e.id = r.encounter_id AND e.provider_id = r.provider_id AND e.patient_id = r.patient_id))
        RAISERROR(N'SKIPPED FK_diagnostic_attachments_encounter_provider_patient: existing attachments disagree with their encounter.', 10, 1) WITH NOWAIT;
    ELSE
        ALTER TABLE dbo.diagnostic_attachments WITH CHECK ADD CONSTRAINT FK_diagnostic_attachments_encounter_provider_patient
            FOREIGN KEY (encounter_id, provider_id, patient_id) REFERENCES dbo.ehr_encounters (id, provider_id, patient_id);
END
GO

/* ---------- 3. New EHR tables ----------
   Common rules for every table below:
   * provider_id is mandatory (tenant scoping).
   * (patient_id, provider_id) must exist in patient_provider_profiles,
     so a record can only exist for a patient registered at that provider.
   * encounter_id, when present, must belong to the SAME provider and patient.
   * doctor ids, when present, must belong to the SAME provider.        */

IF OBJECT_ID(N'dbo.patient_conditions', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.patient_conditions (
        id                    uniqueidentifier NOT NULL CONSTRAINT DF_patient_conditions_id DEFAULT (NEWID()),
        provider_id           uniqueidentifier NOT NULL,
        patient_id            uniqueidentifier NOT NULL,
        encounter_id          uniqueidentifier NULL,
        recorded_by_doctor_id uniqueidentifier NULL,
        condition_name        nvarchar(200)    NOT NULL,
        icd10_code            varchar(10)      NULL,
        clinical_status       varchar(20)      NOT NULL CONSTRAINT DF_patient_conditions_status DEFAULT ('active'),
        severity              varchar(20)      NULL,
        onset_date            date             NULL,
        resolved_date         date             NULL,
        notes                 nvarchar(1000)   NULL,
        created_at            datetimeoffset(7) NOT NULL CONSTRAINT DF_patient_conditions_created DEFAULT (SYSUTCDATETIME()),
        updated_at            datetimeoffset(7) NOT NULL CONSTRAINT DF_patient_conditions_updated DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT PK_patient_conditions PRIMARY KEY CLUSTERED (id),
        CONSTRAINT FK_patient_conditions_profile   FOREIGN KEY (patient_id, provider_id) REFERENCES dbo.patient_provider_profiles (patient_id, provider_id),
        CONSTRAINT FK_patient_conditions_encounter FOREIGN KEY (encounter_id, provider_id, patient_id) REFERENCES dbo.ehr_encounters (id, provider_id, patient_id),
        CONSTRAINT FK_patient_conditions_doctor    FOREIGN KEY (recorded_by_doctor_id, provider_id) REFERENCES dbo.doctors (id, provider_id),
        CONSTRAINT CK_patient_conditions_status    CHECK (clinical_status IN ('active','resolved','inactive')),
        CONSTRAINT CK_patient_conditions_severity  CHECK (severity IS NULL OR severity IN ('mild','moderate','severe')),
        CONSTRAINT CK_patient_conditions_dates     CHECK (resolved_date IS NULL OR onset_date IS NULL OR resolved_date >= onset_date),
        CONSTRAINT CK_patient_conditions_resolved  CHECK (clinical_status <> 'resolved' OR resolved_date IS NOT NULL)
    );
    CREATE INDEX IX_patient_conditions_patient ON dbo.patient_conditions (provider_id, patient_id, clinical_status);
END
GO

IF OBJECT_ID(N'dbo.patient_allergies', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.patient_allergies (
        id                    uniqueidentifier NOT NULL CONSTRAINT DF_patient_allergies_id DEFAULT (NEWID()),
        provider_id           uniqueidentifier NOT NULL,
        patient_id            uniqueidentifier NOT NULL,
        encounter_id          uniqueidentifier NULL,
        recorded_by_doctor_id uniqueidentifier NULL,
        allergen              nvarchar(200)    NOT NULL,
        allergen_type         varchar(20)      NOT NULL,
        reaction              nvarchar(300)    NULL,
        severity              varchar(20)      NOT NULL CONSTRAINT DF_patient_allergies_severity DEFAULT ('mild'),
        status                varchar(20)      NOT NULL CONSTRAINT DF_patient_allergies_status DEFAULT ('active'),
        noted_date            date             NULL,
        created_at            datetimeoffset(7) NOT NULL CONSTRAINT DF_patient_allergies_created DEFAULT (SYSUTCDATETIME()),
        updated_at            datetimeoffset(7) NOT NULL CONSTRAINT DF_patient_allergies_updated DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT PK_patient_allergies PRIMARY KEY CLUSTERED (id),
        CONSTRAINT FK_patient_allergies_profile   FOREIGN KEY (patient_id, provider_id) REFERENCES dbo.patient_provider_profiles (patient_id, provider_id),
        CONSTRAINT FK_patient_allergies_encounter FOREIGN KEY (encounter_id, provider_id, patient_id) REFERENCES dbo.ehr_encounters (id, provider_id, patient_id),
        CONSTRAINT FK_patient_allergies_doctor    FOREIGN KEY (recorded_by_doctor_id, provider_id) REFERENCES dbo.doctors (id, provider_id),
        CONSTRAINT CK_patient_allergies_type      CHECK (allergen_type IN ('drug','food','environmental','other')),
        CONSTRAINT CK_patient_allergies_severity  CHECK (severity IN ('mild','moderate','severe','life_threatening')),
        CONSTRAINT CK_patient_allergies_status    CHECK (status IN ('active','inactive','resolved'))
    );
    CREATE INDEX IX_patient_allergies_patient ON dbo.patient_allergies (provider_id, patient_id, status);
END
GO

IF OBJECT_ID(N'dbo.patient_medications', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.patient_medications (
        id                    uniqueidentifier NOT NULL CONSTRAINT DF_patient_medications_id DEFAULT (NEWID()),
        provider_id           uniqueidentifier NOT NULL,
        patient_id            uniqueidentifier NOT NULL,
        encounter_id          uniqueidentifier NULL,
        prescribed_by_doctor_id uniqueidentifier NULL,
        medication_name       nvarchar(200)    NOT NULL,
        dosage                nvarchar(100)    NULL,
        frequency             nvarchar(100)    NULL,
        route                 varchar(30)      NULL,
        start_date            date             NULL,
        end_date              date             NULL,
        status                varchar(20)      NOT NULL CONSTRAINT DF_patient_medications_status DEFAULT ('active'),
        notes                 nvarchar(500)    NULL,
        created_at            datetimeoffset(7) NOT NULL CONSTRAINT DF_patient_medications_created DEFAULT (SYSUTCDATETIME()),
        updated_at            datetimeoffset(7) NOT NULL CONSTRAINT DF_patient_medications_updated DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT PK_patient_medications PRIMARY KEY CLUSTERED (id),
        CONSTRAINT FK_patient_medications_profile   FOREIGN KEY (patient_id, provider_id) REFERENCES dbo.patient_provider_profiles (patient_id, provider_id),
        CONSTRAINT FK_patient_medications_encounter FOREIGN KEY (encounter_id, provider_id, patient_id) REFERENCES dbo.ehr_encounters (id, provider_id, patient_id),
        CONSTRAINT FK_patient_medications_doctor    FOREIGN KEY (prescribed_by_doctor_id, provider_id) REFERENCES dbo.doctors (id, provider_id),
        CONSTRAINT CK_patient_medications_status    CHECK (status IN ('active','completed','stopped')),
        CONSTRAINT CK_patient_medications_dates     CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date)
    );
    CREATE INDEX IX_patient_medications_patient ON dbo.patient_medications (provider_id, patient_id, status);
END
GO

IF OBJECT_ID(N'dbo.clinical_notes', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.clinical_notes (
        id            uniqueidentifier NOT NULL CONSTRAINT DF_clinical_notes_id DEFAULT (NEWID()),
        provider_id   uniqueidentifier NOT NULL,
        patient_id    uniqueidentifier NOT NULL,
        encounter_id  uniqueidentifier NOT NULL,   -- every note belongs to a visit
        doctor_id     uniqueidentifier NOT NULL,   -- author
        note_type     varchar(20)      NOT NULL CONSTRAINT DF_clinical_notes_type DEFAULT ('progress'),
        title         nvarchar(200)    NULL,
        note_text     nvarchar(max)    NOT NULL,
        status        varchar(20)      NOT NULL CONSTRAINT DF_clinical_notes_status DEFAULT ('draft'),
        signed_at     datetimeoffset(7) NULL,
        addendum_to_note_id uniqueidentifier NULL,  -- corrections are new notes pointing at the original
        created_at    datetimeoffset(7) NOT NULL CONSTRAINT DF_clinical_notes_created DEFAULT (SYSUTCDATETIME()),
        updated_at    datetimeoffset(7) NOT NULL CONSTRAINT DF_clinical_notes_updated DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT PK_clinical_notes PRIMARY KEY CLUSTERED (id),
        CONSTRAINT FK_clinical_notes_profile   FOREIGN KEY (patient_id, provider_id) REFERENCES dbo.patient_provider_profiles (patient_id, provider_id),
        CONSTRAINT FK_clinical_notes_encounter FOREIGN KEY (encounter_id, provider_id, patient_id) REFERENCES dbo.ehr_encounters (id, provider_id, patient_id),
        CONSTRAINT FK_clinical_notes_doctor    FOREIGN KEY (doctor_id, provider_id) REFERENCES dbo.doctors (id, provider_id),
        CONSTRAINT FK_clinical_notes_addendum  FOREIGN KEY (addendum_to_note_id) REFERENCES dbo.clinical_notes (id),
        CONSTRAINT CK_clinical_notes_type      CHECK (note_type IN ('progress','consultation','soap','discharge','addendum')),
        CONSTRAINT CK_clinical_notes_status    CHECK (status IN ('draft','signed')),
        CONSTRAINT CK_clinical_notes_signed    CHECK ((status = 'signed' AND signed_at IS NOT NULL) OR (status = 'draft' AND signed_at IS NULL)),
        CONSTRAINT CK_clinical_notes_addendum  CHECK (note_type <> 'addendum' OR addendum_to_note_id IS NOT NULL)
    );
    CREATE INDEX IX_clinical_notes_patient   ON dbo.clinical_notes (provider_id, patient_id, created_at DESC);
    CREATE INDEX IX_clinical_notes_encounter ON dbo.clinical_notes (encounter_id);
END
GO

/* Cross-provider access: one row = "patient X allows provider GRANTEE to read
   the records that provider OWNER holds". Without an active row, no provider
   may read another provider's records.                                       */
IF OBJECT_ID(N'dbo.patient_access_grants', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.patient_access_grants (
        id                   uniqueidentifier NOT NULL CONSTRAINT DF_patient_access_grants_id DEFAULT (NEWID()),
        patient_id           uniqueidentifier NOT NULL,
        owner_provider_id    uniqueidentifier NOT NULL,   -- provider that holds the records
        grantee_provider_id  uniqueidentifier NOT NULL,   -- provider allowed to read them
        scope                varchar(20)      NOT NULL CONSTRAINT DF_patient_access_grants_scope DEFAULT ('full_record'),
        granted_by           varchar(20)      NOT NULL CONSTRAINT DF_patient_access_grants_by DEFAULT ('patient'),
        granted_at           datetimeoffset(7) NOT NULL CONSTRAINT DF_patient_access_grants_at DEFAULT (SYSUTCDATETIME()),
        expires_at           datetimeoffset(7) NULL,
        revoked_at           datetimeoffset(7) NULL,
        revoked_reason       nvarchar(300)    NULL,
        created_at           datetimeoffset(7) NOT NULL CONSTRAINT DF_patient_access_grants_created DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT PK_patient_access_grants PRIMARY KEY CLUSTERED (id),
        CONSTRAINT FK_patient_access_grants_owner_profile FOREIGN KEY (patient_id, owner_provider_id) REFERENCES dbo.patient_provider_profiles (patient_id, provider_id),
        CONSTRAINT FK_patient_access_grants_grantee       FOREIGN KEY (grantee_provider_id) REFERENCES dbo.providers (id),
        CONSTRAINT CK_patient_access_grants_distinct CHECK (owner_provider_id <> grantee_provider_id),
        CONSTRAINT CK_patient_access_grants_scope    CHECK (scope IN ('full_record','history_only','reports_only')),
        CONSTRAINT CK_patient_access_grants_by       CHECK (granted_by IN ('patient','staff')),
        CONSTRAINT CK_patient_access_grants_expiry   CHECK (expires_at IS NULL OR expires_at > granted_at),
        CONSTRAINT CK_patient_access_grants_revoked  CHECK (revoked_at IS NULL OR revoked_at >= granted_at)
    );
    CREATE UNIQUE INDEX UX_patient_access_grants_active
        ON dbo.patient_access_grants (patient_id, owner_provider_id, grantee_provider_id, scope)
        WHERE revoked_at IS NULL;
    CREATE INDEX IX_patient_access_grants_grantee ON dbo.patient_access_grants (grantee_provider_id, patient_id);
END
GO

/* ---------- 4. Signed clinical notes are immutable ---------- */
CREATE OR ALTER TRIGGER dbo.TR_clinical_notes_protect_signed
ON dbo.clinical_notes
AFTER UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1
        FROM deleted d
        LEFT JOIN inserted i ON i.id = d.id
        WHERE d.status = 'signed'
          AND (   i.id IS NULL
               OR i.status <> d.status
               OR i.note_text <> d.note_text
               OR ISNULL(i.title, N'') <> ISNULL(d.title, N'')
               OR i.encounter_id <> d.encounter_id
               OR i.doctor_id <> d.doctor_id
               OR i.patient_id <> d.patient_id
               OR i.provider_id <> d.provider_id)
    )
    BEGIN
        RAISERROR(N'Signed clinical notes cannot be changed or deleted. Add an addendum note instead.', 16, 1);
        ROLLBACK TRANSACTION;
    END
END
GO

/* ---------- 5. Convenience view: grants that are currently usable ---------- */
CREATE OR ALTER VIEW dbo.vw_active_access_grants
AS
SELECT g.id, g.patient_id, g.owner_provider_id, g.grantee_provider_id, g.scope, g.granted_at, g.expires_at
FROM dbo.patient_access_grants g
WHERE g.revoked_at IS NULL
  AND (g.expires_at IS NULL OR g.expires_at > SYSUTCDATETIME());
GO

PRINT N'01_ehr_schema.sql finished. Look above for any "SKIPPED" warnings.';
GO
SET NOEXEC OFF;
GO
