"""add staff auth models

Revision ID: 4cfaa1f51cc6
Revises: 7b9ccfa58157
Create Date: 2026-09-17 17:36:31.272349
"""

from typing import (
    Sequence,
    Union,
)

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql


revision: str = "4cfaa1f51cc6"

down_revision: Union[
    str,
    Sequence[str],
    None,
] = "7b9ccfa58157"

branch_labels = None
depends_on = None


def upgrade() -> None:

    # ========================================================
    # USER ACCOUNTS
    # ========================================================

    op.create_table(
        "user_accounts",

        sa.Column(
            "id",
            mssql.UNIQUEIDENTIFIER(),
            server_default=sa.text(
                "NEWID()"
            ),
            nullable=False,
        ),

        sa.Column(
            "email",
            sa.String(length=254),
            nullable=False,
        ),

        sa.Column(
            "password_hash",
            sa.String(length=255),
            nullable=False,
        ),

        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("1"),
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

        sa.Column(
            "updated_at",
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
            name="pk_user_accounts",
        ),

        sa.UniqueConstraint(
            "email",
            name="uq_user_accounts_email",
        ),
    )

    # ========================================================
    # PROVIDER MEMBERSHIPS
    # ========================================================

    op.create_table(
        "provider_memberships",

        sa.Column(
            "id",
            mssql.UNIQUEIDENTIFIER(),
            server_default=sa.text(
                "NEWID()"
            ),
            nullable=False,
        ),

        sa.Column(
            "user_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=False,
        ),

        sa.Column(
            "provider_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=False,
        ),

        sa.Column(
            "role",
            sa.String(length=30),
            nullable=False,
        ),

        sa.Column(
            "doctor_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=True,
        ),

        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("1"),
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

        sa.Column(
            "updated_at",
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
            name="pk_provider_memberships",
        ),

        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_accounts.id"],
            name=(
                "fk_provider_memberships_"
                "user_account"
            ),
        ),

        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["providers.id"],
            name=(
                "fk_provider_memberships_"
                "provider"
            ),
        ),

        sa.ForeignKeyConstraint(
            ["doctor_id"],
            ["doctors.id"],
            name=(
                "fk_provider_memberships_"
                "doctor"
            ),
        ),

        sa.UniqueConstraint(
            "user_id",
            "provider_id",
            name=(
                "uq_provider_memberships_"
                "user_provider"
            ),
        ),

        sa.CheckConstraint(
            "role IN ("
            "'provider_admin', "
            "'doctor', "
            "'receptionist', "
            "'lab_staff'"
            ")",
            name=(
                "ck_provider_memberships_role"
            ),
        ),

        sa.CheckConstraint(
            "("
            "role = 'doctor' "
            "AND doctor_id IS NOT NULL"
            ") OR ("
            "role <> 'doctor' "
            "AND doctor_id IS NULL"
            ")",
            name=(
                "ck_provider_memberships_"
                "doctor_role"
            ),
        ),
    )

    op.create_index(
        "ix_provider_memberships_provider",
        "provider_memberships",
        [
            "provider_id",
            "is_active",
        ],
        unique=False,
    )


def downgrade() -> None:

    op.drop_index(
        "ix_provider_memberships_provider",
        table_name=
            "provider_memberships",
    )

    op.drop_table(
        "provider_memberships"
    )

    op.drop_table(
        "user_accounts"
    )