"""add idempotency requests

Revision ID: ba15eb2c5b9f
Revises: c2f41e7b9d30
Create Date: 2026-08-08 20:39:55.196992

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ba15eb2c5b9f'
down_revision: Union[str, Sequence[str], None] = 'c2f41e7b9d30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.create_table(
        "idempotency_requests",

        sa.Column(
            "id",
            sa.String(length=36),
            nullable=False,
        ),

        sa.Column(
            "tenant_id",
            sa.String(length=100),
            nullable=False,
        ),

        sa.Column(
            "operation",
            sa.String(length=50),
            nullable=False,
        ),

        sa.Column(
            "idempotency_key",
            sa.String(length=128),
            nullable=False,
        ),

        sa.Column(
            "request_hash",
            sa.String(length=64),
            nullable=False,
        ),

        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text(
                "'pending'"
            ),
        ),

        sa.Column(
            "response_body",
            sa.UnicodeText(),
            nullable=True,
        ),

        sa.Column(
            "error_code",
            sa.String(length=100),
            nullable=True,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(
                timezone=True
            ),
            nullable=False,
            server_default=sa.text(
                "CURRENT_TIMESTAMP"
            ),
        ),

        sa.Column(
            "completed_at",
            sa.DateTime(
                timezone=True
            ),
            nullable=True,
        ),

        sa.PrimaryKeyConstraint(
            "id",
            name=(
                "pk_idempotency_requests"
            ),
        ),

        sa.UniqueConstraint(
            "tenant_id",
            "operation",
            "idempotency_key",
            name=(
                "uq_idempotency_"
                "tenant_operation_key"
            ),
        ),
    )

    op.create_index(
        "ix_idempotency_created_at",
        "idempotency_requests",
        [
            "created_at",
        ],
        unique=False,
    )


def downgrade() -> None:

    op.drop_index(
        "ix_idempotency_created_at",
        table_name=(
            "idempotency_requests"
        ),
    )

    op.drop_table(
        "idempotency_requests"
    )
