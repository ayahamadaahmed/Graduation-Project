from app.models.radiology_report import (
    RadiologyReport,
)


def test_radiology_report_table_name():

    assert (
        RadiologyReport.__tablename__
        == "radiology_reports"
    )


def test_radiology_report_columns():

    table = RadiologyReport.__table__

    expected = {
        "id",
        "patient_id",
        "provider_id",
        "encounter_id",
        "diagnostic_attachment_id",
        "modality",
        "status",
        "created_at",
        "updated_at",
    }

    assert expected == set(
        table.columns.keys()
    )


def test_radiology_report_required_fields():

    table = RadiologyReport.__table__

    assert table.c.provider_id.nullable is False

    assert (
        table.c.diagnostic_attachment_id.nullable
        is False
    )

    assert table.c.modality.nullable is False

    assert table.c.status.nullable is False


def test_radiology_report_optional_fields():

    table = RadiologyReport.__table__

    assert table.c.patient_id.nullable is True

    assert table.c.encounter_id.nullable is True


def test_radiology_report_foreign_keys():

    table = RadiologyReport.__table__

    patient_fk = next(
        iter(
            table.c.patient_id.foreign_keys
        )
    )

    provider_fk = next(
        iter(
            table.c.provider_id.foreign_keys
        )
    )

    encounter_fk = next(
        iter(
            table.c.encounter_id.foreign_keys
        )
    )

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


def test_radiology_report_attachment_is_unique():

    names = {
        constraint.name
        for constraint
        in RadiologyReport.__table__.constraints
        if constraint.name
    }

    assert (
        "UQ_radiology_reports_diagnostic_attachment"
        in names
    )


def test_radiology_report_indexes():

    names = {
        index.name
        for index
        in RadiologyReport.__table__.indexes
    }

    assert (
        "IX_radiology_reports_patient_created"
        in names
    )

    assert (
        "IX_radiology_reports_provider_created"
        in names
    )