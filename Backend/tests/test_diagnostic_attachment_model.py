from app.models.diagnostic_attachment import (
    DiagnosticAttachment,
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


def test_diagnostic_attachment_table_name():
    assert (
        DiagnosticAttachment.__tablename__
        == "diagnostic_attachments"
    )


def test_diagnostic_attachment_columns():
    table = DiagnosticAttachment.__table__

    expected_columns = {
        "id",
        "attachment_id",
        "provider_id",
        "patient_id",
        "encounter_id",
        "session_id",
        "original_filename",
        "content_type",
        "size_bytes",
        "sha256",
        "storage_key",
        "status",
        "created_at",
        "updated_at",
    }

    assert expected_columns == set(
        table.columns.keys()
    )


def test_diagnostic_attachment_nullability():
    table = DiagnosticAttachment.__table__

    assert table.c.attachment_id.nullable is False
    assert table.c.provider_id.nullable is False
    assert table.c.session_id.nullable is False
    assert table.c.original_filename.nullable is False
    assert table.c.content_type.nullable is False
    assert table.c.size_bytes.nullable is False
    assert table.c.sha256.nullable is False
    assert table.c.storage_key.nullable is False
    assert table.c.status.nullable is False

    assert table.c.patient_id.nullable is True
    assert table.c.encounter_id.nullable is True


def test_diagnostic_attachment_foreign_keys():
    table = DiagnosticAttachment.__table__

    provider_fk = _single_column_fk(table.c.provider_id)

    patient_fk = _single_column_fk(table.c.patient_id)

    encounter_fk = _single_column_fk(table.c.encounter_id)

    assert (
        provider_fk.target_fullname
        == "providers.id"
    )

    assert (
        patient_fk.target_fullname
        == "patients.id"
    )

    assert (
        encounter_fk.target_fullname
        == "ehr_encounters.id"
    )


def test_diagnostic_attachment_unique_id():
    table = DiagnosticAttachment.__table__

    constraint_names = {
        constraint.name
        for constraint in table.constraints
        if constraint.name
    }

    assert (
        "UQ_diagnostic_attachments_attachment_id"
        in constraint_names
    )


def test_diagnostic_attachment_indexes():
    table = DiagnosticAttachment.__table__

    index_names = {
        index.name
        for index in table.indexes
    }

    assert (
        "IX_diagnostic_attachments_patient_created"
        in index_names
    )

    assert (
        "IX_diagnostic_attachments_provider_session"
        in index_names
    )