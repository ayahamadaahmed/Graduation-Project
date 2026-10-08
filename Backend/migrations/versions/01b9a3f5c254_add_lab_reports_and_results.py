"""add lab reports and results

Revision ID: 01b9a3f5c254
Revises: 033ba7d18605
Create Date: 2026-10-04
"""

from typing import (
    Sequence,
    Union,
)

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql


revision: str = "01b9a3f5c254"

down_revision: Union[
    str,
    Sequence[str],
    None,
] = "033ba7d18605"

branch_labels = None
depends_on = None


def upgrade() -> None:

    # ========================================================
    # LAB REPORTS
    # ========================================================

    op.create_table(
        "lab_reports",

        sa.Column(
            "id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=False,
            server_default=sa.text(
                "NEWID()"
            ),
        ),

        # ----------------------------------------------------
        # Global patient.
        #
        # Nullable until National ID / patient identity
        # has been resolved.
        # ----------------------------------------------------

        sa.Column(
            "patient_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=True,
        ),

        # ----------------------------------------------------
        # Provider that supplied / owns this report.
        # ----------------------------------------------------

        sa.Column(
            "provider_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=False,
        ),

        # ----------------------------------------------------
        # Optional Shared EHR encounter.
        # ----------------------------------------------------

        sa.Column(
            "encounter_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=True,
        ),

        # ----------------------------------------------------
        # Original uploaded diagnostic attachment.
        # ----------------------------------------------------

        sa.Column(
            "diagnostic_attachment_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=False,
        ),

        # Examples:
        # cbc
        # glycemic
        # renal
        # liver
        # lipid
        sa.Column(
            "document_type",
            sa.String(
                length=50,
            ),
            nullable=True,
        ),

        # Extractor-level unreadable fields.
        # JSON text.
        sa.Column(
            "unreadable_fields_json",
            sa.UnicodeText(),
            nullable=True,
        ),

        # pending
        # processing
        # processed
        # failed
        sa.Column(
            "status",
            sa.String(
                length=20,
            ),
            nullable=False,
            server_default=sa.text(
                "'pending'"
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
            name="PK_lab_reports",
        ),

        sa.UniqueConstraint(
            "diagnostic_attachment_id",
            name=(
                "UQ_lab_reports_diagnostic_attachment"
            ),
        ),

        sa.ForeignKeyConstraint(
            [
                "patient_id",
            ],
            [
                "patients.id",
            ],
            name="FK_lab_reports_patient",
        ),

        sa.ForeignKeyConstraint(
            [
                "provider_id",
            ],
            [
                "providers.id",
            ],
            name="FK_lab_reports_provider",
        ),

        sa.ForeignKeyConstraint(
            [
                "encounter_id",
            ],
            [
                "ehr_encounters.id",
            ],
            name="FK_lab_reports_encounter",
        ),

        sa.ForeignKeyConstraint(
            [
                "diagnostic_attachment_id",
            ],
            [
                "diagnostic_attachments.id",
            ],
            name=(
                "FK_lab_reports_diagnostic_attachment"
            ),
        ),
    )

    # ========================================================
    # LAB REPORT INDEXES
    # ========================================================

    op.create_index(
        "IX_lab_reports_patient_created",
        "lab_reports",
        [
            "patient_id",
            "created_at",
        ],
        unique=False,
    )

    op.create_index(
        "IX_lab_reports_provider_created",
        "lab_reports",
        [
            "provider_id",
            "created_at",
        ],
        unique=False,
    )

    # ========================================================
    # LAB RESULTS
    # ========================================================

    op.create_table(
        "lab_results",

        sa.Column(
            "id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=False,
            server_default=sa.text(
                "NEWID()"
            ),
        ),

        sa.Column(
            "lab_report_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=False,
        ),

        # Original order in the uploaded report.
        sa.Column(
            "result_index",
            sa.Integer(),
            nullable=False,
        ),

        # cbc / renal / glycemic / liver / lipid
        #
        # NULL for an unmapped result.
        sa.Column(
            "panel",
            sa.String(
                length=30,
            ),
            nullable=True,
        ),

        # Original extracted name.
        # Example: HGB
        sa.Column(
            "raw_name",
            mssql.NVARCHAR(
                length=200,
            ),
            nullable=False,
        ),

        # Normalized MedMind name.
        # Example: hemoglobin
        sa.Column(
            "canonical_name",
            sa.String(
                length=100,
            ),
            nullable=True,
        ),

        sa.Column(
            "value",
            sa.Numeric(
                precision=18,
                scale=6,
            ),
            nullable=True,
        ),

        sa.Column(
            "unit",
            mssql.NVARCHAR(
                length=50,
            ),
            nullable=True,
        ),

        sa.Column(
            "reference_min",
            sa.Numeric(
                precision=18,
                scale=6,
            ),
            nullable=True,
        ),

        sa.Column(
            "reference_max",
            sa.Numeric(
                precision=18,
                scale=6,
            ),
            nullable=True,
        ),

        # Preserve report-provided range text.
        #
        # Examples:
        # 12 - 16
        # < 5.7
        sa.Column(
            "reference_text",
            mssql.NVARCHAR(
                length=200,
            ),
            nullable=True,
        ),

        # low / normal / high / unknown
        sa.Column(
            "flag",
            sa.String(
                length=20,
            ),
            nullable=False,
            server_default=sa.text(
                "'unknown'"
            ),
        ),

        # mapped / unmapped / unreadable
        sa.Column(
            "mapping_status",
            sa.String(
                length=20,
            ),
            nullable=False,
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

        # ----------------------------------------------------
        # Constraints
        # ----------------------------------------------------

        sa.PrimaryKeyConstraint(
            "id",
            name="PK_lab_results",
        ),

        sa.ForeignKeyConstraint(
            [
                "lab_report_id",
            ],
            [
                "lab_reports.id",
            ],
            name="FK_lab_results_report",
        ),

        sa.UniqueConstraint(
            "lab_report_id",
            "result_index",
            name=(
                "UQ_lab_results_report_index"
            ),
        ),
    )

    # ========================================================
    # LAB RESULT INDEXES
    # ========================================================

    op.create_index(
        "IX_lab_results_report",
        "lab_results",
        [
            "lab_report_id",
        ],
        unique=False,
    )

    op.create_index(
        "IX_lab_results_canonical_name",
        "lab_results",
        [
            "canonical_name",
        ],
        unique=False,
    )


def downgrade() -> None:

    # ========================================================
    # LAB RESULTS
    # ========================================================

    op.drop_index(
        "IX_lab_results_canonical_name",
        table_name="lab_results",
    )

    op.drop_index(
        "IX_lab_results_report",
        table_name="lab_results",
    )

    op.drop_table(
        "lab_results"
    )

    # ========================================================
    # LAB REPORTS
    # ========================================================

    op.drop_index(
        "IX_lab_reports_provider_created",
        table_name="lab_reports",
    )

    op.drop_index(
        "IX_lab_reports_patient_created",
        table_name="lab_reports",
    )

    op.drop_table(
        "lab_reports"
    )