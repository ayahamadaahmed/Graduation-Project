"""allow lab booking without a doctor

Revision ID: f4b8d2c6a1e3
Revises: e7c1d4a9b2f6
Create Date: 2026-10-14 12:00:00.000000

Diagnostic labs book by branch + test, not by doctor. This makes
doctor_id nullable on doctor_working_hours, doctor_availability_slots
and appointments. A NULL doctor_id means a branch-level lab schedule /
slot / appointment; the application only allows that for providers with
org_type = 'diagnostic_lab' (a CHECK cannot see providers.org_type).

Uniqueness is split with filtered unique indexes:
  * doctor rows keep the old rule (doctor, date, start) / (doctor, branch, day, start);
  * lab rows are unique per (branch, date, start) / (branch, day, start).
A plain UNIQUE constraint would treat every NULL doctor as the same doctor.

SQL Server refuses ALTER COLUMN while an index, unique constraint or FK
covers the column, so those objects are dropped and recreated. The doctor
FKs were created unnamed (system-generated names), so they are looked up at
runtime and recreated with explicit names.

Filtered indexes require ANSI_NULLS and QUOTED_IDENTIFIER ON for writes
(the default for ODBC/pyodbc and SSMS; run sqlcmd with -I).
"""

from typing import (
    Sequence,
    Union,
)

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f4b8d2c6a1e3"
down_revision: Union[str, Sequence[str], None] = "e7c1d4a9b2f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DOCTOR_FK_NAMES = {
    "appointments": "FK_appointments_doctor",
    "doctor_availability_slots": "FK_availability_slots_doctor",
    "doctor_working_hours": "FK_working_hours_doctor",
}


# ------------------------------------------------------------
# helpers
# ------------------------------------------------------------
def _require_online() -> None:
    if context.is_offline_mode():
        raise RuntimeError(
            "f4b8d2c6a1e3 looks up system-named foreign keys and "
            "must run online (not with --sql)."
        )


def _doctor_fk_names(table: str) -> list[str]:
    """Names of the single-column doctor_id -> doctors(id) FKs on a table."""

    rows = op.get_bind().execute(
        sa.text(
            """
            SELECT fk.name
            FROM sys.foreign_keys AS fk
            JOIN sys.foreign_key_columns AS fkc
                ON fkc.constraint_object_id = fk.object_id
            WHERE fk.parent_object_id = OBJECT_ID(:table)
              AND fk.referenced_object_id = OBJECT_ID(N'dbo.doctors')
              AND COL_NAME(fkc.parent_object_id, fkc.parent_column_id) = N'doctor_id'
            GROUP BY fk.name
            HAVING COUNT(*) = 1
            """
        ),
        {"table": f"dbo.{table}"},
    ).all()

    return [row[0] for row in rows]


def _index_exists(table: str, name: str) -> bool:
    row = op.get_bind().execute(
        sa.text(
            "SELECT 1 FROM sys.indexes "
            "WHERE object_id = OBJECT_ID(:table) AND name = :name"
        ),
        {"table": f"dbo.{table}", "name": name},
    ).first()

    return row is not None


def _drop_doctor_fks() -> None:
    for table in DOCTOR_FK_NAMES:
        for name in _doctor_fk_names(table):
            op.drop_constraint(name, table, type_="foreignkey")


def _create_doctor_fks() -> None:
    for table, name in DOCTOR_FK_NAMES.items():
        op.create_foreign_key(name, table, "doctors", ["doctor_id"], ["id"])


def _set_doctor_nullable(nullable: bool) -> None:
    for table in DOCTOR_FK_NAMES:
        op.alter_column(
            table,
            "doctor_id",
            existing_type=sa.dialects.mssql.UNIQUEIDENTIFIER(),
            nullable=nullable,
        )


# ------------------------------------------------------------
# upgrade
# ------------------------------------------------------------
def upgrade() -> None:
    _require_online()

    # 1. Drop everything that covers doctor_id.
    _drop_doctor_fks()

    op.drop_index("IX_appointments_doctor_date", table_name="appointments")

    op.drop_constraint(
        "UQ_availability_slots_doctor_date_time",
        "doctor_availability_slots",
        type_="unique",
    )
    op.drop_index("IX_availability_slots_doctor_date", table_name="doctor_availability_slots")

    op.drop_constraint(
        "UQ_working_hours_doctor_branch_day_start",
        "doctor_working_hours",
        type_="unique",
    )
    op.drop_index("IX_working_hours_doctor_day", table_name="doctor_working_hours")

    # 2. Allow branch-level (doctor-less) rows.
    _set_doctor_nullable(True)

    # 3. Recreate FKs (now explicitly named) and lookup indexes.
    _create_doctor_fks()

    op.create_index(
        "IX_appointments_doctor_date",
        "appointments",
        ["doctor_id", "scheduled_date"],
    )
    op.create_index(
        "IX_availability_slots_doctor_date",
        "doctor_availability_slots",
        ["doctor_id", "slot_date", "start_time"],
    )
    op.create_index(
        "IX_working_hours_doctor_day",
        "doctor_working_hours",
        ["doctor_id", "day_of_week", "is_active"],
    )

    # 4. Split uniqueness: doctor rows vs branch-level lab rows.
    op.create_index(
        "UX_availability_slots_doctor_date_time",
        "doctor_availability_slots",
        ["doctor_id", "slot_date", "start_time"],
        unique=True,
        mssql_where=sa.text("doctor_id IS NOT NULL"),
    )
    op.create_index(
        "UX_availability_slots_branch_date_time",
        "doctor_availability_slots",
        ["branch_id", "slot_date", "start_time"],
        unique=True,
        mssql_where=sa.text("doctor_id IS NULL"),
    )
    op.create_index(
        "UX_working_hours_doctor_branch_day_start",
        "doctor_working_hours",
        ["doctor_id", "branch_id", "day_of_week", "start_time"],
        unique=True,
        mssql_where=sa.text("doctor_id IS NOT NULL"),
    )
    op.create_index(
        "UX_working_hours_branch_day_start",
        "doctor_working_hours",
        ["branch_id", "day_of_week", "start_time"],
        unique=True,
        mssql_where=sa.text("doctor_id IS NULL"),
    )


# ------------------------------------------------------------
# downgrade
# ------------------------------------------------------------
def downgrade() -> None:
    _require_online()

    # Refuse to silently delete lab bookings / schedules.
    for table in DOCTOR_FK_NAMES:
        row = op.get_bind().execute(
            sa.text(f"SELECT TOP 1 1 FROM dbo.{table} WHERE doctor_id IS NULL")
        ).first()

        if row is not None:
            raise RuntimeError(
                f"Cannot downgrade f4b8d2c6a1e3: dbo.{table} has rows "
                "without a doctor (lab bookings). Remove or reassign them first."
            )

    for table, name in (
        ("doctor_working_hours", "UX_working_hours_branch_day_start"),
        ("doctor_working_hours", "UX_working_hours_doctor_branch_day_start"),
        ("doctor_availability_slots", "UX_availability_slots_branch_date_time"),
        ("doctor_availability_slots", "UX_availability_slots_doctor_date_time"),
        ("doctor_working_hours", "IX_working_hours_doctor_day"),
        ("doctor_availability_slots", "IX_availability_slots_doctor_date"),
        ("appointments", "IX_appointments_doctor_date"),
    ):
        if _index_exists(table, name):
            op.drop_index(name, table_name=table)

    _drop_doctor_fks()

    _set_doctor_nullable(False)

    _create_doctor_fks()

    op.create_index(
        "IX_appointments_doctor_date",
        "appointments",
        ["doctor_id", "scheduled_date"],
    )
    op.create_unique_constraint(
        "UQ_availability_slots_doctor_date_time",
        "doctor_availability_slots",
        ["doctor_id", "slot_date", "start_time"],
    )
    op.create_index(
        "IX_availability_slots_doctor_date",
        "doctor_availability_slots",
        ["doctor_id", "slot_date", "start_time"],
    )
    op.create_unique_constraint(
        "UQ_working_hours_doctor_branch_day_start",
        "doctor_working_hours",
        ["doctor_id", "branch_id", "day_of_week", "start_time"],
    )
    op.create_index(
        "IX_working_hours_doctor_day",
        "doctor_working_hours",
        ["doctor_id", "day_of_week", "is_active"],
    )
