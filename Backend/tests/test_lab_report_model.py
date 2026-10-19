from app.models.lab_report import (
    LabReport,
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


def test_lab_report_table_name():

    assert (
        LabReport.__tablename__
        == "lab_reports"
    )


def test_lab_report_columns():

    table = LabReport.__table__

    expected = {
        "id",
        "patient_id",
        "provider_id",
        "encounter_id",
        "diagnostic_attachment_id",
        "document_type",
        "unreadable_fields_json",
        "status",
        "created_at",
        "updated_at",
    }

    assert expected == set(
        table.columns.keys()
    )


def test_lab_report_nullability():

    table = LabReport.__table__

    assert (
        table.c.provider_id.nullable
        is False
    )

    assert (
        table.c.diagnostic_attachment_id.nullable
        is False
    )

    assert (
        table.c.status.nullable
        is False
    )

    assert (
        table.c.patient_id.nullable
        is True
    )

    assert (
        table.c.encounter_id.nullable
        is True
    )

    assert (
        table.c.document_type.nullable
        is True
    )


def test_lab_report_foreign_keys():

    table = LabReport.__table__

    patient_fk = _single_column_fk(table.c.patient_id)

    provider_fk = _single_column_fk(table.c.provider_id)

    encounter_fk = _single_column_fk(table.c.encounter_id)

    attachment_fk = next(
        iter(
            table
            .c
            .diagnostic_attachment_id
            .foreign_keys
        )
    )

    assert (
        patient_fk.target_fullname
        == "patients.id"
    )

    assert (
        provider_fk.target_fullname
        == "providers.id"
    )

    assert (
        encounter_fk.target_fullname
        == "ehr_encounters.id"
    )

    assert (
        attachment_fk.target_fullname
        == "diagnostic_attachments.id"
    )


def test_lab_report_attachment_is_unique():

    table = LabReport.__table__

    constraint_names = {
        constraint.name
        for constraint in table.constraints
        if constraint.name
    }

    assert (
        "UQ_lab_reports_diagnostic_attachment"
        in constraint_names
    )


def test_lab_report_indexes():

    index_names = {
        index.name
        for index
        in LabReport.__table__.indexes
    }

    assert (
        "IX_lab_reports_patient_created"
        in index_names
    )

    assert (
        "IX_lab_reports_provider_created"
        in index_names
    )