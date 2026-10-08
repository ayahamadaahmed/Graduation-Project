from app.models.diagnostic_assessment import (
    DiagnosticAssessment,
)


def test_diagnostic_assessment_table_name():

    assert (
        DiagnosticAssessment.__tablename__
        == "diagnostic_assessments"
    )


def test_diagnostic_assessment_columns():

    table = DiagnosticAssessment.__table__

    expected = {
        "id",
        "radiology_report_id",
        "assessment_type",
        "classification",
        "probabilities_json",
        "confidence",
        "inference_latency_ms",
        "model_name",
        "model_version",
        "limitations_json",
        "created_at",
    }

    assert expected == set(
        table.columns.keys()
    )


def test_diagnostic_assessment_required_fields():

    table = DiagnosticAssessment.__table__

    required = {
        "radiology_report_id",
        "assessment_type",
        "classification",
        "probabilities_json",
        "confidence",
        "inference_latency_ms",
        "model_name",
        "model_version",
        "limitations_json",
        "created_at",
    }

    for name in required:
        assert (
            table.c[name].nullable
            is False
        )


def test_diagnostic_assessment_report_foreign_key():

    table = DiagnosticAssessment.__table__

    fk = next(
        iter(
            table
            .c
            .radiology_report_id
            .foreign_keys
        )
    )

    assert (
        fk.target_fullname
        == "radiology_reports.id"
    )


def test_diagnostic_assessment_indexes():

    names = {
        index.name
        for index
        in DiagnosticAssessment.__table__.indexes
    }

    assert (
        "IX_diagnostic_assessments_report_created"
        in names
    )

    assert (
        "IX_diagnostic_assessments_model"
        in names
    )


def test_diagnostic_assessment_checks():

    names = {
        constraint.name
        for constraint
        in DiagnosticAssessment.__table__.constraints
        if constraint.name
    }

    assert (
        "CK_diagnostic_assessments_confidence"
        in names
    )

    assert (
        "CK_diagnostic_assessments_latency"
        in names
    )


def test_report_can_have_multiple_assessments():

    table = DiagnosticAssessment.__table__

    unique_column_sets = {
        tuple(
            column.name
            for column
            in constraint.columns
        )
        for constraint
        in table.constraints
        if (
            constraint.__class__.__name__
            == "UniqueConstraint"
        )
    }

    assert (
        ("radiology_report_id",)
        not in unique_column_sets
    )