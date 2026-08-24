"""fix idempotency created at utc

Revision ID: 7b9ccfa58157
Revises: ba15eb2c5b9f
Create Date: 2026-08-10 17:15:36.900621

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7b9ccfa58157'
down_revision: Union[str, Sequence[str], None] = 'ba15eb2c5b9f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None





def upgrade() -> None:

    op.execute(
        """
        DECLARE @constraint_name sysname;

        SELECT
            @constraint_name = dc.name
        FROM sys.default_constraints AS dc
        INNER JOIN sys.columns AS c
            ON c.default_object_id = dc.object_id
        INNER JOIN sys.tables AS t
            ON t.object_id = c.object_id
        INNER JOIN sys.schemas AS s
            ON s.schema_id = t.schema_id
        WHERE
            s.name = 'dbo'
            AND t.name = 'idempotency_requests'
            AND c.name = 'created_at';

        IF @constraint_name IS NOT NULL
        BEGIN
            EXEC(
                'ALTER TABLE '
                + 'dbo.idempotency_requests '
                + 'DROP CONSTRAINT ['
                + @constraint_name
                + ']'
            );
        END;

        ALTER TABLE dbo.idempotency_requests
        ADD CONSTRAINT
            DF_idempotency_requests_created_at
        DEFAULT (
            TODATETIMEOFFSET(
                SYSUTCDATETIME(),
                '+00:00'
            )
        )
        FOR created_at;
        """
    )


def downgrade() -> None:

    op.execute(
        """
        DECLARE @constraint_name sysname;

        SELECT
            @constraint_name = dc.name
        FROM sys.default_constraints AS dc
        INNER JOIN sys.columns AS c
            ON c.default_object_id = dc.object_id
        INNER JOIN sys.tables AS t
            ON t.object_id = c.object_id
        INNER JOIN sys.schemas AS s
            ON s.schema_id = t.schema_id
        WHERE
            s.name = 'dbo'
            AND t.name = 'idempotency_requests'
            AND c.name = 'created_at';

        IF @constraint_name IS NOT NULL
        BEGIN
            EXEC(
                'ALTER TABLE '
                + 'dbo.idempotency_requests '
                + 'DROP CONSTRAINT ['
                + @constraint_name
                + ']'
            );
        END;

        ALTER TABLE dbo.idempotency_requests
        ADD DEFAULT (
            CURRENT_TIMESTAMP
        )
        FOR created_at;
        """
    )
