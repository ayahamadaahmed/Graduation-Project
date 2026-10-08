"""add service voice presentation

Revision ID: b185226cd547
Revises: 450bd59e69e1
Create Date: 2026-09-30
"""

from typing import (
    Sequence,
    Union,
)

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql


revision: str = "b185226cd547"

down_revision: Union[
    str,
    Sequence[str],
    None,
] = "450bd59e69e1"

branch_labels = None
depends_on = None


def upgrade() -> None:

    # ========================================================
    # SERVICE VOICE PRESENTATION
    # ========================================================

    op.add_column(
        "services",
        sa.Column(
            "voice_label_ar",
            mssql.NVARCHAR(
                length=160,
            ),
            nullable=True,
        ),
    )

    op.add_column(
        "services",
        sa.Column(
            "voice_label_en",
            mssql.NVARCHAR(
                length=160,
            ),
            nullable=True,
        ),
    )

    op.add_column(
        "services",
        sa.Column(
            "voice_featured_rank",
            sa.Integer(),
            nullable=True,
        ),
    )

    # NULL means the service is not featured in
    # the short Voice summary.
    #
    # Featured services use 1, 2, 3, ...
    # to define their spoken order.
    op.create_check_constraint(
        "ck_services_voice_featured_rank_positive",
        "services",
        (
            "voice_featured_rank IS NULL "
            "OR voice_featured_rank > 0"
        ),
    )


def downgrade() -> None:

    op.drop_constraint(
        "ck_services_voice_featured_rank_positive",
        "services",
        type_="check",
    )

    op.drop_column(
        "services",
        "voice_featured_rank",
    )

    op.drop_column(
        "services",
        "voice_label_en",
    )

    op.drop_column(
        "services",
        "voice_label_ar",
    )