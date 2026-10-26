import importlib.util
from pathlib import Path

from app.models import (
    Appointment,
    Branch,
    ClinicalNote,
    DiagnosticAttachment,
    Doctor,
    EHREncounter,
    LabReport,
    PatientAccessGrant,
    PatientAllergy,
    PatientCondition,
    PatientMedication,
    RadiologyReport,
)

CLINICAL_MODELS = {
    PatientCondition: "patient_conditions",
    PatientAllergy: "patient_allergies",
    PatientMedication: "patient_medications",
    ClinicalNote: "clinical_notes",
}

MIGRATION_FILE = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "e7c1d4a9b2f6_add_ehr_clinical_tables_and_access_grants.py"
)


def _composite_fks(table):
    """Map constraint name -> (local columns, referenced columns) for composite keys."""
    return {
        constraint.name: (
            [column.name for column in constraint.columns],
            [element.target_fullname for element in constraint.elements],
        )
        for constraint in table.foreign_key_constraints
        if len(constraint.columns) > 1
    }


def _constraint_names(table):
    return {
        constraint.name
        for constraint in table.constraints
        if constraint.name
    }


def test_new_table_names():
    for model, table_name in CLINICAL_MODELS.items():
        assert model.__tablename__ == table_name

    assert PatientAccessGrant.__tablename__ == "patient_access_grants"


def test_clinical_tables_are_tenant_scoped_and_patient_linked():
    for model in CLINICAL_MODELS:
        columns = set(model.__table__.c.keys())

        assert {"id", "provider_id", "patient_id", "created_at"} <= columns
        assert model.__table__.c.provider_id.nullable is False
        assert model.__table__.c.patient_id.nullable is False


def test_clinical_tables_enforce_same_provider_patient_encounter_and_doctor():
    for model, table_name in CLINICAL_MODELS.items():
        fks = _composite_fks(model.__table__)

        profile = fks[f"FK_{table_name}_profile"]
        assert profile[0] == ["patient_id", "provider_id"]
        assert profile[1] == [
            "patient_provider_profiles.patient_id",
            "patient_provider_profiles.provider_id",
        ]

        encounter = fks[f"FK_{table_name}_encounter"]
        assert encounter[0] == ["encounter_id", "provider_id", "patient_id"]
        assert encounter[1] == [
            "ehr_encounters.id",
            "ehr_encounters.provider_id",
            "ehr_encounters.patient_id",
        ]

        doctor_fks = [
            value
            for name, value in fks.items()
            if name == f"FK_{table_name}_doctor"
        ]
        assert len(doctor_fks) == 1
        assert doctor_fks[0][1] == ["doctors.id", "doctors.provider_id"]


def test_clinical_note_requires_encounter_and_author():
    table = ClinicalNote.__table__

    assert table.c.encounter_id.nullable is False
    assert table.c.doctor_id.nullable is False
    assert table.c.note_text.nullable is False

    names = _constraint_names(table)
    assert "CK_clinical_notes_signed" in names
    assert "CK_clinical_notes_addendum" in names
    assert "FK_clinical_notes_addendum" in names


def test_access_grant_structure():
    table = PatientAccessGrant.__table__

    assert {
        "patient_id",
        "owner_provider_id",
        "grantee_provider_id",
        "scope",
        "expires_at",
        "revoked_at",
    } <= set(table.c.keys())

    fks = _composite_fks(table)
    assert fks["FK_patient_access_grants_owner_profile"][0] == [
        "patient_id",
        "owner_provider_id",
    ]

    assert "CK_patient_access_grants_distinct" in _constraint_names(table)

    index_names = {index.name for index in table.indexes}
    assert "UX_patient_access_grants_active" in index_names


def test_existing_models_expose_composite_keys():
    def unique_names(model):
        return {
            constraint.name
            for constraint in model.__table__.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }

    assert "UQ_doctors_id_provider" in unique_names(Doctor)
    assert "UQ_branches_id_provider" in unique_names(Branch)
    assert "UQ_appointments_id_provider" in unique_names(Appointment)
    assert "UQ_ehr_encounters_id_provider_patient" in unique_names(EHREncounter)

    encounter_fks = _composite_fks(EHREncounter.__table__)
    assert "FK_ehr_encounters_doctor_provider" in encounter_fks
    assert "FK_ehr_encounters_branch_provider" in encounter_fks
    assert "FK_ehr_encounters_appointment_provider" in encounter_fks

    for model, table_name in (
        (LabReport, "lab_reports"),
        (RadiologyReport, "radiology_reports"),
        (DiagnosticAttachment, "diagnostic_attachments"),
    ):
        fks = _composite_fks(model.__table__)
        assert fks[f"FK_{table_name}_encounter_provider_patient"][1] == [
            "ehr_encounters.id",
            "ehr_encounters.provider_id",
            "ehr_encounters.patient_id",
        ]


def test_migration_follows_latest_revision_and_matches_models():
    spec = importlib.util.spec_from_file_location("ehr_migration", MIGRATION_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == "e7c1d4a9b2f6"
    assert module.down_revision == "a5e30b966d98"

    source = MIGRATION_FILE.read_text(encoding="utf-8")

    # Every named constraint/index the models declare for the new tables must
    # also be created by the migration, so Alembic and the ORM cannot drift.
    models = list(CLINICAL_MODELS) + [PatientAccessGrant]
    for model in models:
        table = model.__table__

        names = _constraint_names(table) | {index.name for index in table.indexes}

        for name in names:
            # Foreign keys are generated from a naming pattern in the migration.
            if name.startswith("FK_") and name.endswith(("_profile", "_encounter", "_doctor")):
                continue

            assert name in source, f"{name} missing from the migration"
