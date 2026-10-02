from app.models.staff_audit_log import (
    StaffAuditLog,
)


def test_staff_audit_table_name():

    assert (
        StaffAuditLog.__tablename__
        == "staff_audit_logs"
    )


def test_staff_audit_columns():

    columns = {
        column.name
        for column
        in StaffAuditLog.__table__.columns
    }

    assert columns == {
        "id",
        "provider_id",
        "user_id",
        "membership_id",
        "patient_id",
        "action",
        "resource_type",
        "resource_id",
        "outcome",
        "created_at",
    }


def test_staff_audit_has_no_pii_columns():

    columns = {
        column.name
        for column
        in StaffAuditLog.__table__.columns
    }

    forbidden = {
        "national_id",
        "national_id_hash",
        "national_id_encrypted",
        "phone",
        "email",
        "message",
        "request_body",
    }

    assert columns.isdisjoint(
        forbidden
    )


def test_patient_id_is_nullable():

    column = (
        StaffAuditLog
        .__table__
        .c
        .patient_id
    )

    assert (
        column.nullable
        is True
    )


def test_audit_identifiers_have_no_foreign_keys():

    for name in (
        "provider_id",
        "user_id",
        "membership_id",
        "patient_id",
    ):

        column = (
            StaffAuditLog
            .__table__
            .c[name]
        )

        assert (
            len(column.foreign_keys)
            == 0
        )