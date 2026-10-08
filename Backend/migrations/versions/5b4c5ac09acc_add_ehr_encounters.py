"""add ehr encounters

Revision ID: 5b4c5ac09acc
Revises: b185226cd547
Create Date: 2026-10-04
"""

from typing import (
    Sequence,
    Union,
)

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql


revision: str = "5b4c5ac09acc"

down_revision: Union[
    str,
    Sequence[str],
    None,
] = "b185226cd547"

branch_labels = None
depends_on = None


def upgrade() -> None:

    # ========================================================
    # SHARED EHR ENCOUNTERS
    # ========================================================

    op.create_table(
        "ehr_encounters",

        sa.Column(
            "id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=False,
            server_default=sa.text(
                "NEWID()"
            ),
        ),

        # ----------------------------------------------------
        # Global patient identity.
        # ----------------------------------------------------

        sa.Column(
            "patient_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=False,
        ),

        # ----------------------------------------------------
        # Provider where this encounter occurred.
        # ----------------------------------------------------

        sa.Column(
            "provider_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=False,
        ),

        # ----------------------------------------------------
        # Optional clinical/provider context.
        # ----------------------------------------------------

        sa.Column(
            "doctor_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=True,
        ),

        sa.Column(
            "branch_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=True,
        ),

        # ----------------------------------------------------
        # Existing appointments table currently has no ORM
        # model in app.models.
        #
        # Keep the reference for now without a DB FK.
        # ----------------------------------------------------

        sa.Column(
            "appointment_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=True,
        ),

        sa.Column(
            "encounter_type",
            sa.String(
                length=30,
            ),
            nullable=False,
        ),

        sa.Column(
            "status",
            sa.String(
                length=20,
            ),
            nullable=False,
        ),

        sa.Column(
            "started_at",
            sa.DateTime(
                timezone=True,
            ),
            nullable=False,
        ),

        sa.Column(
            "ended_at",
            sa.DateTime(
                timezone=True,
            ),
            nullable=True,
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
            name="PK_ehr_encounters",
        ),

        sa.ForeignKeyConstraint(
            [
                "patient_id",
            ],
            [
                "patients.id",
            ],
            name=(
                "FK_ehr_encounters_patient"
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
                "FK_ehr_encounters_provider"
            ),
        ),

        sa.ForeignKeyConstraint(
            [
                "doctor_id",
            ],
            [
                "doctors.id",
            ],
            name=(
                "FK_ehr_encounters_doctor"
            ),
        ),

        sa.ForeignKeyConstraint(
            [
                "branch_id",
            ],
            [
                "branches.id",
            ],
            name=(
                "FK_ehr_encounters_branch"
            ),
        ),
    )

    # ========================================================
    # TIMELINE INDEXES
    # ========================================================

    op.create_index(
        "IX_ehr_encounters_patient_started",
        "ehr_encounters",
        [
            "patient_id",
            "started_at",
        ],
        unique=False,
    )

    op.create_index(
        "IX_ehr_encounters_provider_started",
        "ehr_encounters",
        [
            "provider_id",
            "started_at",
        ],
        unique=False,
    )


def downgrade() -> None:

    op.drop_index(
        "IX_ehr_encounters_provider_started",
        table_name="ehr_encounters",
    )

    op.drop_index(
        "IX_ehr_encounters_patient_started",
        table_name="ehr_encounters",
    )

    op.drop_table(
        "ehr_encounters"
    )