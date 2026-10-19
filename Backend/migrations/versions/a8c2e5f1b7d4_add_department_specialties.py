"""add department specialties

Revision ID: a8c2e5f1b7d4
Revises: d3a7c9e1f5b2
Create Date: 2026-10-16 12:00:00.000000

Many-to-many link between departments and specialties. Adds the composite key
specialties(id, provider_id) (always satisfiable: `id` is the primary key) so
both sides of a link are forced to the same provider. No data is inserted.
"""

from typing import (
    Sequence,
    Union,
)

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql


# revision identifiers, used by Alembic.
revision: str = "a8c2e5f1b7d4"
down_revision: Union[str, Sequence[str], None] = "d3a7c9e1f5b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OWNER_PROPERTY = "medmind_created_by_revision"


def upgrade() -> None:
    # Idempotent: works online and in offline (--sql) mode. Only a key created
    # here is tagged, so downgrade never drops a pre-existing one.
    op.execute(
        "IF NOT EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = N'UQ_specialties_id_provider') "
        "BEGIN "
        "ALTER TABLE specialties ADD CONSTRAINT [UQ_specialties_id_provider] UNIQUE (id, provider_id); "
        "DECLARE @schema sysname = OBJECT_SCHEMA_NAME(OBJECT_ID(N'specialties')); "
        f"EXEC sys.sp_addextendedproperty @name = N'{_OWNER_PROPERTY}', @value = N'{revision}', "
        "@level0type = N'SCHEMA', @level0name = @schema, "
        "@level1type = N'TABLE', @level1name = N'specialties', "
        "@level2type = N'CONSTRAINT', @level2name = N'UQ_specialties_id_provider'; "
        "END"
    )
    op.create_table(
        "department_specialties",
        sa.Column("id", mssql.UNIQUEIDENTIFIER(), nullable=False, server_default=sa.text("NEWID()")),
        sa.Column("provider_id", mssql.UNIQUEIDENTIFIER(), nullable=False),
        sa.Column("department_id", mssql.UNIQUEIDENTIFIER(), nullable=False),
        sa.Column("specialty_id", mssql.UNIQUEIDENTIFIER(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("SYSUTCDATETIME()")),
        sa.PrimaryKeyConstraint("id", name="PK_department_specialties"),
        sa.UniqueConstraint(
            "department_id",
            "specialty_id",
            name="UQ_department_specialties_department_specialty",
        ),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], name="FK_department_specialties_provider"),
        sa.ForeignKeyConstraint(
            ["department_id", "provider_id"],
            ["departments.id", "departments.provider_id"],
            name="FK_department_specialties_department_provider",
        ),
        sa.ForeignKeyConstraint(
            ["specialty_id", "provider_id"],
            ["specialties.id", "specialties.provider_id"],
            name="FK_department_specialties_specialty_provider",
        ),
    )
    op.create_index(
        "IX_department_specialties_provider_specialty",
        "department_specialties",
        ["provider_id", "specialty_id"],
    )


def downgrade() -> None:
    op.drop_index("IX_department_specialties_provider_specialty", table_name="department_specialties")
    op.drop_table("department_specialties")
    # Drop the key only if this revision created it (its extended property goes with it).
    op.execute(
        "IF EXISTS ("
        "SELECT 1 FROM sys.key_constraints kc "
        "JOIN sys.extended_properties ep "
        "ON ep.class = 1 AND ep.major_id = kc.object_id AND ep.minor_id = 0 "
        "WHERE kc.name = N'UQ_specialties_id_provider' "
        f"AND ep.name = N'{_OWNER_PROPERTY}' AND CAST(ep.value AS nvarchar(100)) = N'{revision}'"
        ") "
        "ALTER TABLE specialties DROP CONSTRAINT [UQ_specialties_id_provider]"
    )
