"""add radiology reports and diagnostic assessments

Revision ID: a5e30b966d98
Revises: 01b9a3f5c254
Create Date: 2026-10-04 15:29:52.767904
"""

from typing import (
    Sequence,
    Union,
)

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql


# revision identifiers, used by Alembic.
revision: str = "a5e30b966d98"

down_revision: Union[
    str,
    Sequence[str],
    None,
] = "01b9a3f5c254"

branch_labels: Union[
    str,
    Sequence[str],
    None,
] = None

depends_on: Union[
    str,
    Sequence[str],
    None,
] = None


def upgrade() -> None:

    # ========================================================
    # RADIOLOGY REPORTS
    # ========================================================

    op.create_table(
        "radiology_reports",

        sa.Column(
            "id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=False,
            server_default=sa.text(
                "NEWID()"
            ),
        ),

        sa.Column(
            "patient_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=True,
        ),

        sa.Column(
            "provider_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=False,
        ),

        sa.Column(
            "encounter_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=True,
        ),

        sa.Column(
            "diagnostic_attachment_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=False,
        ),

        # chest_xray / brain_mri / kidney_ct
        sa.Column(
            "modality",
            sa.String(
                length=30,
            ),
            nullable=False,
        ),

        # pending / processing / processed / failed
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

        sa.PrimaryKeyConstraint(
            "id",
            name="PK_radiology_reports",
        ),

        sa.ForeignKeyConstraint(
            [
                "patient_id",
            ],
            [
                "patients.id",
            ],
            name="FK_radiology_reports_patient",
        ),

        sa.ForeignKeyConstraint(
            [
                "provider_id",
            ],
            [
                "providers.id",
            ],
            name="FK_radiology_reports_provider",
        ),

        sa.ForeignKeyConstraint(
            [
                "encounter_id",
            ],
            [
                "ehr_encounters.id",
            ],
            name="FK_radiology_reports_encounter",
        ),

        sa.ForeignKeyConstraint(
            [
                "diagnostic_attachment_id",
            ],
            [
                "diagnostic_attachments.id",
            ],
            name=(
                "FK_radiology_reports_"
                "diagnostic_attachment"
            ),
        ),

        sa.UniqueConstraint(
            "diagnostic_attachment_id",
            name=(
                "UQ_radiology_reports_"
                "diagnostic_attachment"
            ),
        ),
    )

    # ========================================================
    # RADIOLOGY REPORT INDEXES
    # ========================================================

    op.create_index(
        "IX_radiology_reports_patient_created",
        "radiology_reports",
        [
            "patient_id",
            "created_at",
        ],
        unique=False,
    )

    op.create_index(
        "IX_radiology_reports_provider_created",
        "radiology_reports",
        [
            "provider_id",
            "created_at",
        ],
        unique=False,
    )

    # ========================================================
    # DIAGNOSTIC ASSESSMENTS
    # ========================================================

    op.create_table(
        "diagnostic_assessments",

        sa.Column(
            "id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=False,
            server_default=sa.text(
                "NEWID()"
            ),
        ),

        sa.Column(
            "radiology_report_id",
            mssql.UNIQUEIDENTIFIER(),
            nullable=False,
        ),

        sa.Column(
            "assessment_type",
            sa.String(
                length=30,
            ),
            nullable=False,
            server_default=sa.text(
                "'radiology_model'"
            ),
        ),

        sa.Column(
            "classification",
            sa.String(
                length=100,
            ),
            nullable=False,
        ),

        # JSON object containing class probabilities.
        sa.Column(
            "probabilities_json",
            sa.UnicodeText(),
            nullable=False,
        ),

        sa.Column(
            "confidence",
            sa.Numeric(
                precision=9,
                scale=8,
            ),
            nullable=False,
        ),

        sa.Column(
            "inference_latency_ms",
            sa.Numeric(
                precision=12,
                scale=3,
            ),
            nullable=False,
        ),

        sa.Column(
            "model_name",
            sa.Unicode(
                length=150,
            ),
            nullable=False,
        ),

        sa.Column(
            "model_version",
            sa.Unicode(
                length=100,
            ),
            nullable=False,
        ),

        # JSON array containing limitations.
        sa.Column(
            "limitations_json",
            sa.UnicodeText(),
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

        sa.PrimaryKeyConstraint(
            "id",
            name="PK_diagnostic_assessments",
        ),

        sa.ForeignKeyConstraint(
            [
                "radiology_report_id",
            ],
            [
                "radiology_reports.id",
            ],
            name=(
                "FK_diagnostic_assessments_"
                "radiology_report"
            ),
        ),

        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=(
                "CK_diagnostic_assessments_"
                "confidence"
            ),
        ),

        sa.CheckConstraint(
            "inference_latency_ms >= 0",
            name=(
                "CK_diagnostic_assessments_"
                "latency"
            ),
        ),
    )

    # ========================================================
    # DIAGNOSTIC ASSESSMENT INDEXES
    # ========================================================

    op.create_index(
        "IX_diagnostic_assessments_report_created",
        "diagnostic_assessments",
        [
            "radiology_report_id",
            "created_at",
        ],
        unique=False,
    )

    op.create_index(
        "IX_diagnostic_assessments_model",
        "diagnostic_assessments",
        [
            "model_name",
            "model_version",
        ],
        unique=False,
    )


def downgrade() -> None:

    # ========================================================
    # DIAGNOSTIC ASSESSMENTS
    # ========================================================

    op.drop_index(
        "IX_diagnostic_assessments_model",
        table_name=(
            "diagnostic_assessments"
        ),
    )

    op.drop_index(
        "IX_diagnostic_assessments_report_created",
        table_name=(
            "diagnostic_assessments"
        ),
    )

    op.drop_table(
        "diagnostic_assessments"
    )

    # ========================================================
    # RADIOLOGY REPORTS
    # ========================================================

    op.drop_index(
        "IX_radiology_reports_provider_created",
        table_name="radiology_reports",
    )

    op.drop_index(
        "IX_radiology_reports_patient_created",
        table_name="radiology_reports",
    )

    op.drop_table(
        "radiology_reports"
    )