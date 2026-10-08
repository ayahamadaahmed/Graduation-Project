from app.models.lab_result import (
    LabResult,
)


def test_lab_result_table_name():

    assert (
        LabResult.__tablename__
        == "lab_results"
    )


def test_lab_result_columns():

    table = LabResult.__table__

    expected = {
        "id",
        "lab_report_id",
        "result_index",
        "panel",
        "raw_name",
        "canonical_name",
        "value",
        "unit",
        "reference_min",
        "reference_max",
        "reference_text",
        "flag",
        "mapping_status",
        "created_at",
    }

    assert expected == set(
        table.columns.keys()
    )


def test_lab_result_required_fields():

    table = LabResult.__table__

    assert table.c.lab_report_id.nullable is False
    assert table.c.result_index.nullable is False
    assert table.c.raw_name.nullable is False
    assert table.c.flag.nullable is False
    assert table.c.mapping_status.nullable is False


def test_lab_result_optional_fields():

    table = LabResult.__table__

    assert table.c.panel.nullable is True
    assert table.c.canonical_name.nullable is True
    assert table.c.value.nullable is True
    assert table.c.unit.nullable is True
    assert table.c.reference_min.nullable is True
    assert table.c.reference_max.nullable is True
    assert table.c.reference_text.nullable is True


def test_lab_result_report_foreign_key():

    table = LabResult.__table__

    fk = next(
        iter(
            table.c.lab_report_id.foreign_keys
        )
    )

    assert (
        fk.target_fullname
        == "lab_reports.id"
    )


def test_lab_result_unique_report_index():

    table = LabResult.__table__

    names = {
        constraint.name
        for constraint in table.constraints
        if constraint.name
    }

    assert (
        "UQ_lab_results_report_index"
        in names
    )


def test_lab_result_indexes():

    names = {
        index.name
        for index in LabResult.__table__.indexes
    }

    assert (
        "IX_lab_results_report"
        in names
    )

    assert (
        "IX_lab_results_canonical_name"
        in names
    )