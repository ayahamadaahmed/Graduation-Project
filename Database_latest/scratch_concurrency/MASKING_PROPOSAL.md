# Privacy decisions and masking inventory for the scratch copy (NOT implemented)

**Status: proposal only. No masking script exists and nothing has been run.
Masking is not complete and is not claimed to be.**

Source of this inventory: the SQLAlchemy models in `Backend/app/models/*.py`
(the schema at Alembic revision `c3d9e6a2f8b1`). It was **not** read from the
live database. Any future masking script must first compare the copy's
`INFORMATION_SCHEMA.COLUMNS` with this list and stop on any difference.
(The previous version listed `appointments.reason`, which does not exist, and
missed many columns; this version replaces it.)

Whether Final2 holds real or synthetic people is not established in the
repository. Treat every row as real.

## A. Two different artifacts

| | The `.bak` file (G3) | The scratch database (G4) |
|---|---|---|
| Content | Every page of `MedMind_Audit_Final2`, unmasked | Same as the `.bak` right after G4 |
| Can it be masked? | **No.** A backup is never modified | Only by an optional, separately approved step after the G4 check and before G5 (section D) |
| Encryption | None: G3 uses no `ENCRYPTION` option | Data/log files unencrypted (no TDE) |
| Who can read it | Anyone with read access to the instance backup folder, the SQL Server service account, local administrators | sysadmin logins; anyone who can copy its data/log files |
| After masking | Unchanged | Old values can remain in the transaction log and in unallocated pages of the data file until the database is dropped. Masking only changes what queries return |
| How it ends | G8 (`Remove-Item`): a normal delete, not a secure erase; msdb keeps the backup history and file path | G7/R2 `DROP DATABASE` deletes its files (normal delete) |

## B. Mandatory decisions (needed before G3, independent of masking)

1. **May a full, unmasked copy exist at all?** The `.bak` will be unmasked in
   every case. If not, G3 must not run.
2. **Retention.** Proposal: delete the `.bak` (G8) right after a verified G4;
   drop the copy (G7) right after G6. Record the actual times.
3. **Staff credentials (`user_accounts.password_hash`).** These are bcrypt hashes
   (`app/security/passwords.py`). Keeping them means:
   - two more copies of every staff password verifier (the `.bak` and the
     scratch copy), open to offline guessing against weak passwords by anyone
     who obtains either;
   - any process pointed at the copy would accept real staff passwords.

   C1-C3 never authenticate: `test_reschedule_concurrency_scratch_db.py` reads
   `provider_memberships.user_id`/`role` only. So neutralising the hashes *in
   the copy* costs the tests nothing, but it can never remove them from the
   `.bak`.
4. **National ID protection.** `national_id_hash` is a keyed HMAC
   (`app/core/patient_identity.py`). `national_id_encrypted` is ciphertext.
   Both keys are application secrets held on the same machine (never read
   here). So the copy is exactly as protected as Final2, not more.
5. **Access and output.** Same instance and disk only. No copy of the `.bak`
   elsewhere. Test and runner output show ids, codes and counts, never names,
   phones or clinical text.

## C. Inventory (sensitive columns identified in the models)

Scope: built by reading the model files. It does not prove that it lists
every sensitive column, nor that the live database matches the models
(section E). Every table also has `created_at`/`updated_at` timestamps.
Those are not listed one by one; combined with ids they are
quasi-identifiers too, and are retained unless a decision says otherwise.

Legend:
- **Class**: DI direct identifier, QI quasi-identifier, FT free text,
  CL clinical, CR credential, ST staff/business personal data,
  REF linkage/reference value.
- **NN**: NOT NULL in the model.
- **C1-C3**: read or written by `test_reschedule_concurrency_scratch_db.py`,
  directly or through the booking/reschedule service (static reading; not
  executed).
- **Treatment** is only a proposal. "Retain" means it is kept **on purpose**;
  the reason is given.

### Patients and identity

| Column | Class | Constraints | C1-C3 | Treatment |
|---|---|---|---|---|
| `patients.full_name_ar` | DI | NN | copied into new appointments by booking | `N'Test patient ' + patient_code` |
| `patients.full_name_en` | DI | nullable | same | `NULL` |
| `patients.phone` | DI | NN, non-unique `IX_patients_phone` | copied into new appointments | fixed test number (check the booking path's phone validation first; not verified) |
| `patients.email` | DI | nullable | no | `NULL` |
| `patients.date_of_birth` | QI | nullable | no | `NULL` |
| `patients.gender` | QI | nullable, CHECK male/female | no | `NULL` |
| `patients.location` | QI/FT | nullable | no | `NULL` |
| `patients.digital_literacy_flag` | QI | nullable, CHECK | no | `NULL` |
| `patients.national_id_last4` | QI | NN, CHECK 4 digits, indexed | no | `N'0000'` |
| `patients.national_id_hash` | DI (keyed) | NN, unique, CHECK length 64 | **yes**: the seed selects a patient by it | **Retain**: the test needs it; HMAC, key never read |
| `patients.national_id_encrypted` | DI (ciphertext) | NN | not referenced by the test | **Retain** (decision B.4): replacing it would break any decryption path; not analysed |
| `patients.patient_code` | identifier | NN, unique, CHECK digits | used in masked names | **Retain**: unique key |
| `patient_provider_profiles.medical_record_number` | identifier | nullable, filtered unique | joined by the seed | **Retain**: unique, used by booking |
| `patient_provider_profiles.consent_status`, `consent_timestamp` | QI | NN / nullable | `is_active` only | retain (not identifying alone) |
| `patient_branch_profiles.medical_record_number` | identifier | NN, unique per provider/branch | joined by the seed | **Retain**: unique, used by booking |

### Appointments, history, reminders, idempotency

| Column | Class | Constraints | C1-C3 | Treatment |
|---|---|---|---|---|
| `appointments.patient_name` | DI | NN | written by booking | same rule as `patients.full_name_ar` |
| `appointments.phone` | DI | NN | written by booking | same rule as `patients.phone` |
| `appointments.notes` | FT | nullable | no | `NULL` |
| `appointments.cancellation_reason` | FT | nullable | no | `NULL` |
| `appointments.created_by_reference` | REF | nullable | written by booking | `NULL` |
| `appointments.appointment_reference` | REF | NN, unique per provider | written by booking | **Retain**: unique key |
| `appointment_status_history.reason` | FT | nullable | written by reschedule | `NULL` |
| `appointment_status_history.actor_reference` | REF | nullable | written by reschedule | `NULL` |
| `reminders.recipient_phone` | DI | NN | no | fixed test number |
| `reminders.recipient_name` | DI | nullable | no | `NULL` |
| `reminders.content` | FT | nullable | no | `NULL` |
| `reminders.patient_response` | FT | nullable | no | `NULL` |
| `reminders.last_error` | FT | nullable | no | `NULL` (provider errors can echo phone numbers) |
| `reminders.provider_message_id` | REF | nullable | no | `NULL` |
| `idempotency_requests.response_body` | FT/DI | nullable | no (the test sends no keys) | `NULL` (stored responses hold names, codes, MRNs) |
| `idempotency_requests.idempotency_key`, `request_hash` | REF | NN, unique (tenant, operation, key) | no | retain (unique; not identifying alone) |

### Clinical records

| Column | Class | Constraints | C1-C3 | Treatment |
|---|---|---|---|---|
| `ehr_encounters.started_at`, `ended_at`, `encounter_type` | QI | NN / nullable / NN | no | retain (dates) or shift: decision |
| `clinical_notes.title` | FT | nullable | no | `NULL` |
| `clinical_notes.note_text` | CL/FT | NN | no | `N'[masked]'` |
| `patient_conditions.condition_name` | CL | NN | no | `N'[masked]'` |
| `patient_conditions.icd10_code` | CL | nullable | no | `NULL` |
| `patient_conditions.notes` | FT | nullable | no | `NULL` |
| `patient_conditions.clinical_status`, `severity`, `onset_date`, `resolved_date` | CL | NN / nullable | no | retain status (CHECK-constrained), `NULL` the rest |
| `patient_medications.medication_name` | CL | NN | no | `N'[masked]'` |
| `patient_medications.dosage`, `frequency`, `route`, `notes` | CL/FT | nullable | no | `NULL` |
| `patient_medications.start_date`, `end_date` | QI | nullable | no | `NULL` |
| `patient_allergies.allergen` | CL | NN | no | `N'[masked]'` |
| `patient_allergies.reaction` | CL/FT | nullable | no | `NULL` |
| `patient_allergies.allergen_type`, `severity` | CL | NN | no | retain (constrained codes) |
| `patient_allergies.noted_date` | QI | nullable | no | `NULL` |
| `lab_reports.unreadable_fields_json` | FT | nullable | no | `NULL` |
| `lab_reports.document_type` | CL | nullable | no | retain |
| `lab_results.raw_name` | CL | NN | no | `N'[masked]'` |
| `lab_results.value`, `unit`, `reference_min`, `reference_max`, `reference_text` | CL | nullable | no | `NULL` |
| `lab_results.canonical_name`, `panel`, `flag` | CL | nullable / NN `flag` | no | retain `flag` (NN), `NULL` the others |
| `radiology_reports.modality` | CL | NN | no | retain (no free-text columns in this table) |
| `diagnostic_assessments.classification` | CL | NN | no | `N'[masked]'` |
| `diagnostic_assessments.probabilities_json`, `limitations_json` | CL | NN | no | `N'{}'` / `N'[]'` |
| `diagnostic_assessments.confidence` | CL | NN, CHECK 0..1 | no | `0` |
| `diagnostic_attachments.original_filename` | DI/FT | NN | no | `N'masked'` |
| `diagnostic_attachments.storage_key` | REF | NN | no | `N'masked/' + attachment_id` (points to stored files; files are not in the DB) |
| `diagnostic_attachments.sha256` | REF | NN | no | retain or random: decision (proves possession of a known document) |
| `diagnostic_attachments.attachment_id`, `session_id` | REF | NN, `attachment_id` unique | no | retain (unique) |
| `patient_access_grants.granted_by` | REF/ST | NN | no | `N'masked'` |
| `patient_access_grants.revoked_reason` | FT | nullable | no | `NULL` |
| `staff_audit_logs` (`user_id`, `patient_id`, `action`, `resource_id`) | REF | NN / nullable | no | retain (no free text; links staff to patients: covered by decision B.1) |

### Dates and times (quasi-identifiers)

| Column | Class | Constraints | C1-C3 | Treatment |
|---|---|---|---|---|
| `appointments.scheduled_date`, `start_time`, `end_time` | QI | NN | **yes**: booking and reschedule write them from the slot | **Retain**: they must match `doctor_availability_slots`; shifting would have to shift slots consistently (decision) |
| `appointments.confirmed_at`, `cancelled_at` | QI | nullable | written by booking/reschedule | retain or shift: decision |
| `appointment_status_history.changed_at` | QI | NN | written by reschedule | retain or shift: decision |
| `doctor_availability_slots.slot_date`, `start_time`, `end_time` | QI (linked to appointments) | NN | **yes**: the test creates and books slots | **Retain**: needed by the tests and the unique slot indexes |
| `reminders.scheduled_for` | QI | NN | no | retain or shift: decision |
| `reminders.last_attempt_at`, `sent_at`, `delivered_at`, `response_at` | QI | nullable | no | `NULL` |
| `doctor_schedule_exceptions.exception_date`, `exception_type`, `start_time`, `end_time` | ST/QI | NN / NN / nullable | no | retain or delete the rows in the copy: decision (staff leave dates) |
| `clinical_notes.signed_at` | QI | nullable | no | `NULL` |
| `patient_access_grants.granted_at`, `expires_at`, `revoked_at` | QI | NN / nullable | no | retain or shift: decision |
| `doctor_verification_decisions.decided_at` | ST/QI | NN | reads the table | retain |

### Staff and business data

| Column | Class | Constraints | C1-C3 | Treatment |
|---|---|---|---|---|
| `user_accounts.email` | ST/DI | NN, unique `uq_user_accounts_email` | no | `'zztest-' + CONVERT(varchar(36), id) + '@invalid'` (stays unique) |
| `user_accounts.password_hash` | CR | NN | no (no authentication) | sentinel that can never verify: decision B.3 |
| `provider_memberships.user_id`, `role`, `doctor_id` | REF/ST | NN / NN / nullable | **yes**: the seed reads `user_id` and `role = 'provider_admin'` | **Retain**: the test needs them (staff-to-provider links, no free text) |
| `doctors.full_name_ar`, `full_name_en` | ST | NN | the test inserts its own doctors | `N'Doctor ' + LEFT(CONVERT(nvarchar(36), id), 8)` |
| `doctors.license_number` | ST | nullable, filtered unique per provider | G4b counts `ZZTEST-DV-%` | **Retain** `ZZTEST-DV-%` rows; others `NULL` (the filtered index allows many NULLs) |
| `doctors.bio_ar`, `bio_en`, `photo_url`, `gender` | ST/FT | nullable | no | `NULL` |
| `doctor_verification_decisions.reason` | FT | nullable | reads the table | `NULL` |
| `doctor_schedule_exceptions.reason` | FT | nullable | no | `NULL` (may describe staff leave or health) |
| `providers.phone`, `email`, `address` | ST | nullable | no | retain (business contact) or `NULL`: decision |
| `branches.address_ar`, `address_en`, `phone`, `whatsapp`, `latitude`, `longitude` | ST | nullable | branch id, `mrn_code` | retain (business) or `NULL`: decision |
| `departments.phone` | ST | nullable | no | retain |

Tables with no personal or clinical content in the models: `services`,
`specialties`, `service_specialties`, `department_specialties`,
`doctor_branches`, `doctor_services`, `doctor_working_hours`,
`branch_mrn_sequences`,
`patient_number_sequences`, `alembic_version`.

## D. If masking is approved later (G5b, not written)

- **When:** after the G4b and fingerprint comparison (masking changes the
  fingerprints), before G5.
- **Where:** on the scratch copy only, through the runner, as a new pinned
  script that checks it is on the scratch database, as G5 does.
- **Its own checks:** compare the copy's columns against section C; verify
  every unique and CHECK constraint afterwards.
- **Approval:** each "decision" cell above needs an explicit answer first.

## E. Not covered

- Columns that exist in the live database but not in the models (drift).
  The script must stop on any difference.
- Stored attachment files (`storage_key` targets) are outside the database
  and outside this workflow.
- The `.bak`, the transaction log of the copy, and msdb history (section A).
