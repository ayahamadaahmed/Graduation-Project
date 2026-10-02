"""add staff audit logs

Revision ID: 450bd59e69e1
Revises: 4cfaa1f51cc6
Create Date: 2026-09-17 20:26:06.730777
"""

from typing import (
    Sequence,
    Union,
)

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql


revision: str = "450bd59e69e1"

down_revision: Union[
    str,
    Sequence[str],
    None,
] = "4cfaa1f51cc6"

branch_labels = None
depends_on = None


def upgrade() -> None:

    # ========================================================
    # STAFF AUDIT LOGS
    # ========================================================

    op.create_table(
        "staff_audit_logs",

        sa.Column(
            "id",
            mssql.UNIQUEIDENTIFIER(),
            server_default=sa.text(
                "NEWID()"
            ),
            nullable=False,
        ),

        sa.Column(
            "provider_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=False,
        ),

        sa.Column(
            "user_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=False,
        ),

        sa.Column(
            "membership_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=False,
        ),

        sa.Column(
            "patient_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=True,
        ),

        sa.Column(
            "action",
            sa.String(length=100),
            nullable=False,
        ),

        sa.Column(
            "resource_type",
            sa.String(length=50),
            nullable=False,
        ),

        sa.Column(
            "resource_id",
            sa.String(length=100),
            nullable=True,
        ),

        sa.Column(
            "outcome",
            sa.String(length=30),
            nullable=False,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text(
                "TODATETIMEOFFSET("
                "SYSUTCDATETIME(), "
                "'+00:00'"
                ")"
            ),
            nullable=False,
        ),

        sa.PrimaryKeyConstraint(
            "id",
            name="pk_staff_audit_logs",
        ),

        sa.CheckConstraint(
            "outcome IN ("
            "'success', "
            "'not_found', "
            "'denied', "
            "'error'"
            ")",
            name=(
                "ck_staff_audit_logs_outcome"
            ),
        ),
    )

    # ========================================================
    # INDEXES
    # ========================================================

    op.create_index(
        "ix_staff_audit_logs_provider_created",
        "staff_audit_logs",
        [
            "provider_id",
            "created_at",
        ],
        unique=False,
    )

    op.create_index(
        "ix_staff_audit_logs_user_created",
        "staff_audit_logs",
        [
            "user_id",
            "created_at",
        ],
        unique=False,
    )

    op.create_index(
        "ix_staff_audit_logs_patient_created",
        "staff_audit_logs",
        [
            "patient_id",
            "created_at",
        ],
        unique=False,
    )


def downgrade() -> None:

    op.drop_index(
        "ix_staff_audit_logs_patient_created",
        table_name="staff_audit_logs",
    )

    op.drop_index(
        "ix_staff_audit_logs_user_created",
        table_name="staff_audit_logs",
    )

    op.drop_index(
        "ix_staff_audit_logs_provider_created",
        table_name="staff_audit_logs",
    )

    op.drop_table(
        "staff_audit_logs"
    )