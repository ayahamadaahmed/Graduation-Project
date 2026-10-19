/* =====================================================================
   MedMind - Sprint "Database Completion"  |  Script 03: Staff, patients, visits, EHR data
   Run AFTER script 01 (EHR schema) and script 02 (providers).

   WHAT IT CREATES (all idempotent, deterministic ids, nothing existing is modified):
   A. Staff accounts + memberships for ALL providers: admin, receptionist,
      lab_staff (hospitals/labs) and one account per active doctor.
      Login format:  <role or doctor name>@<tenant_key>.medmind-demo.com
      e.g. admin@clinic-001.medmind-demo.com, reception@hospital-002.medmind-demo.com
      Demo password for ALL of them:  MedMind#Demo2026   (change before any real use)
   B. Patient profiles: ~12 existing patients registered at each new provider
      (each patient ends up at 2 new providers, which exercises cross-provider rules),
      plus a branch profile with a medical record number (MRN).
   C. Two historical visits per profile at the 6 new providers:
      slot -> completed appointment -> status history -> closed encounter.
   D. One past encounter for every existing patient at hospital-001 and clinic-001.
   E. Clinical data for hospital/clinic encounters: conditions, medications,
      allergies and signed clinical notes (synthetic, clinically coherent).
   F. Two historical CBC lab reports per profile at lab-002 with structured results.
   G. Sample cross-provider access grants (active, revoked and expired).

   NOTES
   * Patient national IDs are NOT touched: no patients are created, existing ones are reused.
   * Seeded lab reports point at placeholder attachment rows (size 0, storage_key
     'seed/...'): the structured results are real rows, but opening the
     original image/PDF through the file endpoint will not find a file.
   * No radiology/AI model outputs are fabricated: lab-003 gets visits only.
   * DRY RUN BY DEFAULT: set @commit = 1 to keep the data.
   ===================================================================== */
IF DB_ID() <= 4 OR OBJECT_ID(N'dbo.providers', N'U') IS NULL
BEGIN
    RAISERROR(N'Select the restored MedMind database first.', 16, 1);
    SET NOEXEC ON;
END
GO
SET QUOTED_IDENTIFIER ON;
SET ANSI_NULLS ON;
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @commit bit = 0;      -- <<< 0 = dry run (rollback), 1 = keep the data
DECLARE @pwd varchar(255) = '$2b$12$MU7j0ppVRyBKFdm/N.vX3.zXLoBe7p8w.tlm78D18O1r1DacodvXK';   -- bcrypt of the demo password
DECLARE @today date = CAST(SYSUTCDATETIME() AS date);
DECLARE @year int = YEAR(SYSUTCDATETIME());

DROP TABLE IF EXISTS #pref, #staff, #np, #pt, #fb, #newbp, #dpool, #vbase, #visit, #enc, #clin, #allg, #e, #condrows, #medrows, #allrows, #labenc, #cbc, #labres, #gr;

BEGIN TRY
BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.clinical_notes', N'U') IS NULL OR OBJECT_ID(N'dbo.patient_access_grants', N'U') IS NULL
    RAISERROR(N'Run 01_ehr_schema.sql first (EHR tables are missing).', 16, 1);

/* ============ A. STAFF ACCOUNTS ============ */
CREATE TABLE #staff (
    user_id uniqueidentifier,
    email varchar(254) COLLATE DATABASE_DEFAULT,
    provider_id uniqueidentifier,
    role varchar(30) COLLATE DATABASE_DEFAULT,
    doctor_id uniqueidentifier NULL
);

INSERT INTO #staff (user_id, email, provider_id, role, doctor_id)
SELECT CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|user|', r.role_key, N'|', p.tenant_key)), 1, 16) AS uniqueidentifier),
       CONCAT(r.role_key, '@', p.tenant_key, '.medmind-demo.com'),
       p.id, r.role_name, NULL
FROM dbo.providers p
CROSS JOIN (VALUES ('admin','provider_admin'), ('reception','receptionist'), ('lab','lab_staff')) r(role_key, role_name)
WHERE p.is_active = 1
  AND (r.role_key <> 'lab' OR p.org_type IN ('hospital','diagnostic_lab'));

INSERT INTO #staff (user_id, email, provider_id, role, doctor_id)
SELECT CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|user_doctor|', d.id)), 1, 16) AS uniqueidentifier),
       CONCAT(LOWER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(d.full_name_en, 'Prof. ', ''), 'Dr. ', ''), '.', ''), ' ', '.'), '''', ''), '-', '')),
              '@', p.tenant_key, '.medmind-demo.com'),
       d.provider_id, 'doctor', d.id
FROM dbo.doctors d
JOIN dbo.providers p ON p.id = d.provider_id
WHERE d.is_active = 1 AND p.is_active = 1;

INSERT INTO dbo.user_accounts (id, email, password_hash, is_active, created_at, updated_at)
SELECT s.user_id, s.email, @pwd, 1, SYSDATETIMEOFFSET(), SYSDATETIMEOFFSET()
FROM #staff s
WHERE NOT EXISTS (
    SELECT 1
    FROM dbo.user_accounts u
    WHERE u.email COLLATE DATABASE_DEFAULT = s.email COLLATE DATABASE_DEFAULT
)
  AND NOT EXISTS (SELECT 1 FROM dbo.user_accounts u WHERE u.id = s.user_id);

INSERT INTO dbo.provider_memberships (id, user_id, provider_id, role, doctor_id, is_active, created_at, updated_at)
SELECT CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|membership|', s.user_id, N'|', s.provider_id)), 1, 16) AS uniqueidentifier), s.user_id, s.provider_id, s.role, s.doctor_id, 1, SYSDATETIMEOFFSET(), SYSDATETIMEOFFSET()
FROM #staff s
JOIN dbo.user_accounts u ON u.id = s.user_id
WHERE NOT EXISTS (SELECT 1 FROM dbo.provider_memberships m WHERE m.user_id = s.user_id AND m.provider_id = s.provider_id);

/* ============ B. PATIENT PROFILES AT THE 6 NEW PROVIDERS ============ */
SELECT p.id AS provider_id, p.tenant_key, p.org_type, ROW_NUMBER() OVER (ORDER BY p.tenant_key) AS k
INTO #np
FROM dbo.providers p
WHERE p.tenant_key IN ('hospital-002','hospital-003','clinic-002','clinic-003','lab-002','lab-003');

IF (SELECT COUNT(*) FROM #np) < 6
    RAISERROR(N'Run 02_seed_providers.sql (with @commit = 1) first: the 6 new providers were not found.', 16, 1);

SELECT pa.id AS patient_id, ROW_NUMBER() OVER (ORDER BY pa.patient_code) AS r
INTO #pt
FROM dbo.patients pa
WHERE pa.is_active = 1;

INSERT INTO dbo.patient_provider_profiles (id, patient_id, provider_id, medical_record_number, preferred_channel,
                                           consent_status, consent_timestamp, is_active, created_at, updated_at)
SELECT CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|profile|', pt.patient_id, N'|', np.provider_id)), 1, 16) AS uniqueidentifier), pt.patient_id, np.provider_id, NULL, 'web',
       'granted', SYSDATETIMEOFFSET(), 1, SYSDATETIMEOFFSET(), SYSDATETIMEOFFSET()
FROM #np np
JOIN #pt pt ON (pt.r % 6) IN ((np.k - 1) % 6, np.k % 6)
WHERE NOT EXISTS (SELECT 1 FROM dbo.patient_provider_profiles x WHERE x.patient_id = pt.patient_id AND x.provider_id = np.provider_id);

/* branch profile (MRN) at each provider's first active branch */
SELECT bb.provider_id, bb.id AS branch_id, bb.mrn_code
INTO #fb
FROM (SELECT b.provider_id, b.id, b.mrn_code,
             ROW_NUMBER() OVER (PARTITION BY b.provider_id ORDER BY b.code) AS rn
      FROM dbo.branches b
      WHERE b.is_active = 1 AND b.mrn_code IS NOT NULL) bb
JOIN #np np ON np.provider_id = bb.provider_id
WHERE bb.rn = 1;

SELECT f.provider_id, f.branch_id, f.mrn_code, ppp.patient_id,
       ISNULL(sq.last_number, 0) + ROW_NUMBER() OVER (PARTITION BY f.provider_id, f.branch_id ORDER BY pt.r) AS n
INTO #newbp
FROM #fb f
JOIN dbo.patient_provider_profiles ppp ON ppp.provider_id = f.provider_id AND ppp.is_active = 1
JOIN #pt pt ON pt.patient_id = ppp.patient_id
LEFT JOIN dbo.branch_mrn_sequences sq ON sq.provider_id = f.provider_id AND sq.branch_id = f.branch_id AND sq.sequence_year = @year
WHERE NOT EXISTS (SELECT 1 FROM dbo.patient_branch_profiles x
                  WHERE x.provider_id = f.provider_id AND x.branch_id = f.branch_id AND x.patient_id = ppp.patient_id);

IF EXISTS (SELECT 1 FROM #newbp WHERE n > 999)
    RAISERROR(N'MRN sequence would exceed 999 for a branch.', 16, 1);

INSERT INTO dbo.patient_branch_profiles (id, provider_id, branch_id, patient_id, medical_record_number, is_active, created_at, updated_at)
SELECT CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|branch_profile|', nb.provider_id, N'|', nb.branch_id, N'|', nb.patient_id)), 1, 16) AS uniqueidentifier), nb.provider_id, nb.branch_id, nb.patient_id,
       CONCAT(nb.mrn_code, '-', @year, '-', RIGHT(CONCAT('000', nb.n), 3)), 1, SYSDATETIMEOFFSET(), SYSDATETIMEOFFSET()
FROM #newbp nb;

UPDATE sq SET last_number = m.maxn, updated_at = SYSDATETIMEOFFSET()
FROM dbo.branch_mrn_sequences sq
JOIN (SELECT provider_id, branch_id, MAX(n) AS maxn FROM #newbp GROUP BY provider_id, branch_id) m
  ON m.provider_id = sq.provider_id AND m.branch_id = sq.branch_id
WHERE sq.sequence_year = @year;

INSERT INTO dbo.branch_mrn_sequences (provider_id, branch_id, sequence_year, last_number, updated_at)
SELECT m.provider_id, m.branch_id, @year, m.maxn, SYSDATETIMEOFFSET()
FROM (SELECT provider_id, branch_id, MAX(n) AS maxn FROM #newbp GROUP BY provider_id, branch_id) m
WHERE NOT EXISTS (SELECT 1 FROM dbo.branch_mrn_sequences sq
                  WHERE sq.provider_id = m.provider_id AND sq.branch_id = m.branch_id AND sq.sequence_year = @year);

/* ============ C. TWO HISTORICAL VISITS PER PROFILE (new providers) ============ */
SELECT d.provider_id, d.id AS doctor_id, db.branch_id,
       ROW_NUMBER() OVER (PARTITION BY d.provider_id ORDER BY d.license_number) - 1 AS di,
       COUNT(*) OVER (PARTITION BY d.provider_id) AS dcnt
INTO #dpool
FROM dbo.doctors d
JOIN dbo.doctor_branches db ON db.doctor_id = d.id AND db.is_primary = 1 AND db.is_active = 1
JOIN #np np ON np.provider_id = d.provider_id
WHERE d.is_active = 1;

SELECT ppp.patient_id, np.provider_id, np.tenant_key, np.org_type,
       DENSE_RANK() OVER (PARTITION BY np.provider_id ORDER BY pt.r) AS rp,
       v.v
INTO #vbase
FROM dbo.patient_provider_profiles ppp
JOIN #np np ON np.provider_id = ppp.provider_id
JOIN #pt pt ON pt.patient_id = ppp.patient_id
CROSS JOIN (VALUES (1), (2)) v(v)
WHERE ppp.is_active = 1;

CREATE TABLE #pref (
    tenant_key varchar(100) COLLATE DATABASE_DEFAULT,
    v int,
    code varchar(50) COLLATE DATABASE_DEFAULT
);
INSERT INTO #pref VALUES ('lab-002', 1, 'CBC'), ('lab-002', 2, 'CBC'), ('lab-003', 1, 'CHEST_XRAY'), ('lab-003', 2, 'ULTRASOUND_ABD');

SELECT vb.patient_id, vb.provider_id, vb.tenant_key, vb.org_type, vb.rp, vb.v,
       dp.doctor_id, dp.branch_id, sv.service_id,
       vd.visit_date,
       CAST(DATEADD(minute, vd.start_min, CAST('00:00' AS time(0))) AS time(0)) AS start_time,
       CAST(DATEADD(minute, vd.start_min + 30, CAST('00:00' AS time(0))) AS time(0)) AS end_time,
       TODATETIMEOFFSET(DATEADD(minute, vd.start_min, CAST(vd.visit_date AS datetime2(0))), '+00:00') AS ts,
       CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|appt|', vb.patient_id, N'|', vb.provider_id, N'|', vb.v)), 1, 16) AS uniqueidentifier) AS appointment_id,
       CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|slot|', vb.patient_id, N'|', vb.provider_id, N'|', vb.v)), 1, 16) AS uniqueidentifier) AS slot_id,
       CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|encounter|', vb.patient_id, N'|', vb.provider_id, N'|', vb.v)), 1, 16) AS uniqueidentifier) AS encounter_id
INTO #visit
FROM #vbase vb
JOIN #dpool dp ON dp.provider_id = vb.provider_id AND dp.di = (vb.rp + vb.v) % dp.dcnt
CROSS APPLY (SELECT TOP 1 s.id AS service_id
             FROM dbo.doctor_services ds
             JOIN dbo.services s ON s.id = ds.service_id
             LEFT JOIN #pref pf
                ON pf.tenant_key COLLATE DATABASE_DEFAULT = vb.tenant_key COLLATE DATABASE_DEFAULT
               AND pf.v = vb.v
             WHERE ds.doctor_id = dp.doctor_id AND ds.is_active = 1 AND s.is_active = 1
             ORDER BY CASE WHEN pf.code COLLATE DATABASE_DEFAULT = s.code COLLATE DATABASE_DEFAULT THEN 0
                           WHEN s.service_type = CASE vb.v WHEN 2 THEN 'follow_up' ELSE 'consultation' END THEN 1
                           WHEN s.service_type = 'consultation' THEN 2
                           ELSE 3 END,
                      s.code) sv
CROSS APPLY (SELECT DATEADD(day, -(CASE vb.v WHEN 1 THEN 75 ELSE 25 END) - CAST(vb.rp % 5 AS int), @today) AS visit_date,
                    480 + 30 * CAST(vb.rp % 16 AS int) AS start_min) vd;

INSERT INTO dbo.doctor_availability_slots (id, provider_id, doctor_id, branch_id, working_hours_id, slot_date, start_time, end_time,
                                           status, hold_expires_at, hold_reference, is_waitlist_fill, created_at, updated_at)
SELECT v.slot_id, v.provider_id, v.doctor_id, v.branch_id, NULL, v.visit_date, v.start_time, v.end_time,
       'booked', NULL, NULL, 0, DATEADD(day, -3, v.ts), DATEADD(day, -3, v.ts)
FROM #visit v
WHERE NOT EXISTS (SELECT 1 FROM dbo.doctor_availability_slots x WHERE x.id = v.slot_id);

INSERT INTO dbo.appointments (id, provider_id, appointment_reference, patient_id, patient_name, phone, slot_id, doctor_id, branch_id, service_id,
                              scheduled_date, start_time, end_time, channel, status, notes, cancellation_reason,
                              confirmed_at, cancelled_at, created_at, updated_at, created_by_type, created_by_reference, reschedule_count)
SELECT v.appointment_id, v.provider_id,
       CONCAT('APT-SEED-', UPPER(LEFT(REPLACE(CONVERT(varchar(36), v.appointment_id), '-', ''), 12))),
       v.patient_id, pa.full_name_ar, pa.phone, v.slot_id, v.doctor_id, v.branch_id, v.service_id,
       v.visit_date, v.start_time, v.end_time, 'staff', 'completed', NULL, NULL,
       DATEADD(day, -3, v.ts), NULL, DATEADD(day, -3, v.ts), DATEADD(minute, 30, v.ts), 'staff', 'seed', 0
FROM #visit v
JOIN dbo.patients pa ON pa.id = v.patient_id
WHERE NOT EXISTS (SELECT 1 FROM dbo.appointments x WHERE x.id = v.appointment_id);

INSERT INTO dbo.appointment_status_history (id, provider_id, appointment_id, event_type, previous_status, new_status,
                                            old_slot_id, new_slot_id, changed_by, actor_reference, reason, changed_at)
SELECT CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|history_created|', v.appointment_id)), 1, 16) AS uniqueidentifier), v.provider_id, v.appointment_id, 'created', NULL, 'confirmed',
       NULL, v.slot_id, 'staff', 'seed', NULL, DATEADD(day, -3, v.ts)
FROM #visit v
WHERE NOT EXISTS (SELECT 1 FROM dbo.appointment_status_history h WHERE h.appointment_id = v.appointment_id AND h.event_type = 'created');

INSERT INTO dbo.appointment_status_history (id, provider_id, appointment_id, event_type, previous_status, new_status,
                                            old_slot_id, new_slot_id, changed_by, actor_reference, reason, changed_at)
SELECT CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|history_completed|', v.appointment_id)), 1, 16) AS uniqueidentifier), v.provider_id, v.appointment_id, 'completed', 'confirmed', 'completed',
       NULL, NULL, 'staff', 'seed', NULL, DATEADD(minute, 30, v.ts)
FROM #visit v
WHERE NOT EXISTS (SELECT 1 FROM dbo.appointment_status_history h WHERE h.appointment_id = v.appointment_id AND h.event_type = 'completed');

INSERT INTO dbo.ehr_encounters (id, patient_id, provider_id, doctor_id, branch_id, appointment_id, encounter_type, status,
                                started_at, ended_at, created_at, updated_at)
SELECT v.encounter_id, v.patient_id, v.provider_id, v.doctor_id, v.branch_id, v.appointment_id,
       CASE WHEN v.org_type IN ('hospital','clinic') THEN 'outpatient_visit' ELSE 'diagnostic_test' END, 'closed',
       v.ts, DATEADD(minute, 30, v.ts), v.ts, DATEADD(minute, 30, v.ts)
FROM #visit v
WHERE NOT EXISTS (SELECT 1 FROM dbo.ehr_encounters x WHERE x.id = v.encounter_id);

/* ============ D. ONE PAST ENCOUNTER PER PATIENT AT hospital-001 AND clinic-001 ============ */
INSERT INTO dbo.ehr_encounters (id, patient_id, provider_id, doctor_id, branch_id, appointment_id, encounter_type, status,
                                started_at, ended_at, created_at, updated_at)
SELECT CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|encounter_existing|', ppp.patient_id, N'|', p.id)), 1, 16) AS uniqueidentifier), ppp.patient_id, p.id, dd.doctor_id, dd.branch_id, NULL, 'outpatient_visit', 'closed',
       TODATETIMEOFFSET(DATEADD(day, -30, CAST(@today AS datetime2(0))), '+00:00'),
       TODATETIMEOFFSET(DATEADD(minute, 30, DATEADD(day, -30, CAST(@today AS datetime2(0)))), '+00:00'),
       SYSDATETIMEOFFSET(), SYSDATETIMEOFFSET()
FROM dbo.patient_provider_profiles ppp
JOIN dbo.providers p ON p.id = ppp.provider_id AND p.tenant_key IN ('hospital-001', 'clinic-001')
CROSS APPLY (SELECT TOP 1 d.id AS doctor_id, db.branch_id
             FROM dbo.doctors d
             LEFT JOIN dbo.doctor_branches db ON db.doctor_id = d.id AND db.is_primary = 1 AND db.is_active = 1
             WHERE d.provider_id = p.id AND d.is_active = 1
             ORDER BY d.license_number, d.id) dd
WHERE ppp.is_active = 1
  AND NOT EXISTS (SELECT 1 FROM dbo.ehr_encounters x
                  WHERE x.patient_id = ppp.patient_id AND x.provider_id = p.id AND x.encounter_type = 'outpatient_visit');

/* ============ E. CLINICAL DATA (hospital / clinic outpatient encounters) ============ */
CREATE TABLE #clin (
    id int,
    condition_name nvarchar(200) COLLATE DATABASE_DEFAULT,
    icd10 varchar(10) COLLATE DATABASE_DEFAULT,
    severity varchar(20) COLLATE DATABASE_DEFAULT,
    med nvarchar(200) COLLATE DATABASE_DEFAULT,
    dose nvarchar(100) COLLATE DATABASE_DEFAULT,
    freq nvarchar(100) COLLATE DATABASE_DEFAULT,
    route varchar(30) COLLATE DATABASE_DEFAULT
);
INSERT INTO #clin VALUES
 (1, N'Type 2 diabetes mellitus', 'E11.9',   'moderate', N'Metformin',     N'500 mg',          N'Twice daily with meals', 'oral'),
 (2, N'Essential hypertension',   'I10',     'moderate', N'Amlodipine',    N'5 mg',            N'Once daily',             'oral'),
 (3, N'Asthma',                   'J45.909', 'mild',     N'Salbutamol',    N'100 mcg/dose',    N'As needed',              'inhalation'),
 (4, N'Hypothyroidism',           'E03.9',   'mild',     N'Levothyroxine', N'50 mcg',          N'Once daily, morning',    'oral'),
 (5, N'Gastro-esophageal reflux disease', 'K21.9', 'mild', N'Omeprazole',  N'20 mg',           N'Once daily before breakfast', 'oral'),
 (6, N'Hyperlipidemia',           'E78.5',   'moderate', N'Atorvastatin',  N'20 mg',           N'Once daily at night',    'oral'),
 (7, N'Iron deficiency anemia',   'D50.9',   'mild',     N'Ferrous sulfate', N'200 mg',        N'Once daily',             'oral'),
 (8, N'Migraine',                 'G43.909', 'mild',     N'Paracetamol',   N'500 mg',          N'As needed, max 3 g/day', 'oral');

CREATE TABLE #allg (
    id int,
    allergen nvarchar(200) COLLATE DATABASE_DEFAULT,
    allergen_type varchar(20) COLLATE DATABASE_DEFAULT,
    reaction nvarchar(300) COLLATE DATABASE_DEFAULT,
    severity varchar(20) COLLATE DATABASE_DEFAULT
);
INSERT INTO #allg VALUES
 (1, N'Penicillin',  'drug',          N'Skin rash',            'moderate'),
 (2, N'Sulfonamides','drug',          N'Hives',                'moderate'),
 (3, N'Peanuts',     'food',          N'Swelling and wheezing','severe'),
 (4, N'Dust mites',  'environmental', N'Sneezing, itchy eyes', 'mild'),
 (5, N'Shellfish',   'food',          N'Vomiting',             'moderate');

SELECT e.id AS encounter_id, e.patient_id, e.provider_id, e.doctor_id, e.started_at,
       ROW_NUMBER() OVER (PARTITION BY e.patient_id, e.provider_id ORDER BY e.started_at, e.id) AS vn,
       hh.h AS h,
       (hh.h % 8) + 1 AS a_id,
       ((hh.h % 8) + 1 + ((hh.h / 8) % 7)) % 8 + 1 AS b_id
INTO #e
FROM dbo.ehr_encounters e
JOIN dbo.providers p ON p.id = e.provider_id
CROSS APPLY (SELECT (CHECKSUM(e.patient_id) & 2147483647) AS h) hh
WHERE e.encounter_type = 'outpatient_visit'
  AND p.org_type IN ('hospital', 'clinic')
  AND e.doctor_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM dbo.patient_provider_profiles ppp WHERE ppp.patient_id = e.patient_id AND ppp.provider_id = e.provider_id);

/* conditions + medications: attached to each patient's first visit at the provider */
SELECT CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|condition|', e.encounter_id, N'|', x.slot)), 1, 16) AS uniqueidentifier) AS id, e.provider_id, e.patient_id, e.encounter_id, e.doctor_id,
       c.condition_name, c.icd10, c.severity, c.med, c.dose, c.freq, c.route,
       DATEADD(year, -(1 + ((e.h / 64) + x.slot) % 6), @today) AS onset_date,
       e.started_at
INTO #condrows
FROM #e e
CROSS APPLY (VALUES (0, e.a_id), (1, e.b_id)) x(slot, clin_id)
JOIN #clin c ON c.id = x.clin_id
WHERE e.vn = 1;

INSERT INTO dbo.patient_conditions (id, provider_id, patient_id, encounter_id, recorded_by_doctor_id, condition_name, icd10_code,
                                    clinical_status, severity, onset_date, resolved_date, notes, created_at, updated_at)
SELECT r.id, r.provider_id, r.patient_id, r.encounter_id, r.doctor_id, r.condition_name, r.icd10,
       'active', r.severity, r.onset_date, NULL, NULL, r.started_at, r.started_at
FROM #condrows r
WHERE NOT EXISTS (SELECT 1 FROM dbo.patient_conditions z WHERE z.id = r.id);

INSERT INTO dbo.patient_medications (id, provider_id, patient_id, encounter_id, prescribed_by_doctor_id, medication_name, dosage, frequency, route,
                                     start_date, end_date, status, notes, created_at, updated_at)
SELECT CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|medication|', r.encounter_id, N'|', r.id)), 1, 16) AS uniqueidentifier), r.provider_id, r.patient_id, r.encounter_id, r.doctor_id, r.med, r.dose, r.freq, r.route,
       r.onset_date, NULL, 'active', NULL, r.started_at, r.started_at
FROM #condrows r
WHERE NOT EXISTS (SELECT 1 FROM dbo.patient_medications z WHERE z.id = CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|medication|', r.encounter_id, N'|', r.id)), 1, 16) AS uniqueidentifier));

/* allergies: about two thirds of patients have one recorded */
SELECT CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|allergy|', e.encounter_id)), 1, 16) AS uniqueidentifier) AS id, e.provider_id, e.patient_id, e.encounter_id, e.doctor_id,
       a.allergen, a.allergen_type, a.reaction, a.severity,
       CAST(e.started_at AS date) AS noted_date, e.started_at
INTO #allrows
FROM #e e
JOIN #allg a ON a.id = ((e.h / 3) % 5) + 1
WHERE e.vn = 1 AND (e.h % 3) <> 0;

INSERT INTO dbo.patient_allergies (id, provider_id, patient_id, encounter_id, recorded_by_doctor_id, allergen, allergen_type, reaction,
                                   severity, status, noted_date, created_at, updated_at)
SELECT r.id, r.provider_id, r.patient_id, r.encounter_id, r.doctor_id, r.allergen, r.allergen_type, r.reaction,
       r.severity, 'active', r.noted_date, r.started_at, r.started_at
FROM #allrows r
WHERE NOT EXISTS (SELECT 1 FROM dbo.patient_allergies z WHERE z.id = r.id);

/* clinical notes: one signed note per outpatient encounter */
INSERT INTO dbo.clinical_notes (id, provider_id, patient_id, encounter_id, doctor_id, note_type, title, note_text,
                                status, signed_at, addendum_to_note_id, created_at, updated_at)
SELECT CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|note|', e.encounter_id)), 1, 16) AS uniqueidentifier), e.provider_id, e.patient_id, e.encounter_id, e.doctor_id, 'progress',
       CASE WHEN e.vn = 1 THEN N'Initial consultation' ELSE N'Follow-up visit' END,
       CASE WHEN e.vn = 1 THEN
            CONCAT(N'Subjective: Patient presents for initial evaluation. History of ', ca.condition_name, N'. Currently taking ',
                   ca.med, N' ', ca.dose, N' (', ca.freq, N').', CHAR(10),
                   N'Objective: Vital signs within normal limits. No acute distress.', CHAR(10),
                   N'Assessment: ', ca.condition_name, N', stable on current therapy.', CHAR(10),
                   N'Plan: Continue current medication, routine laboratory monitoring, follow-up in 4 to 6 weeks.')
       ELSE
            CONCAT(N'Subjective: Follow-up visit. Reports good adherence to ', ca.med, N' with no new complaints.', CHAR(10),
                   N'Objective: Vital signs stable. Examination unremarkable.', CHAR(10),
                   N'Assessment: ', ca.condition_name, N', well controlled.', CHAR(10),
                   N'Plan: Continue ', ca.med, N' ', ca.dose, N'. Review in 3 months or earlier if symptoms change.')
       END,
       'signed', DATEADD(minute, 40, e.started_at), NULL, e.started_at, DATEADD(minute, 40, e.started_at)
FROM #e e
JOIN #clin ca ON ca.id = e.a_id
WHERE NOT EXISTS (SELECT 1 FROM dbo.clinical_notes z WHERE z.id = CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|note|', e.encounter_id)), 1, 16) AS uniqueidentifier));

/* ============ F. HISTORICAL CBC REPORTS AT lab-002 ============ */
SELECT e.id AS encounter_id, e.patient_id, e.provider_id, e.started_at
INTO #labenc
FROM dbo.ehr_encounters e
JOIN dbo.providers p     ON p.id = e.provider_id AND p.tenant_key = 'lab-002'
JOIN dbo.appointments a  ON a.id = e.appointment_id AND a.created_by_reference = 'seed'
JOIN dbo.services s      ON s.id = a.service_id AND s.code = 'CBC';

INSERT INTO dbo.diagnostic_attachments (id, attachment_id, provider_id, patient_id, encounter_id, session_id, original_filename,
                                        content_type, size_bytes, sha256, storage_key, status, created_at, updated_at)
SELECT CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|attachment|', le.encounter_id)), 1, 16) AS uniqueidentifier),
       LOWER(CONVERT(varchar(32), SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|attachment_ref|', le.encounter_id)), 1, 16), 2)),
       le.provider_id, le.patient_id, le.encounter_id,
       CONCAT('seed-', LOWER(CONVERT(varchar(12), SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|session|', le.encounter_id)), 1, 6), 2))),
       N'cbc_report_seed.png', 'image/png', 0,
       LOWER(CONVERT(varchar(64), HASHBYTES('SHA2_256', CONCAT(N'seed|file|', le.encounter_id)), 2)),
       CONCAT(N'seed/', LOWER(CONVERT(varchar(32), SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|attachment_ref|', le.encounter_id)), 1, 16), 2)), N'.png'),
       'stored', le.started_at, le.started_at
FROM #labenc le
WHERE NOT EXISTS (SELECT 1 FROM dbo.diagnostic_attachments z WHERE z.id = CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|attachment|', le.encounter_id)), 1, 16) AS uniqueidentifier));

INSERT INTO dbo.lab_reports (id, patient_id, provider_id, encounter_id, diagnostic_attachment_id, document_type,
                             unreadable_fields_json, status, created_at, updated_at)
SELECT CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|lab_report|', le.encounter_id)), 1, 16) AS uniqueidentifier), le.patient_id, le.provider_id, le.encounter_id, CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|attachment|', le.encounter_id)), 1, 16) AS uniqueidentifier),
       'cbc', '[]', 'processed', le.started_at, DATEADD(minute, 20, le.started_at)
FROM #labenc le
WHERE NOT EXISTS (SELECT 1 FROM dbo.lab_reports z WHERE z.id = CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|lab_report|', le.encounter_id)), 1, 16) AS uniqueidentifier));

CREATE TABLE #cbc (
    idx int,
    raw_name nvarchar(200) COLLATE DATABASE_DEFAULT,
    canonical varchar(100) COLLATE DATABASE_DEFAULT,
    unit nvarchar(50) COLLATE DATABASE_DEFAULT,
    rmin numeric(18,6),
    rmax numeric(18,6),
    rtext nvarchar(200) COLLATE DATABASE_DEFAULT
);
INSERT INTO #cbc VALUES
 (0, N'Hemoglobin', 'hemoglobin', N'g/dL',     11.0, 16.0,  N'11.0 - 16.0'),
 (1, N'WBC',        'wbc',        N'10^3/uL',  4.0,  11.0,  N'4.0 - 11.0'),
 (2, N'PLT',        'platelets',  N'10^3/uL',  150,  450,   N'150-450'),
 (3, N'RBC',        'rbc',        N'10^6/uL',  3.5,  5.5,   N'3.5-5.5'),
 (4, N'HCT',        'hematocrit', N'%',        37.0, 50.0,  N'37.0-50.0'),
 (5, N'MCV',        'mcv',        N'fl',       82,   95,    N'82-95'),
 (6, N'MCH',        'mch',        N'pg',       27,   31,    N'27-31'),
 (7, N'MCHC',       'mchc',       N'g/dL',     32.0, 36.0,  N'32.0-36.0');

SELECT CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|lab_result|', le.encounter_id, N'|', t.idx)), 1, 16) AS uniqueidentifier) AS id, CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|lab_report|', le.encounter_id)), 1, 16) AS uniqueidentifier) AS lab_report_id, t.idx, t.raw_name, t.canonical, t.unit,
       t.rmin, t.rmax, t.rtext, x.val, le.started_at
INTO #labres
FROM #labenc le
CROSS JOIN #cbc t
CROSS APPLY (SELECT CAST(ROUND(t.rmin + (t.rmax - t.rmin) * (1.2 * (((CHECKSUM(le.encounter_id, t.idx) & 2147483647) % 100) / 100.0) - 0.1), 2) AS numeric(18,6)) AS val) x;

INSERT INTO dbo.lab_results (id, lab_report_id, result_index, panel, raw_name, canonical_name, value, unit,
                             reference_min, reference_max, reference_text, flag, mapping_status, created_at)
SELECT r.id, r.lab_report_id, r.idx, 'cbc', r.raw_name, r.canonical, r.val, r.unit,
       r.rmin, r.rmax, r.rtext,
       CASE WHEN r.val < r.rmin THEN 'low' WHEN r.val > r.rmax THEN 'high' ELSE 'normal' END,
       'mapped', DATEADD(minute, 20, r.started_at)
FROM #labres r
WHERE NOT EXISTS (SELECT 1 FROM dbo.lab_results z WHERE z.id = r.id);

/* ============ G. SAMPLE CROSS-PROVIDER ACCESS GRANTS ============ */
SELECT a.patient_id, a.provider_id AS owner_provider_id, b.provider_id AS grantee_provider_id,
       ROW_NUMBER() OVER (ORDER BY a.patient_id, pa.tenant_key, pb.tenant_key) AS rn
INTO #gr
FROM dbo.patient_provider_profiles a
JOIN dbo.patient_provider_profiles b ON b.patient_id = a.patient_id AND b.provider_id <> a.provider_id
JOIN dbo.providers pa ON pa.id = a.provider_id
JOIN dbo.providers pb ON pb.id = b.provider_id
WHERE pa.tenant_key IN ('hospital-002','hospital-003','clinic-002','clinic-003','lab-002','lab-003')
  AND pb.tenant_key IN ('hospital-002','hospital-003','clinic-002','clinic-003','lab-002','lab-003')
  AND pa.org_type IN ('hospital', 'clinic')
  AND pa.tenant_key < pb.tenant_key;

INSERT INTO dbo.patient_access_grants (id, patient_id, owner_provider_id, grantee_provider_id, scope, granted_by,
                                       granted_at, expires_at, revoked_at, revoked_reason, created_at)
SELECT CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|grant|', g.patient_id, N'|', g.owner_provider_id, N'|', g.grantee_provider_id)), 1, 16) AS uniqueidentifier),
       g.patient_id, g.owner_provider_id, g.grantee_provider_id,
       CASE WHEN g.rn % 3 = 0 THEN 'reports_only' ELSE 'full_record' END, 'patient',
       DATEADD(day, -30, SYSUTCDATETIME()),
       CASE WHEN g.rn BETWEEN 11 AND 12 THEN DATEADD(day, -1, SYSUTCDATETIME()) ELSE NULL END,
       CASE WHEN g.rn BETWEEN 9 AND 10 THEN DATEADD(day, -5, SYSUTCDATETIME()) ELSE NULL END,
       CASE WHEN g.rn BETWEEN 9 AND 10 THEN N'Revoked by patient' ELSE NULL END,
       DATEADD(day, -30, SYSUTCDATETIME())
FROM #gr g
WHERE g.rn <= 12
  AND NOT EXISTS (SELECT 1 FROM dbo.patient_access_grants z
                  WHERE z.patient_id = g.patient_id AND z.owner_provider_id = g.owner_provider_id
                    AND z.grantee_provider_id = g.grantee_provider_id AND z.revoked_at IS NULL
                    AND z.scope = CASE WHEN g.rn % 3 = 0 THEN 'reports_only' ELSE 'full_record' END)
  AND NOT EXISTS (SELECT 1 FROM dbo.patient_access_grants z
                  WHERE z.id = CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|grant|', g.patient_id, N'|', g.owner_provider_id, N'|', g.grantee_provider_id)), 1, 16) AS uniqueidentifier));

/* ============ SUMMARY (visible on dry run too) ============ */
PRINT N'--- Row counts after this script ---';
SELECT N'user_accounts' AS item, COUNT(*) AS total FROM dbo.user_accounts
UNION ALL SELECT N'provider_memberships', COUNT(*) FROM dbo.provider_memberships
UNION ALL SELECT N'patient_provider_profiles', COUNT(*) FROM dbo.patient_provider_profiles
UNION ALL SELECT N'patient_branch_profiles', COUNT(*) FROM dbo.patient_branch_profiles
UNION ALL SELECT N'appointments (seed)', COUNT(*) FROM dbo.appointments WHERE created_by_reference = 'seed'
UNION ALL SELECT N'ehr_encounters', COUNT(*) FROM dbo.ehr_encounters
UNION ALL SELECT N'patient_conditions', COUNT(*) FROM dbo.patient_conditions
UNION ALL SELECT N'patient_medications', COUNT(*) FROM dbo.patient_medications
UNION ALL SELECT N'patient_allergies', COUNT(*) FROM dbo.patient_allergies
UNION ALL SELECT N'clinical_notes', COUNT(*) FROM dbo.clinical_notes
UNION ALL SELECT N'lab_reports', COUNT(*) FROM dbo.lab_reports
UNION ALL SELECT N'lab_results', COUNT(*) FROM dbo.lab_results
UNION ALL SELECT N'patient_access_grants', COUNT(*) FROM dbo.patient_access_grants;

PRINT N'--- Staff logins created (password: MedMind#Demo2026) ---';
SELECT p.tenant_key, m.role, u.email
FROM dbo.provider_memberships m
JOIN dbo.user_accounts u ON u.id = m.user_id
JOIN dbo.providers p ON p.id = m.provider_id
WHERE m.role <> 'doctor'
ORDER BY p.tenant_key, m.role;

IF @commit = 1
BEGIN
    COMMIT TRANSACTION;
    PRINT N'COMMITTED. Staff, patients, visits and EHR data were saved.';
END
ELSE
BEGIN
    ROLLBACK TRANSACTION;
    PRINT N'DRY RUN: everything was rolled back. Set @commit = 1 to keep the data.';
END
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
SET NOEXEC OFF;
GO
