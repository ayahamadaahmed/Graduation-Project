"""
The deterministic, entirely fake fixture for the SYNTHETIC concurrency
database (Database_latest/synthetic_concurrency). Single source of
truth: the seed SQL (S3), the verification SQL (S4) and the synthetic guard
are all derived from these rows.

Nothing here comes from any existing database. No real person, phone
number, national ID, e-mail address or credential is represented:
  - names are "Synthetic ...";
  - the phone number has an impossible format (+20 0...);
  - the national-ID hash is SHA-256 of a fixed label, not of any ID;
  - national_id_encrypted holds the ASCII bytes "SYNTHETIC" (not a
    ciphertext; the booking path under test never decrypts it);
  - the e-mail domain is .invalid (RFC 2606);
  - password_hash is a sentinel that is not a bcrypt hash and can never
    verify, so the staff account can never log in.

Only the rows that the C1-C4 tests need before they start are seeded. The
tests create their own doctors, links, slots, appointments, history,
decisions and audit rows (SYNTHETIC_TEST_WRITABLE_TABLES).
"""

import hashlib
import json

FIXTURE_VERSION = "synthetic-v1"
EXPECTED_REVISION = "c3d9e6a2f8b1"
MARKER_TABLE = "zz_synthetic_marker"
MARKER_KIND = "synthetic"
TEST_DOCTOR_LICENSE_PREFIX = "ZZTEST-CC-"  # tests/test_reschedule_concurrency_scratch_db.py MARKER_PREFIX

PROVIDER_ID = "5e000001-0000-4000-8000-000000000001"
USER_ID = "5e000002-0000-4000-8000-000000000001"
BRANCH_ID = "5e000003-0000-4000-8000-000000000001"
SPECIALTY_ID = "5e000004-0000-4000-8000-000000000001"
SERVICE_ID = "5e000005-0000-4000-8000-000000000001"
PATIENT_ID = "5e000006-0000-4000-8000-000000000001"
PROVIDER_PROFILE_ID = "5e000007-0000-4000-8000-000000000001"
BRANCH_PROFILE_ID = "5e000008-0000-4000-8000-000000000001"
MEMBERSHIP_ID = "5e000009-0000-4000-8000-000000000001"

PATIENT_HASH = hashlib.sha256(b"medmind-synthetic-patient-0001").hexdigest()
NON_VERIFIABLE_PASSWORD = "!synthetic-account-no-login"

# In insertion (foreign-key) order. Columns not listed take their modeled
# server defaults (ids are always given explicitly).
SYNTHETIC_ROWS = [
    ("providers", {
        "id": PROVIDER_ID, "tenant_key": "synthetic-clinic-01", "name": "Synthetic Clinic 01",
        "slug": "synthetic-clinic-01", "org_type": "clinic", "verification_status": "verified",
        "default_language": "en", "timezone": "Africa/Cairo", "currency_code": "EGP", "is_active": True,
    }),
    ("user_accounts", {
        "id": USER_ID, "email": "synthetic.admin@example.invalid",
        "password_hash": NON_VERIFIABLE_PASSWORD, "is_active": True,
    }),
    ("branches", {
        "id": BRANCH_ID, "provider_id": PROVIDER_ID, "code": "SYN-B1", "name_ar": "Synthetic Branch 1",
        "name_en": "Synthetic Branch 1", "timezone": "Africa/Cairo", "is_active": True, "mrn_code": "SYN",
    }),
    ("specialties", {
        "id": SPECIALTY_ID, "provider_id": PROVIDER_ID, "code": "SYN-GEN", "name_ar": "Synthetic Specialty",
        "name_en": "Synthetic Specialty", "is_active": True,
    }),
    ("services", {
        "id": SERVICE_ID, "provider_id": PROVIDER_ID, "code": "SYN-CONSULT", "name_ar": "Synthetic Consultation",
        "name_en": "Synthetic Consultation", "duration_minutes": 15, "service_type": "consultation",
        "requires_preparation": False, "is_active": True,
    }),
    ("patients", {
        "id": PATIENT_ID, "phone": "+200000000001", "preferred_language": "en", "is_active": True,
        "patient_code": "9000001", "national_id_hash": PATIENT_HASH, "national_id_encrypted": b"SYNTHETIC",
        "national_id_last4": "0000", "full_name_ar": "Synthetic Patient 0001", "full_name_en": "Synthetic Patient 0001",
    }),
    ("patient_provider_profiles", {
        "id": PROVIDER_PROFILE_ID, "patient_id": PATIENT_ID, "provider_id": PROVIDER_ID,
        "medical_record_number": "SYN-MRN-0001", "preferred_channel": "web", "consent_status": "pending",
        "is_active": True,
    }),
    ("patient_branch_profiles", {
        "id": BRANCH_PROFILE_ID, "provider_id": PROVIDER_ID, "branch_id": BRANCH_ID, "patient_id": PATIENT_ID,
        "medical_record_number": "SYN-000001", "is_active": True,
    }),
    ("provider_memberships", {
        "id": MEMBERSHIP_ID, "user_id": USER_ID, "provider_id": PROVIDER_ID, "role": "provider_admin",
        "is_active": True,
    }),
]

SYNTHETIC_SEED_TABLES = tuple(table for table, _ in SYNTHETIC_ROWS)

# Tables the tests (and the booking/reschedule/decision services they call)
# write to. Every other table must stay exactly as seeded.
SYNTHETIC_TEST_WRITABLE_TABLES = (
    "appointment_status_history", "appointments", "doctor_availability_slots", "doctor_branches",
    "doctor_services", "doctor_verification_decisions", "doctors", "staff_audit_logs",
)

# Rows per seeded table. Unseeded, non-writable tables must hold 0 rows.
SYNTHETIC_MANIFEST = {table: sum(1 for t, _ in SYNTHETIC_ROWS if t == table) for table in SYNTHETIC_SEED_TABLES}


def _canonical(value):
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    return value


MANIFEST_SHA256 = hashlib.sha256(json.dumps(
    {"fixture_version": FIXTURE_VERSION, "revision": EXPECTED_REVISION,
     "rows": [[table, {k: _canonical(v) for k, v in sorted(row.items())}] for table, row in SYNTHETIC_ROWS]},
    sort_keys=True, separators=(",", ":"),
).encode("ascii")).hexdigest()
