"""add diagnostic attachments

Revision ID: 033ba7d18605
Revises: 5b4c5ac09acc
Create Date: 2026-10-04
"""

from typing import (
    Sequence,
    Union,
)

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql


revision: str = "033ba7d18605"

down_revision: Union[
    str,
    Sequence[str],
    None,
] = "5b4c5ac09acc"

branch_labels = None
depends_on = None


def upgrade() -> None:

    # ========================================================
    # DIAGNOSTIC ATTACHMENTS
    # ========================================================

    op.create_table(
        "diagnostic_attachments",

        sa.Column(
            "id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=False,
            server_default=sa.text(
                "NEWID()"
            ),
        ),

        # ----------------------------------------------------
        # Safe external identifier returned to clients.
        # ----------------------------------------------------

        sa.Column(
            "attachment_id",
            sa.String(
                length=32,
            ),
            nullable=False,
        ),

        # ----------------------------------------------------
        # Tenant / provider ownership.
        # ----------------------------------------------------

        sa.Column(
            "provider_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=False,
        ),

        # ----------------------------------------------------
        # May be unknown at initial upload time.
        # It can be linked after patient identity is resolved.
        # ----------------------------------------------------

        sa.Column(
            "patient_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=True,
        ),

        # ----------------------------------------------------
        # Optional EHR timeline link.
        # ----------------------------------------------------

        sa.Column(
            "encounter_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=True,
        ),

        sa.Column(
            "session_id",
            sa.String(
                length=128,
            ),
            nullable=False,
        ),

        sa.Column(
            "original_filename",
            mssql.NVARCHAR(
                length=255,
            ),
            nullable=False,
        ),

        sa.Column(
            "content_type",
            sa.String(
                length=100,
            ),
            nullable=False,
        ),

        sa.Column(
            "size_bytes",
            sa.BigInteger(),
            nullable=False,
        ),

        sa.Column(
            "sha256",
            sa.String(
                length=64,
            ),
            nullable=False,
        ),

        # ----------------------------------------------------
        # Internal storage reference.
        #
        # Never expose this field to API clients.
        # ----------------------------------------------------

        sa.Column(
            "storage_key",
            mssql.NVARCHAR(
                length=500,
            ),
            nullable=False,
        ),

        sa.Column(
            "status",
            sa.String(
                length=20,
            ),
            nullable=False,
            server_default=sa.text(
                "'stored'"
            ),
        ),

        sa.Column(
            "created_at",
            sa.DateTime(
                timezone=True,
            ),
            nullable=False,
            server_default=sa.text(
                "SYSUTCDATETIME()"
            ),
        ),

        sa.Column(
            "updated_at",
            sa.DateTime(
                timezone=True,
            ),
            nullable=False,
            server_default=sa.text(
                "SYSUTCDATETIME()"
            ),
        ),

        # ----------------------------------------------------
        # Constraints
        # ----------------------------------------------------

        sa.PrimaryKeyConstraint(
            "id",
            name="PK_diagnostic_attachments",
        ),

        sa.UniqueConstraint(
            "attachment_id",
            name=(
                "UQ_diagnostic_attachments_attachment_id"
            ),
        ),

        sa.ForeignKeyConstraint(
            [
                "provider_id",
            ],
            [
                "providers.id",
            ],
            name=(
                "FK_diagnostic_attachments_provider"
            ),
        ),

        sa.ForeignKeyConstraint(
            [
                "patient_id",
            ],
            [
                "patients.id",
            ],
            name=(
                "FK_diagnostic_attachments_patient"
            ),
        ),

        sa.ForeignKeyConstraint(
            [
                "encounter_id",
            ],
            [
                "ehr_encounters.id",
            ],
            name=(
                "FK_diagnostic_attachments_encounter"
            ),
        ),
    )

    # ========================================================
    # INDEXES
    # ========================================================

    op.create_index(
        "IX_diagnostic_attachments_patient_created",
        "diagnostic_attachments",
        [
            "patient_id",
            "created_at",
        ],
        unique=False,
    )

    op.create_index(
        "IX_diagnostic_attachments_provider_session",
        "diagnostic_attachments",
        [
            "provider_id",
            "session_id",
        ],
        unique=False,
    )


def downgrade() -> None:

    op.drop_index(
        "IX_diagnostic_attachments_provider_session",
        table_name="diagnostic_attachments",
    )

    op.drop_index(
        "IX_diagnostic_attachments_patient_created",
        table_name="diagnostic_attachments",
    )

    op.drop_table(
        "diagnostic_attachments"
    )