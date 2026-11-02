"""add persisted diagnostic cases

Revision ID: e8b12a60c941
Revises: a5e30b966d98
Create Date: 2026-11-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql


revision: str = "e8b12a60c941"
down_revision: Union[str, Sequence[str], None] = "a5e30b966d98"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "diagnostic_cases",
        sa.Column("id", mssql.UNIQUEIDENTIFIER(), nullable=False, server_default=sa.text("NEWID()")),
        sa.Column("provider_id", mssql.UNIQUEIDENTIFIER(), nullable=False),
        sa.Column("patient_id", mssql.UNIQUEIDENTIFIER(), nullable=True),
        sa.Column("encounter_id", mssql.UNIQUEIDENTIFIER(), nullable=True),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("complaint", sa.Unicode(4000), nullable=False, server_default=sa.text("''")),
        sa.Column("answers_json", sa.Unicode(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("summary_json", sa.Unicode(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'in_progress'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("SYSUTCDATETIME()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("SYSUTCDATETIME()")),
        sa.PrimaryKeyConstraint("id", name="PK_diagnostic_cases"),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], name="FK_diagnostic_cases_provider"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], name="FK_diagnostic_cases_patient"),
        sa.ForeignKeyConstraint(["encounter_id"], ["ehr_encounters.id"], name="FK_diagnostic_cases_encounter"),
        sa.UniqueConstraint("provider_id", "session_id", name="UQ_diagnostic_cases_provider_session"),
    )
    op.create_index("IX_diagnostic_cases_patient_created", "diagnostic_cases", ["patient_id", "created_at"])


def downgrade() -> None:
    op.drop_index("IX_diagnostic_cases_patient_created", table_name="diagnostic_cases")
    op.drop_table("diagnostic_cases")
