"""Departments: model, tenant-scoped catalog query, schema, migration (no database)."""

import importlib.util
import io
from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import mssql
from sqlalchemy.schema import CreateTable

from app.models import Department
from app.repositories.catalog_repository import CatalogRepository
from app.schemas.catalog import DepartmentOut
from app.services.catalog_service import CatalogService

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "migrations" / "versions" / "d3a7c9e1f5b2_add_departments.py"


class CapturingSession:
    def __init__(self):
        self.statement = None

    def scalars(self, statement):
        self.statement = statement
        return self

    def all(self):
        return []


def compiled_sql(statement) -> str:
    return str(statement.compile(dialect=mssql.dialect(), compile_kwargs={"literal_binds": True}))


def test_department_model_is_provider_scoped_with_optional_branch():
    table = Department.__table__
    assert table.name == "departments"
    assert table.c.provider_id.nullable is False
    assert table.c.branch_id.nullable is True
    names = {c.name for c in table.constraints}
    assert {"UQ_departments_provider_code", "UQ_departments_id_provider",
            "FK_departments_provider", "FK_departments_branch_provider"} <= names
    branch_fk = next(c for c in table.foreign_key_constraints if c.name == "FK_departments_branch_provider")
    assert [c.name for c in branch_fk.columns] == ["branch_id", "provider_id"]
    assert [e.target_fullname for e in branch_fk.elements] == ["branches.id", "branches.provider_id"]
    ddl = str(CreateTable(table).compile(dialect=mssql.dialect()))
    assert "FOREIGN KEY(branch_id, provider_id) REFERENCES branches (id, provider_id)" in ddl


def test_list_departments_filters_by_provider_and_active():
    session = CapturingSession()
    provider_id = uuid4()
    CatalogRepository(session).list_departments(provider_id)
    sql = compiled_sql(session.statement)
    assert "departments.provider_id = '" + str(provider_id) + "'" in sql
    assert "departments.is_active = 1" in sql
    assert "branch_id" not in sql.split("WHERE", 1)[1]


def test_list_departments_for_branch_includes_provider_wide():
    session = CapturingSession()
    provider_id, branch_id = uuid4(), uuid4()
    CatalogRepository(session).list_departments(provider_id, branch_id)
    where = compiled_sql(session.statement).split("WHERE", 1)[1]
    assert "departments.provider_id = '" + str(provider_id) + "'" in where
    assert "departments.branch_id IS NULL OR departments.branch_id = '" + str(branch_id) + "'" in where


def test_service_delegates_with_tenant_provider():
    calls = []

    class Repo:
        def list_departments(self, provider_id, branch_id=None):
            calls.append((provider_id, branch_id))
            return []

    provider_id, branch_id = uuid4(), uuid4()
    assert CatalogService(Repo()).get_departments(provider_id, branch_id) == []
    assert calls == [(provider_id, branch_id)]


def test_department_out_from_orm():
    dept = Department(id=uuid4(), provider_id=uuid4(), branch_id=None, code="cardiology",
                      name_ar="قسم القلب", name_en="Cardiology", description_ar=None,
                      description_en=None, phone=None, is_active=True)
    out = DepartmentOut.model_validate(dept)
    assert out.branch_id is None and out.code == "cardiology"


def test_migration_follows_lab_migration():
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert len(script.get_heads()) == 1
    assert script.get_revision("d3a7c9e1f5b2").down_revision == "f4b8d2c6a1e3"


def _offline_sql(fn_name: str) -> str:
    spec = importlib.util.spec_from_file_location("dept_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    buffer = io.StringIO()
    context = MigrationContext.configure(dialect_name="mssql", opts={"as_sql": True, "output_buffer": buffer})
    with Operations.context(context):
        spec.loader.exec_module(module)
        getattr(module, fn_name)()
    return buffer.getvalue()


def test_migration_upgrade_and_downgrade_sql():
    up = _offline_sql("upgrade")
    assert "CREATE TABLE departments" in up
    assert "CONSTRAINT [FK_departments_branch_provider] FOREIGN KEY(branch_id, provider_id) REFERENCES branches (id, provider_id)" in up
    assert "CONSTRAINT [UQ_departments_provider_code] UNIQUE (provider_id, code)" in up
    assert "CREATE INDEX [IX_departments_provider_active]" in up
    assert "INSERT" not in up.upper()
    down = _offline_sql("downgrade")
    assert "DROP TABLE departments" in down
