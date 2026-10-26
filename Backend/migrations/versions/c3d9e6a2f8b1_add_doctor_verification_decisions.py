"""add doctor verification decisions

Revision ID: c3d9e6a2f8b1
Revises: a8c2e5f1b7d4
Create Date: 2026-10-22 12:00:00.000000

Append-only history of doctor verification decisions (verified, rejected,
resubmitted), with the reviewer, the time and the rejection reason.

Creates one new, empty table and one unique key on provider_memberships,
uq_provider_memberships_id_user_provider (id, user_id, provider_id): always
satisfiable because id is the primary key, so no existing row can violate
it. It is the target of the single composite reviewer foreign key, which
makes the membership, the user and the provider one and the same row. No
existing row is changed.

Prerequisite: UQ_doctors_id_provider on dbo.doctors (id, provider_id),
added by e7c1d4a9b2f6 or Database_latest/01_ehr_schema.sql, the target of
the doctor foreign key. Script 08 reports whether it exists; without it the
upgrade fails and rolls back (transactional DDL).
"""

from typing import (
    Sequence,
    Union,
)

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql


revision: str = "c3d9e6a2f8b1"
down_revision: Union[
    str,
    Sequence[str],
    None,
] = "a8c2e5f1b7d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Target of the composite reviewer foreign key below.
    op.create_unique_constraint(
        "uq_provider_memberships_id_user_provider",
        "provider_memberships",
        ["id", "user_id", "provider_id"],
    )

    op.create_table(
        "doctor_verification_decisions",
        sa.Column("id", mssql.UNIQUEIDENTIFIER(), server_default=sa.text("NEWID()"), nullable=False),
        sa.Column("provider_id", mssql.UNIQUEIDENTIFIER(), nullable=False),
        sa.Column("doctor_id", mssql.UNIQUEIDENTIFIER(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("previous_status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Unicode(length=500), nullable=True),
        sa.Column("reviewer_user_id", mssql.UNIQUEIDENTIFIER(), nullable=False),
        sa.Column("reviewer_membership_id", mssql.UNIQUEIDENTIFIER(), nullable=False),
        sa.Column(
            "decided_at",
            mssql.DATETIMEOFFSET(),
            server_default=sa.text("TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00')"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="PK_doctor_verification_decisions"),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["providers.id"],
            name="FK_doctor_verification_decisions_provider",
        ),
        sa.ForeignKeyConstraint(
            ["doctor_id", "provider_id"],
            ["doctors.id", "doctors.provider_id"],
            name="FK_doctor_verification_decisions_doctor_provider",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_membership_id", "reviewer_user_id", "provider_id"],
            ["provider_memberships.id", "provider_memberships.user_id", "provider_memberships.provider_id"],
            name="FK_doctor_verification_decisions_reviewer_membership",
        ),
        sa.CheckConstraint(
            "decision IN ('verified', 'rejected', 'resubmitted')",
            name="CK_doctor_verification_decisions_decision",
        ),
        sa.CheckConstraint(
            "previous_status IN ('pending', 'verified', 'rejected')",
            name="CK_doctor_verification_decisions_previous_status",
        ),
        sa.CheckConstraint(
            "(decision = 'rejected' AND reason IS NOT NULL AND LEN(LTRIM(RTRIM(reason))) > 0) "
            "OR (decision <> 'rejected' AND reason IS NULL)",
            name="CK_doctor_verification_decisions_reason",
        ),
    )

    op.create_index(
        "IX_doctor_verification_decisions_provider_doctor_decided",
        "doctor_verification_decisions",
        ["provider_id", "doctor_id", "decided_at"],
        unique=False,
    )


def downgrade() -> None:
    # Reverse order: the table (and its foreign keys) before the unique key
    # it references. Deletes all decision history.
    op.drop_index(
        "IX_doctor_verification_decisions_provider_doctor_decided",
        table_name="doctor_verification_decisions",
    )
    op.drop_table("doctor_verification_decisions")
    op.drop_constraint(
        "uq_provider_memberships_id_user_provider",
        "provider_memberships",
        type_="unique",
    )
