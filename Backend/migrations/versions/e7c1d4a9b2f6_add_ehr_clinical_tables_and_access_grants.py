"""add ehr clinical tables and cross-provider access grants

Revision ID: e7c1d4a9b2f6
Revises: a5e30b966d98
Create Date: 2026-10-12 09:00:00.000000

Adds the patient medical-record tables (conditions, allergies, medications,
clinical notes) and explicit cross-provider access grants, plus the composite
keys that force every EHR row to agree on provider / patient / doctor / encounter.

This migration mirrors Database_Sprint/01_ehr_schema.sql and is IDEMPOTENT:
every object is created only if it does not already exist, so it is safe to run
on a database where that SQL script was already applied (the script and this
migration use the same object names).

Composite foreign keys on EXISTING tables are added only when the current data
already satisfies them; otherwise a warning is printed and that key is skipped
(the integrity-check script lists the offending rows).
"""

from typing import (
    Sequence,
    Union,
)

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql

# revision identifiers, used by Alembic.
revision: str = "e7c1d4a9b2f6"
down_revision: Union[str, Sequence[str], None] = "a5e30b966d98"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ------------------------------------------------------------
# helpers
# ------------------------------------------------------------
def _offline() -> bool:
    return context.is_offline_mode()


def _object_exists(name: str) -> bool:
    """True if a table / constraint / trigger / view with this name exists."""

    if _offline():
        return False

    row = op.get_bind().execute(
        sa.text("SELECT 1 FROM sys.objects WHERE name = :name"),
        {"name": name},
    ).first()

    return row is not None


def _has_violations(sql: str) -> bool:
    if _offline():
        return False

    return op.get_bind().execute(sa.text(sql)).first() is not None


def _add_unique_if_missing(name: str, table: str, columns: list[str]) -> None:
    if _object_exists(name):
        return

    op.create_unique_constraint(name, table, columns)


def _add_composite_fk_if_clean(
    name: str,
    table: str,
    ref_table: str,
    local_cols: list[str],
    remote_cols: list[str],
    violation_sql: str,
) -> None:
    """Add a composite FK to an existing table only if current rows satisfy it."""

    if _object_exists(name):
        return

    if _has_violations(violation_sql):
        print(f"WARNING: skipped {name}: existing rows in {table} violate it. Run 04_integrity_and_tenant_checks.sql.")
        return

    op.create_foreign_key(name, table, ref_table, local_cols, remote_cols)


def _timestamp(name: str) -> sa.Column:
    return sa.Column(
        name,
        mssql.DATETIMEOFFSET(),
        nullable=False,
        server_default=sa.text("SYSUTCDATETIME()"),
    )


def _id() -> sa.Column:
    return sa.Column(
        "id",
        mssql.UNIQUEIDENTIFIER(),
        nullable=False,
        server_default=sa.text("NEWID()"),
    )


def _uuid(name: str, nullable: bool) -> sa.Column:
    return sa.Column(name, mssql.UNIQUEIDENTIFIER(), nullable=nullable)


def _profile_fk(table: str, provider_col: str = "provider_id") -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["patient_id", provider_col],
        ["patient_provider_profiles.patient_id", "patient_provider_profiles.provider_id"],
        name=f"FK_{table}_profile",
    )


def _encounter_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["encounter_id", "provider_id", "patient_id"],
        ["ehr_encounters.id", "ehr_encounters.provider_id", "ehr_encounters.patient_id"],
        name=f"FK_{table}_encounter",
    )


def _doctor_fk(table: str, doctor_col: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [doctor_col, "provider_id"],
        ["doctors.id", "doctors.provider_id"],
        name=f"FK_{table}_doctor",
    )


# ------------------------------------------------------------
# upgrade
# ------------------------------------------------------------
def upgrade() -> None:
    # ========================================================
    # 1. Composite unique keys on existing tables
    #    (targets for the composite foreign keys below)
    # ========================================================
    _add_unique_if_missing("UQ_doctors_id_provider", "doctors", ["id", "provider_id"])
    _add_unique_if_missing("UQ_branches_id_provider", "branches", ["id", "provider_id"])
    _add_unique_if_missing("UQ_appointments_id_provider", "appointments", ["id", "provider_id"])
    _add_unique_if_missing(
        "UQ_ehr_encounters_id_provider_patient",
        "ehr_encounters",
        ["id", "provider_id", "patient_id"],
    )

    # ========================================================
    # 2. Composite foreign keys on existing tables
    # ========================================================
    _add_composite_fk_if_clean(
        "FK_ehr_encounters_doctor_provider",
        "ehr_encounters",
        "doctors",
        ["doctor_id", "provider_id"],
        ["id", "provider_id"],
        "SELECT TOP 1 1 FROM dbo.ehr_encounters e WHERE e.doctor_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM dbo.doctors d WHERE d.id = e.doctor_id AND d.provider_id = e.provider_id)",
    )
    _add_composite_fk_if_clean(
        "FK_ehr_encounters_branch_provider",
        "ehr_encounters",
        "branches",
        ["branch_id", "provider_id"],
        ["id", "provider_id"],
        "SELECT TOP 1 1 FROM dbo.ehr_encounters e WHERE e.branch_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM dbo.branches b WHERE b.id = e.branch_id AND b.provider_id = e.provider_id)",
    )
    _add_composite_fk_if_clean(
        "FK_ehr_encounters_appointment_provider",
        "ehr_encounters",
        "appointments",
        ["appointment_id", "provider_id"],
        ["id", "provider_id"],
        "SELECT TOP 1 1 FROM dbo.ehr_encounters e WHERE e.appointment_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM dbo.appointments a WHERE a.id = e.appointment_id AND a.provider_id = e.provider_id)",
    )

    for table in ("lab_reports", "radiology_reports", "diagnostic_attachments"):
        _add_composite_fk_if_clean(
            f"FK_{table}_encounter_provider_patient",
            table,
            "ehr_encounters",
            ["encounter_id", "provider_id", "patient_id"],
            ["id", "provider_id", "patient_id"],
            f"SELECT TOP 1 1 FROM dbo.{table} r WHERE r.encounter_id IS NOT NULL AND r.patient_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM dbo.ehr_encounters e "
            "WHERE e.id = r.encounter_id AND e.provider_id = r.provider_id AND e.patient_id = r.patient_id)",
        )

    # ========================================================
    # 3. patient_conditions
    # ========================================================
    if not _object_exists("patient_conditions"):
        op.create_table(
            "patient_conditions",
            _id(),
            _uuid("provider_id", False),
            _uuid("patient_id", False),
            _uuid("encounter_id", True),
            _uuid("recorded_by_doctor_id", True),
            sa.Column("condition_name", sa.Unicode(200), nullable=False),
            sa.Column("icd10_code", sa.String(10), nullable=True),
            # active / resolved / inactive
            sa.Column("clinical_status", sa.String(20), nullable=False, server_default=sa.text("'active'")),
            # mild / moderate / severe
            sa.Column("severity", sa.String(20), nullable=True),
            sa.Column("onset_date", sa.Date(), nullable=True),
            sa.Column("resolved_date", sa.Date(), nullable=True),
            sa.Column("notes", sa.Unicode(1000), nullable=True),
            _timestamp("created_at"),
            _timestamp("updated_at"),
            sa.PrimaryKeyConstraint("id", name="PK_patient_conditions"),
            _profile_fk("patient_conditions"),
            _encounter_fk("patient_conditions"),
            _doctor_fk("patient_conditions", "recorded_by_doctor_id"),
            sa.CheckConstraint("clinical_status IN ('active','resolved','inactive')", name="CK_patient_conditions_status"),
            sa.CheckConstraint("severity IS NULL OR severity IN ('mild','moderate','severe')", name="CK_patient_conditions_severity"),
            sa.CheckConstraint("resolved_date IS NULL OR onset_date IS NULL OR resolved_date >= onset_date", name="CK_patient_conditions_dates"),
            sa.CheckConstraint("clinical_status <> 'resolved' OR resolved_date IS NOT NULL", name="CK_patient_conditions_resolved"),
        )
        op.create_index("IX_patient_conditions_patient", "patient_conditions", ["provider_id", "patient_id", "clinical_status"])

    # ========================================================
    # 4. patient_allergies
    # ========================================================
    if not _object_exists("patient_allergies"):
        op.create_table(
            "patient_allergies",
            _id(),
            _uuid("provider_id", False),
            _uuid("patient_id", False),
            _uuid("encounter_id", True),
            _uuid("recorded_by_doctor_id", True),
            sa.Column("allergen", sa.Unicode(200), nullable=False),
            # drug / food / environmental / other
            sa.Column("allergen_type", sa.String(20), nullable=False),
            sa.Column("reaction", sa.Unicode(300), nullable=True),
            # mild / moderate / severe / life_threatening
            sa.Column("severity", sa.String(20), nullable=False, server_default=sa.text("'mild'")),
            # active / inactive / resolved
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'active'")),
            sa.Column("noted_date", sa.Date(), nullable=True),
            _timestamp("created_at"),
            _timestamp("updated_at"),
            sa.PrimaryKeyConstraint("id", name="PK_patient_allergies"),
            _profile_fk("patient_allergies"),
            _encounter_fk("patient_allergies"),
            _doctor_fk("patient_allergies", "recorded_by_doctor_id"),
            sa.CheckConstraint("allergen_type IN ('drug','food','environmental','other')", name="CK_patient_allergies_type"),
            sa.CheckConstraint("severity IN ('mild','moderate','severe','life_threatening')", name="CK_patient_allergies_severity"),
            sa.CheckConstraint("status IN ('active','inactive','resolved')", name="CK_patient_allergies_status"),
        )
        op.create_index("IX_patient_allergies_patient", "patient_allergies", ["provider_id", "patient_id", "status"])

    # ========================================================
    # 5. patient_medications
    # ========================================================
    if not _object_exists("patient_medications"):
        op.create_table(
            "patient_medications",
            _id(),
            _uuid("provider_id", False),
            _uuid("patient_id", False),
            _uuid("encounter_id", True),
            _uuid("prescribed_by_doctor_id", True),
            sa.Column("medication_name", sa.Unicode(200), nullable=False),
            sa.Column("dosage", sa.Unicode(100), nullable=True),
            sa.Column("frequency", sa.Unicode(100), nullable=True),
            sa.Column("route", sa.String(30), nullable=True),
            sa.Column("start_date", sa.Date(), nullable=True),
            sa.Column("end_date", sa.Date(), nullable=True),
            # active / completed / stopped
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'active'")),
            sa.Column("notes", sa.Unicode(500), nullable=True),
            _timestamp("created_at"),
            _timestamp("updated_at"),
            sa.PrimaryKeyConstraint("id", name="PK_patient_medications"),
            _profile_fk("patient_medications"),
            _encounter_fk("patient_medications"),
            _doctor_fk("patient_medications", "prescribed_by_doctor_id"),
            sa.CheckConstraint("status IN ('active','completed','stopped')", name="CK_patient_medications_status"),
            sa.CheckConstraint("end_date IS NULL OR start_date IS NULL OR end_date >= start_date", name="CK_patient_medications_dates"),
        )
        op.create_index("IX_patient_medications_patient", "patient_medications", ["provider_id", "patient_id", "status"])

    # ========================================================
    # 6. clinical_notes
    # ========================================================
    if not _object_exists("clinical_notes"):
        op.create_table(
            "clinical_notes",
            _id(),
            _uuid("provider_id", False),
            _uuid("patient_id", False),
            # every note belongs to a visit
            _uuid("encounter_id", False),
            # the author
            _uuid("doctor_id", False),
            # progress / consultation / soap / discharge / addendum
            sa.Column("note_type", sa.String(20), nullable=False, server_default=sa.text("'progress'")),
            sa.Column("title", sa.Unicode(200), nullable=True),
            # nvarchar(max), stated explicitly so offline (--sql) output is not NTEXT
            sa.Column("note_text", mssql.NVARCHAR(), nullable=False),
            # draft / signed
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'draft'")),
            sa.Column("signed_at", mssql.DATETIMEOFFSET(), nullable=True),
            _uuid("addendum_to_note_id", True),
            _timestamp("created_at"),
            _timestamp("updated_at"),
            sa.PrimaryKeyConstraint("id", name="PK_clinical_notes"),
            _profile_fk("clinical_notes"),
            _encounter_fk("clinical_notes"),
            _doctor_fk("clinical_notes", "doctor_id"),
            sa.ForeignKeyConstraint(["addendum_to_note_id"], ["clinical_notes.id"], name="FK_clinical_notes_addendum"),
            sa.CheckConstraint("note_type IN ('progress','consultation','soap','discharge','addendum')", name="CK_clinical_notes_type"),
            sa.CheckConstraint("status IN ('draft','signed')", name="CK_clinical_notes_status"),
            sa.CheckConstraint(
                "(status = 'signed' AND signed_at IS NOT NULL) OR (status = 'draft' AND signed_at IS NULL)",
                name="CK_clinical_notes_signed",
            ),
            sa.CheckConstraint("note_type <> 'addendum' OR addendum_to_note_id IS NOT NULL", name="CK_clinical_notes_addendum"),
        )
        # newest notes first, matching 01_ehr_schema.sql
        op.create_index(
            "IX_clinical_notes_patient",
            "clinical_notes",
            ["provider_id", "patient_id", sa.text("created_at DESC")],
        )
        op.create_index("IX_clinical_notes_encounter", "clinical_notes", ["encounter_id"])

    # ========================================================
    # 7. patient_access_grants
    # ========================================================
    if not _object_exists("patient_access_grants"):
        op.create_table(
            "patient_access_grants",
            _id(),
            _uuid("patient_id", False),
            # the provider that holds the records
            _uuid("owner_provider_id", False),
            # the provider allowed to read them
            _uuid("grantee_provider_id", False),
            # full_record / history_only / reports_only
            sa.Column("scope", sa.String(20), nullable=False, server_default=sa.text("'full_record'")),
            # patient / staff
            sa.Column("granted_by", sa.String(20), nullable=False, server_default=sa.text("'patient'")),
            _timestamp("granted_at"),
            sa.Column("expires_at", mssql.DATETIMEOFFSET(), nullable=True),
            sa.Column("revoked_at", mssql.DATETIMEOFFSET(), nullable=True),
            sa.Column("revoked_reason", sa.Unicode(300), nullable=True),
            _timestamp("created_at"),
            sa.PrimaryKeyConstraint("id", name="PK_patient_access_grants"),
            sa.ForeignKeyConstraint(
                ["patient_id", "owner_provider_id"],
                ["patient_provider_profiles.patient_id", "patient_provider_profiles.provider_id"],
                name="FK_patient_access_grants_owner_profile",
            ),
            sa.ForeignKeyConstraint(["grantee_provider_id"], ["providers.id"], name="FK_patient_access_grants_grantee"),
            sa.CheckConstraint("owner_provider_id <> grantee_provider_id", name="CK_patient_access_grants_distinct"),
            sa.CheckConstraint("scope IN ('full_record','history_only','reports_only')", name="CK_patient_access_grants_scope"),
            sa.CheckConstraint("granted_by IN ('patient','staff')", name="CK_patient_access_grants_by"),
            sa.CheckConstraint("expires_at IS NULL OR expires_at > granted_at", name="CK_patient_access_grants_expiry"),
            sa.CheckConstraint("revoked_at IS NULL OR revoked_at >= granted_at", name="CK_patient_access_grants_revoked"),
        )
        op.create_index(
            "UX_patient_access_grants_active",
            "patient_access_grants",
            ["patient_id", "owner_provider_id", "grantee_provider_id", "scope"],
            unique=True,
            mssql_where=sa.text("revoked_at IS NULL"),
        )
        op.create_index("IX_patient_access_grants_grantee", "patient_access_grants", ["grantee_provider_id", "patient_id"])

    # ========================================================
    # 8. Signed clinical notes are immutable (not representable in the ORM)
    # ========================================================
    op.execute(
        """
        CREATE OR ALTER TRIGGER dbo.TR_clinical_notes_protect_signed
        ON dbo.clinical_notes
        AFTER UPDATE, DELETE
        AS
        BEGIN
            SET NOCOUNT ON;
            IF EXISTS (
                SELECT 1
                FROM deleted d
                LEFT JOIN inserted i ON i.id = d.id
                WHERE d.status = 'signed'
                  AND (   i.id IS NULL
                       OR i.status <> d.status
                       OR i.note_text <> d.note_text
                       OR ISNULL(i.title, N'') <> ISNULL(d.title, N'')
                       OR i.encounter_id <> d.encounter_id
                       OR i.doctor_id <> d.doctor_id
                       OR i.patient_id <> d.patient_id
                       OR i.provider_id <> d.provider_id)
            )
            BEGIN
                RAISERROR(N'Signed clinical notes cannot be changed or deleted. Add an addendum note instead.', 16, 1);
                ROLLBACK TRANSACTION;
            END
        END
        """
    )

    # ========================================================
    # 9. Grants that are currently usable
    # ========================================================
    op.execute(
        """
        CREATE OR ALTER VIEW dbo.vw_active_access_grants
        AS
        SELECT g.id, g.patient_id, g.owner_provider_id, g.grantee_provider_id, g.scope, g.granted_at, g.expires_at
        FROM dbo.patient_access_grants g
        WHERE g.revoked_at IS NULL
          AND (g.expires_at IS NULL OR g.expires_at > SYSUTCDATETIME())
        """
    )


# ------------------------------------------------------------
# downgrade
# ------------------------------------------------------------
def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS dbo.vw_active_access_grants")
    op.execute("DROP TRIGGER IF EXISTS dbo.TR_clinical_notes_protect_signed")

    # dropping a table also drops its indexes and its own constraints
    for table in (
        "patient_access_grants",
        "clinical_notes",
        "patient_medications",
        "patient_allergies",
        "patient_conditions",
    ):
        op.execute(f"DROP TABLE IF EXISTS dbo.{table}")

    for table in ("lab_reports", "radiology_reports", "diagnostic_attachments"):
        name = f"FK_{table}_encounter_provider_patient"
        if _object_exists(name) or _offline():
            op.drop_constraint(name, table, type_="foreignkey")

    for name in (
        "FK_ehr_encounters_doctor_provider",
        "FK_ehr_encounters_branch_provider",
        "FK_ehr_encounters_appointment_provider",
    ):
        if _object_exists(name) or _offline():
            op.drop_constraint(name, "ehr_encounters", type_="foreignkey")

    for name, table in (
        ("UQ_ehr_encounters_id_provider_patient", "ehr_encounters"),
        ("UQ_appointments_id_provider", "appointments"),
        ("UQ_branches_id_provider", "branches"),
        ("UQ_doctors_id_provider", "doctors"),
    ):
        if _object_exists(name) or _offline():
            op.drop_constraint(name, table, type_="unique")
