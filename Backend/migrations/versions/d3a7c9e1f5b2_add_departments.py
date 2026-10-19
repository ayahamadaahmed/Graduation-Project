"""add departments

Revision ID: d3a7c9e1f5b2
Revises: f4b8d2c6a1e3
Create Date: 2026-10-14 12:00:00.000000

Adds the provider `departments` table (a dedicated entity, NOT a specialty).
A department is provider-wide (branch_id NULL) or belongs to one branch of the
same provider; the composite key to branches(id, provider_id) enforces that.
No data is inserted.
"""

from typing import (
    Sequence,
    Union,
)

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql


# revision identifiers, used by Alembic.
revision: str = "d3a7c9e1f5b2"
down_revision: Union[str, Sequence[str], None] = "f4b8d2c6a1e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", mssql.UNIQUEIDENTIFIER(), nullable=False, server_default=sa.text("NEWID()")),
        sa.Column("provider_id", mssql.UNIQUEIDENTIFIER(), nullable=False),
        sa.Column("branch_id", mssql.UNIQUEIDENTIFIER(), nullable=True),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name_ar", mssql.NVARCHAR(150), nullable=False),
        sa.Column("name_en", mssql.NVARCHAR(150), nullable=False),
        sa.Column("description_ar", mssql.NVARCHAR(1000), nullable=True),
        sa.Column("description_en", mssql.NVARCHAR(1000), nullable=True),
        sa.Column("phone", sa.String(30), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("SYSUTCDATETIME()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("SYSUTCDATETIME()")),
        sa.PrimaryKeyConstraint("id", name="PK_departments"),
        sa.UniqueConstraint("provider_id", "code", name="UQ_departments_provider_code"),
        sa.UniqueConstraint("id", "provider_id", name="UQ_departments_id_provider"),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], name="FK_departments_provider"),
        sa.ForeignKeyConstraint(
            ["branch_id", "provider_id"],
            ["branches.id", "branches.provider_id"],
            name="FK_departments_branch_provider",
        ),
    )
    op.create_index("IX_departments_provider_active", "departments", ["provider_id", "is_active"])
    op.create_index("IX_departments_provider_branch", "departments", ["provider_id", "branch_id"])


def downgrade() -> None:
    op.drop_index("IX_departments_provider_branch", table_name="departments")
    op.drop_index("IX_departments_provider_active", table_name="departments")
    op.drop_table("departments")
