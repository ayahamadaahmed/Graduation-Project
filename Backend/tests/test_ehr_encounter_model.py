from app.models.ehr_encounter import (
    EHREncounter,
)

def _single_column_fk(column):
    """Return the plain single-column foreign key of a column.

    Some columns (provider_id, encounter_id, ...) are also part of composite
    foreign keys that tie a record to the same provider / patient.
    """
    return next(
        fk
        for fk in column.foreign_keys
        if len(fk.constraint.columns) == 1
    )


def test_ehr_encounter_table_name():
    assert (
        EHREncounter.__tablename__
        == "ehr_encounters"
    )


def test_ehr_encounter_required_columns():
    table = EHREncounter.__table__

    expected_columns = {
        "id",
        "patient_id",
        "provider_id",
        "doctor_id",
        "branch_id",
        "appointment_id",
        "encounter_type",
        "status",
        "started_at",
        "ended_at",
        "created_at",
        "updated_at",
    }

    assert expected_columns == set(
        table.columns.keys()
    )


def test_ehr_encounter_required_nullability():
    table = EHREncounter.__table__

    assert table.c.patient_id.nullable is False
    assert table.c.provider_id.nullable is False
    assert table.c.encounter_type.nullable is False
    assert table.c.status.nullable is False
    assert table.c.started_at.nullable is False

    assert table.c.doctor_id.nullable is True
    assert table.c.branch_id.nullable is True
    assert table.c.appointment_id.nullable is True
    assert table.c.ended_at.nullable is True


def test_ehr_encounter_foreign_keys():
    table = EHREncounter.__table__

    patient_fk = _single_column_fk(table.c.patient_id)

    provider_fk = _single_column_fk(table.c.provider_id)

    doctor_fk = _single_column_fk(table.c.doctor_id)

    branch_fk = _single_column_fk(table.c.branch_id)

    assert (
        patient_fk.target_fullname
        == "patients.id"
    )

    assert (
        provider_fk.target_fullname
        == "providers.id"
    )

    assert (
        doctor_fk.target_fullname
        == "doctors.id"
    )

    assert (
        branch_fk.target_fullname
        == "branches.id"
    )


def test_ehr_encounter_indexes():
    table = EHREncounter.__table__

    index_names = {
        index.name
        for index in table.indexes
    }

    assert (
        "IX_ehr_encounters_patient_started"
        in index_names
    )

    assert (
        "IX_ehr_encounters_provider_started"
        in index_names
    )