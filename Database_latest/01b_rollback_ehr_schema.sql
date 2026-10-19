/* =====================================================================
   MedMind - Rollback for 01_ehr_schema.sql
   Removes ONLY the objects created by script 01. Destroys any data in the
   new EHR tables. Does not touch pre-existing tables' data.
   ===================================================================== */
IF DB_ID() <= 4 OR OBJECT_ID(N'dbo.ehr_encounters', N'U') IS NULL
BEGIN
    RAISERROR(N'Select the MedMind database first.', 16, 1);
    SET NOEXEC ON;
END
GO
DROP VIEW IF EXISTS dbo.vw_active_access_grants;
DROP TRIGGER IF EXISTS dbo.TR_clinical_notes_protect_signed;
DROP TABLE IF EXISTS dbo.patient_access_grants;
DROP TABLE IF EXISTS dbo.clinical_notes;
DROP TABLE IF EXISTS dbo.patient_medications;
DROP TABLE IF EXISTS dbo.patient_allergies;
DROP TABLE IF EXISTS dbo.patient_conditions;
GO
IF EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_lab_reports_encounter_provider_patient')
    ALTER TABLE dbo.lab_reports DROP CONSTRAINT FK_lab_reports_encounter_provider_patient;
IF EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_radiology_reports_encounter_provider_patient')
    ALTER TABLE dbo.radiology_reports DROP CONSTRAINT FK_radiology_reports_encounter_provider_patient;
IF EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_diagnostic_attachments_encounter_provider_patient')
    ALTER TABLE dbo.diagnostic_attachments DROP CONSTRAINT FK_diagnostic_attachments_encounter_provider_patient;
IF EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_ehr_encounters_doctor_provider')
    ALTER TABLE dbo.ehr_encounters DROP CONSTRAINT FK_ehr_encounters_doctor_provider;
IF EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_ehr_encounters_branch_provider')
    ALTER TABLE dbo.ehr_encounters DROP CONSTRAINT FK_ehr_encounters_branch_provider;
IF EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_ehr_encounters_appointment_provider')
    ALTER TABLE dbo.ehr_encounters DROP CONSTRAINT FK_ehr_encounters_appointment_provider;
GO
IF EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = N'UQ_ehr_encounters_id_provider_patient')
    ALTER TABLE dbo.ehr_encounters DROP CONSTRAINT UQ_ehr_encounters_id_provider_patient;
IF EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = N'UQ_appointments_id_provider')
    ALTER TABLE dbo.appointments DROP CONSTRAINT UQ_appointments_id_provider;
IF EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = N'UQ_branches_id_provider')
    ALTER TABLE dbo.branches DROP CONSTRAINT UQ_branches_id_provider;
IF EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = N'UQ_doctors_id_provider')
    ALTER TABLE dbo.doctors DROP CONSTRAINT UQ_doctors_id_provider;
GO
PRINT N'Rollback of script 01 finished.';
GO
SET NOEXEC OFF;
GO
