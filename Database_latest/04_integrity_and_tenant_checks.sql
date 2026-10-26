/* =====================================================================
   MedMind - Sprint "Database Completion"  |  Script 04: Integrity + tenant separation
   READ-ONLY. Every check returns the number of violating rows; a healthy
   database shows 0 for every row marked FAIL.  WARN rows are data-quality
   notes (e.g. diagnostic reports not yet linked to a patient).
   Run after scripts 01-03, and again on the restored copy in script 05.
   ===================================================================== */
IF DB_ID() <= 4 OR OBJECT_ID(N'dbo.providers', N'U') IS NULL
BEGIN
    RAISERROR(N'Select the MedMind database first.', 16, 1);
    SET NOEXEC ON;
END
GO
SET NOCOUNT ON;
DROP TABLE IF EXISTS #r;
CREATE TABLE #r (id int IDENTITY(1,1), area varchar(30), check_name varchar(200), severity varchar(4), violations int);

/* helper pattern: INSERT INTO #r SELECT area, name, severity, COUNT(*) FROM (violating rows) v */

/* ---------- TENANT SEPARATION: every child row must live in the same provider as its parents ---------- */
INSERT INTO #r (area, check_name, severity, violations)
SELECT 'tenant','appointments: doctor from another provider','FAIL',(SELECT COUNT(*) FROM dbo.appointments a JOIN dbo.doctors d ON d.id=a.doctor_id WHERE d.provider_id<>a.provider_id)
UNION ALL SELECT 'tenant','appointments: branch from another provider','FAIL',(SELECT COUNT(*) FROM dbo.appointments a JOIN dbo.branches b ON b.id=a.branch_id WHERE b.provider_id<>a.provider_id)
UNION ALL SELECT 'tenant','appointments: slot from another provider','FAIL',(SELECT COUNT(*) FROM dbo.appointments a JOIN dbo.doctor_availability_slots s ON s.id=a.slot_id WHERE s.provider_id<>a.provider_id)
UNION ALL SELECT 'tenant','appointments: service from another provider','FAIL',(SELECT COUNT(*) FROM dbo.appointments a JOIN dbo.services s ON s.id=a.service_id WHERE s.provider_id<>a.provider_id)
UNION ALL SELECT 'tenant','appointments: slot doctor/date/time differs from appointment','FAIL',(SELECT COUNT(*) FROM dbo.appointments a JOIN dbo.doctor_availability_slots s ON s.id=a.slot_id WHERE s.doctor_id<>a.doctor_id OR s.slot_date<>a.scheduled_date OR s.start_time<>a.start_time)
UNION ALL SELECT 'tenant','appointments: patient has no profile at the provider','WARN',(SELECT COUNT(*) FROM dbo.appointments a WHERE NOT EXISTS (SELECT 1 FROM dbo.patient_provider_profiles p WHERE p.patient_id=a.patient_id AND p.provider_id=a.provider_id))
UNION ALL SELECT 'tenant','slots: doctor from another provider','FAIL',(SELECT COUNT(*) FROM dbo.doctor_availability_slots s JOIN dbo.doctors d ON d.id=s.doctor_id WHERE d.provider_id<>s.provider_id)
UNION ALL SELECT 'tenant','slots: branch from another provider','FAIL',(SELECT COUNT(*) FROM dbo.doctor_availability_slots s JOIN dbo.branches b ON b.id=s.branch_id WHERE b.provider_id<>s.provider_id)
UNION ALL SELECT 'tenant','doctor_branches: cross-provider link','FAIL',(SELECT COUNT(*) FROM dbo.doctor_branches x JOIN dbo.doctors d ON d.id=x.doctor_id JOIN dbo.branches b ON b.id=x.branch_id WHERE d.provider_id<>x.provider_id OR b.provider_id<>x.provider_id)
UNION ALL SELECT 'tenant','doctor_services: cross-provider link','FAIL',(SELECT COUNT(*) FROM dbo.doctor_services x JOIN dbo.doctors d ON d.id=x.doctor_id JOIN dbo.services s ON s.id=x.service_id WHERE d.provider_id<>x.provider_id OR s.provider_id<>x.provider_id)
UNION ALL SELECT 'tenant','service_specialties: cross-provider link','FAIL',(SELECT COUNT(*) FROM dbo.service_specialties x JOIN dbo.services s ON s.id=x.service_id JOIN dbo.specialties sp ON sp.id=x.specialty_id WHERE s.provider_id<>x.provider_id OR sp.provider_id<>x.provider_id)
UNION ALL SELECT 'tenant','doctors: specialty from another provider','FAIL',(SELECT COUNT(*) FROM dbo.doctors d JOIN dbo.specialties sp ON sp.id=d.specialty_id WHERE sp.provider_id<>d.provider_id)
UNION ALL SELECT 'tenant','working_hours: cross-provider link','FAIL',(SELECT COUNT(*) FROM dbo.doctor_working_hours w JOIN dbo.doctors d ON d.id=w.doctor_id JOIN dbo.branches b ON b.id=w.branch_id WHERE d.provider_id<>w.provider_id OR b.provider_id<>w.provider_id)
UNION ALL SELECT 'tenant','branch profiles: branch from another provider','FAIL',(SELECT COUNT(*) FROM dbo.patient_branch_profiles x JOIN dbo.branches b ON b.id=x.branch_id WHERE b.provider_id<>x.provider_id)
UNION ALL SELECT 'tenant','branch profiles: patient has no provider profile','FAIL',(SELECT COUNT(*) FROM dbo.patient_branch_profiles x WHERE NOT EXISTS (SELECT 1 FROM dbo.patient_provider_profiles p WHERE p.patient_id=x.patient_id AND p.provider_id=x.provider_id))
UNION ALL SELECT 'tenant','memberships: doctor belongs to another provider','FAIL',(SELECT COUNT(*) FROM dbo.provider_memberships m JOIN dbo.doctors d ON d.id=m.doctor_id WHERE d.provider_id<>m.provider_id)
UNION ALL SELECT 'tenant','reminders: appointment from another provider','FAIL',(SELECT COUNT(*) FROM dbo.reminders r JOIN dbo.appointments a ON a.id=r.appointment_id WHERE a.provider_id<>r.provider_id)
UNION ALL SELECT 'tenant','status history: appointment from another provider','FAIL',(SELECT COUNT(*) FROM dbo.appointment_status_history h JOIN dbo.appointments a ON a.id=h.appointment_id WHERE a.provider_id<>h.provider_id);

/* ---------- EHR LINKS: patient / provider / doctor / encounter must agree ---------- */
INSERT INTO #r (area, check_name, severity, violations)
SELECT 'ehr','encounters: doctor from another provider','FAIL',(SELECT COUNT(*) FROM dbo.ehr_encounters e JOIN dbo.doctors d ON d.id=e.doctor_id WHERE d.provider_id<>e.provider_id)
UNION ALL SELECT 'ehr','encounters: branch from another provider','FAIL',(SELECT COUNT(*) FROM dbo.ehr_encounters e JOIN dbo.branches b ON b.id=e.branch_id WHERE b.provider_id<>e.provider_id)
UNION ALL SELECT 'ehr','encounters: appointment missing or from another provider','FAIL',(SELECT COUNT(*) FROM dbo.ehr_encounters e WHERE e.appointment_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dbo.appointments a WHERE a.id=e.appointment_id AND a.provider_id=e.provider_id))
UNION ALL SELECT 'ehr','encounters: appointment belongs to a different patient','FAIL',(SELECT COUNT(*) FROM dbo.ehr_encounters e JOIN dbo.appointments a ON a.id=e.appointment_id WHERE a.patient_id<>e.patient_id)
UNION ALL SELECT 'ehr','encounters: appointment has a different doctor','WARN',(SELECT COUNT(*) FROM dbo.ehr_encounters e JOIN dbo.appointments a ON a.id=e.appointment_id WHERE e.doctor_id IS NOT NULL AND a.doctor_id<>e.doctor_id)
UNION ALL SELECT 'ehr','encounters: patient has no profile at the provider','WARN',(SELECT COUNT(*) FROM dbo.ehr_encounters e WHERE NOT EXISTS (SELECT 1 FROM dbo.patient_provider_profiles p WHERE p.patient_id=e.patient_id AND p.provider_id=e.provider_id))
UNION ALL SELECT 'ehr','encounters: ended before it started','FAIL',(SELECT COUNT(*) FROM dbo.ehr_encounters e WHERE e.ended_at IS NOT NULL AND e.ended_at<e.started_at)
UNION ALL SELECT 'ehr','lab_reports: encounter disagrees on provider or patient','FAIL',(SELECT COUNT(*) FROM dbo.lab_reports r JOIN dbo.ehr_encounters e ON e.id=r.encounter_id WHERE e.provider_id<>r.provider_id OR (r.patient_id IS NOT NULL AND e.patient_id<>r.patient_id))
UNION ALL SELECT 'ehr','radiology_reports: encounter disagrees on provider or patient','FAIL',(SELECT COUNT(*) FROM dbo.radiology_reports r JOIN dbo.ehr_encounters e ON e.id=r.encounter_id WHERE e.provider_id<>r.provider_id OR (r.patient_id IS NOT NULL AND e.patient_id<>r.patient_id))
UNION ALL SELECT 'ehr','lab_reports: attachment from another provider/patient','FAIL',(SELECT COUNT(*) FROM dbo.lab_reports r JOIN dbo.diagnostic_attachments a ON a.id=r.diagnostic_attachment_id WHERE a.provider_id<>r.provider_id OR (r.patient_id IS NOT NULL AND a.patient_id IS NOT NULL AND a.patient_id<>r.patient_id))
UNION ALL SELECT 'ehr','radiology_reports: attachment from another provider/patient','FAIL',(SELECT COUNT(*) FROM dbo.radiology_reports r JOIN dbo.diagnostic_attachments a ON a.id=r.diagnostic_attachment_id WHERE a.provider_id<>r.provider_id OR (r.patient_id IS NOT NULL AND a.patient_id IS NOT NULL AND a.patient_id<>r.patient_id))
UNION ALL SELECT 'ehr','lab_reports: encounter set but patient missing','WARN',(SELECT COUNT(*) FROM dbo.lab_reports r WHERE r.encounter_id IS NOT NULL AND r.patient_id IS NULL)
UNION ALL SELECT 'ehr','radiology_reports: encounter set but patient missing','WARN',(SELECT COUNT(*) FROM dbo.radiology_reports r WHERE r.encounter_id IS NOT NULL AND r.patient_id IS NULL)
UNION ALL SELECT 'ehr','lab_reports not linked to any patient (diagnostic uploads)','WARN',(SELECT COUNT(*) FROM dbo.lab_reports r WHERE r.patient_id IS NULL)
UNION ALL SELECT 'ehr','radiology_reports not linked to any patient (diagnostic uploads)','WARN',(SELECT COUNT(*) FROM dbo.radiology_reports r WHERE r.patient_id IS NULL)
UNION ALL SELECT 'ehr','lab_reports without any result rows','WARN',(SELECT COUNT(*) FROM dbo.lab_reports r WHERE r.status='processed' AND NOT EXISTS (SELECT 1 FROM dbo.lab_results x WHERE x.lab_report_id=r.id))
UNION ALL SELECT 'ehr','radiology_reports without an assessment','WARN',(SELECT COUNT(*) FROM dbo.radiology_reports r WHERE r.status='processed' AND NOT EXISTS (SELECT 1 FROM dbo.diagnostic_assessments x WHERE x.radiology_report_id=r.id));

/* ---------- NEW EHR TABLES (skipped automatically if script 01 was not run) ---------- */
IF OBJECT_ID(N'dbo.clinical_notes', N'U') IS NOT NULL
BEGIN
    INSERT INTO #r (area, check_name, severity, violations)
    SELECT 'ehr','patient_conditions: patient not registered at provider','FAIL',COUNT(*) FROM dbo.patient_conditions x WHERE NOT EXISTS (SELECT 1 FROM dbo.patient_provider_profiles p WHERE p.patient_id=x.patient_id AND p.provider_id=x.provider_id)
    UNION ALL SELECT 'ehr','patient_conditions: encounter belongs to another provider/patient','FAIL',COUNT(*) FROM dbo.patient_conditions x JOIN dbo.ehr_encounters e ON e.id=x.encounter_id WHERE e.provider_id<>x.provider_id OR e.patient_id<>x.patient_id
    UNION ALL SELECT 'ehr','patient_allergies: patient not registered at provider','FAIL',COUNT(*) FROM dbo.patient_allergies x WHERE NOT EXISTS (SELECT 1 FROM dbo.patient_provider_profiles p WHERE p.patient_id=x.patient_id AND p.provider_id=x.provider_id)
    UNION ALL SELECT 'ehr','patient_allergies: encounter belongs to another provider/patient','FAIL',COUNT(*) FROM dbo.patient_allergies x JOIN dbo.ehr_encounters e ON e.id=x.encounter_id WHERE e.provider_id<>x.provider_id OR e.patient_id<>x.patient_id
    UNION ALL SELECT 'ehr','patient_medications: patient not registered at provider','FAIL',COUNT(*) FROM dbo.patient_medications x WHERE NOT EXISTS (SELECT 1 FROM dbo.patient_provider_profiles p WHERE p.patient_id=x.patient_id AND p.provider_id=x.provider_id)
    UNION ALL SELECT 'ehr','patient_medications: encounter belongs to another provider/patient','FAIL',COUNT(*) FROM dbo.patient_medications x JOIN dbo.ehr_encounters e ON e.id=x.encounter_id WHERE e.provider_id<>x.provider_id OR e.patient_id<>x.patient_id
    UNION ALL SELECT 'ehr','clinical_notes: encounter belongs to another provider/patient','FAIL',COUNT(*) FROM dbo.clinical_notes x JOIN dbo.ehr_encounters e ON e.id=x.encounter_id WHERE e.provider_id<>x.provider_id OR e.patient_id<>x.patient_id
    UNION ALL SELECT 'ehr','clinical_notes: author is from another provider','FAIL',COUNT(*) FROM dbo.clinical_notes x JOIN dbo.doctors d ON d.id=x.doctor_id WHERE d.provider_id<>x.provider_id
    UNION ALL SELECT 'ehr','clinical_notes: author differs from encounter doctor (addenda may do this legitimately)','WARN',COUNT(*) FROM dbo.clinical_notes x JOIN dbo.ehr_encounters e ON e.id=x.encounter_id WHERE e.doctor_id IS NOT NULL AND e.doctor_id<>x.doctor_id
    UNION ALL SELECT 'ehr','clinical_notes: signed note without signature time','FAIL',COUNT(*) FROM dbo.clinical_notes x WHERE x.status='signed' AND x.signed_at IS NULL
    UNION ALL SELECT 'access','grants: owner has no profile for the patient','FAIL',COUNT(*) FROM dbo.patient_access_grants g WHERE NOT EXISTS (SELECT 1 FROM dbo.patient_provider_profiles p WHERE p.patient_id=g.patient_id AND p.provider_id=g.owner_provider_id)
    UNION ALL SELECT 'access','grants: owner and grantee are the same provider','FAIL',COUNT(*) FROM dbo.patient_access_grants g WHERE g.owner_provider_id=g.grantee_provider_id
    UNION ALL SELECT 'access','grants: expired but not revoked (informational)','WARN',COUNT(*) FROM dbo.patient_access_grants g WHERE g.revoked_at IS NULL AND g.expires_at IS NOT NULL AND g.expires_at<=SYSUTCDATETIME();
END
ELSE
    INSERT INTO #r (area, check_name, severity, violations) VALUES ('ehr','new EHR tables not found (run script 01)','FAIL',1);

/* ---------- STAFF / RBAC DATA ---------- */
INSERT INTO #r (area, check_name, severity, violations)
SELECT 'rbac','active providers with no provider_admin account','FAIL',(SELECT COUNT(*) FROM dbo.providers p WHERE p.is_active=1 AND NOT EXISTS (SELECT 1 FROM dbo.provider_memberships m WHERE m.provider_id=p.id AND m.role='provider_admin' AND m.is_active=1))
UNION ALL SELECT 'rbac','active providers with no receptionist account','WARN',(SELECT COUNT(*) FROM dbo.providers p WHERE p.is_active=1 AND NOT EXISTS (SELECT 1 FROM dbo.provider_memberships m WHERE m.provider_id=p.id AND m.role='receptionist' AND m.is_active=1))
UNION ALL SELECT 'rbac','active doctors with no login membership','WARN',(SELECT COUNT(*) FROM dbo.doctors d WHERE d.is_active=1 AND NOT EXISTS (SELECT 1 FROM dbo.provider_memberships m WHERE m.doctor_id=d.id AND m.role='doctor'))
UNION ALL SELECT 'rbac','memberships whose user account is missing','FAIL',(SELECT COUNT(*) FROM dbo.provider_memberships m WHERE NOT EXISTS (SELECT 1 FROM dbo.user_accounts u WHERE u.id=m.user_id))
UNION ALL SELECT 'rbac','user accounts with no membership','WARN',(SELECT COUNT(*) FROM dbo.user_accounts u WHERE NOT EXISTS (SELECT 1 FROM dbo.provider_memberships m WHERE m.user_id=u.id))
UNION ALL SELECT 'rbac','user accounts without a bcrypt hash','FAIL',(SELECT COUNT(*) FROM dbo.user_accounts u WHERE u.password_hash NOT LIKE '$2%');

/* ---------- SCHEDULING / DATA QUALITY ---------- */
INSERT INTO #r (area, check_name, severity, violations)
SELECT 'booking','slots with more than one active appointment','FAIL',(SELECT COUNT(*) FROM (SELECT slot_id FROM dbo.appointments WHERE status<>'cancelled' GROUP BY slot_id HAVING COUNT(*)>1) x)
UNION ALL SELECT 'booking','active appointment but slot not marked booked','WARN',(SELECT COUNT(*) FROM dbo.appointments a JOIN dbo.doctor_availability_slots s ON s.id=a.slot_id WHERE a.status IN ('pending','confirmed','completed') AND s.status<>'booked')
UNION ALL SELECT 'booking','booked slot without an active appointment','WARN',(SELECT COUNT(*) FROM dbo.doctor_availability_slots s WHERE s.status='booked' AND NOT EXISTS (SELECT 1 FROM dbo.appointments a WHERE a.slot_id=s.id AND a.status<>'cancelled'))
UNION ALL SELECT 'booking','overlapping slots for the same doctor and date','FAIL',(SELECT COUNT(*) FROM dbo.doctor_availability_slots a JOIN dbo.doctor_availability_slots b ON b.doctor_id=a.doctor_id AND b.slot_date=a.slot_date AND b.id<a.id AND b.start_time<a.end_time AND a.start_time<b.end_time WHERE a.status<>'blocked' AND b.status<>'blocked')
UNION ALL SELECT 'booking','branch profiles with duplicate MRN in one branch','FAIL',(SELECT COUNT(*) FROM (SELECT provider_id,branch_id,medical_record_number FROM dbo.patient_branch_profiles GROUP BY provider_id,branch_id,medical_record_number HAVING COUNT(*)>1) x)
UNION ALL SELECT 'booking','MRN sequence lower than highest issued number','FAIL',(SELECT COUNT(*) FROM dbo.branch_mrn_sequences s WHERE s.last_number < ISNULL((SELECT MAX(TRY_CAST(RIGHT(b.medical_record_number,3) AS int)) FROM dbo.patient_branch_profiles b WHERE b.provider_id=s.provider_id AND b.branch_id=s.branch_id AND b.medical_record_number LIKE '%-'+CAST(s.sequence_year AS varchar(4))+'-%'),0))
UNION ALL SELECT 'quality','patients with duplicate national_id_hash','FAIL',(SELECT COUNT(*) FROM (SELECT national_id_hash FROM dbo.patients GROUP BY national_id_hash HAVING COUNT(*)>1) x);

/* ---------- CONSTRAINTS THAT ARE OFF OR UNTRUSTED ---------- */
INSERT INTO #r (area, check_name, severity, violations)
SELECT 'schema','foreign keys disabled or not trusted','FAIL',(SELECT COUNT(*) FROM sys.foreign_keys WHERE is_disabled=1 OR is_not_trusted=1)
UNION ALL SELECT 'schema','check constraints disabled or not trusted','FAIL',(SELECT COUNT(*) FROM sys.check_constraints WHERE is_disabled=1 OR is_not_trusted=1);

/* ---------- RESULTS ---------- */
SELECT area, check_name, severity,
       violations,
       CASE WHEN violations = 0 THEN 'PASS' WHEN severity = 'FAIL' THEN 'FAIL' ELSE 'WARN' END AS result
FROM #r
ORDER BY CASE WHEN violations > 0 AND severity = 'FAIL' THEN 0 WHEN violations > 0 THEN 1 ELSE 2 END, area, id;

SELECT SUM(CASE WHEN violations = 0 THEN 1 ELSE 0 END)                       AS passed,
       SUM(CASE WHEN violations > 0 AND severity = 'FAIL' THEN 1 ELSE 0 END) AS failed,
       SUM(CASE WHEN violations > 0 AND severity = 'WARN' THEN 1 ELSE 0 END) AS warnings,
       COUNT(*)                                                              AS total_checks
FROM #r;

/* ---------- PROVIDER CONFIGURATION COMPLETENESS ("fully configured providers") ---------- */
SELECT p.tenant_key, p.org_type, p.is_active,
       (SELECT COUNT(*) FROM dbo.branches b WHERE b.provider_id=p.id AND b.is_active=1)                     AS branches,
       (SELECT COUNT(*) FROM dbo.specialties s WHERE s.provider_id=p.id AND s.is_active=1)                  AS specialties,
       (SELECT COUNT(*) FROM dbo.services s WHERE s.provider_id=p.id AND s.is_active=1)                     AS services,
       (SELECT COUNT(*) FROM dbo.doctors d WHERE d.provider_id=p.id AND d.is_active=1)                      AS doctors,
       (SELECT COUNT(*) FROM dbo.doctor_working_hours w WHERE w.provider_id=p.id AND w.is_active=1)         AS working_hours,
       (SELECT COUNT(*) FROM dbo.doctor_availability_slots s WHERE s.provider_id=p.id AND s.status='available' AND s.slot_date>=CAST(SYSUTCDATETIME() AS date)) AS future_slots,
       (SELECT COUNT(*) FROM dbo.patient_provider_profiles x WHERE x.provider_id=p.id AND x.is_active=1)    AS patients,
       (SELECT COUNT(*) FROM dbo.provider_memberships m WHERE m.provider_id=p.id AND m.is_active=1)         AS staff,
       CASE WHEN EXISTS (SELECT 1 FROM dbo.branches b WHERE b.provider_id=p.id AND b.is_active=1)
             AND EXISTS (SELECT 1 FROM dbo.doctors d WHERE d.provider_id=p.id AND d.is_active=1)
             AND EXISTS (SELECT 1 FROM dbo.services s WHERE s.provider_id=p.id AND s.is_active=1)
             AND EXISTS (SELECT 1 FROM dbo.doctor_working_hours w WHERE w.provider_id=p.id AND w.is_active=1)
            THEN 'configured' ELSE 'INCOMPLETE' END AS config_status
FROM dbo.providers p
ORDER BY p.tenant_key;

/* ---------- PER-TENANT ROW COUNTS (spot-check that data stays inside its tenant) ---------- */
SELECT p.tenant_key,
       (SELECT COUNT(*) FROM dbo.appointments x WHERE x.provider_id=p.id)         AS appointments,
       (SELECT COUNT(*) FROM dbo.ehr_encounters x WHERE x.provider_id=p.id)       AS encounters,
       (SELECT COUNT(*) FROM dbo.lab_reports x WHERE x.provider_id=p.id)          AS lab_reports,
       (SELECT COUNT(*) FROM dbo.radiology_reports x WHERE x.provider_id=p.id)    AS radiology_reports,
       (SELECT COUNT(*) FROM dbo.diagnostic_attachments x WHERE x.provider_id=p.id) AS attachments
FROM dbo.providers p
ORDER BY p.tenant_key;
GO
SET NOEXEC OFF;
GO
