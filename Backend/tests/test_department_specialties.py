"""Department <-> specialty links: model, tenant/branch-scoped service, query, migration (no database)."""

import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import mssql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.models import DepartmentSpecialty, Specialty
from app.repositories.catalog_repository import CatalogRepository
from app.schemas.catalog import DepartmentSpecialtyLinkIn
from app.services.catalog_service import (
    CatalogService,
    DepartmentNotFoundError,
    SpecialtyNotFoundError,
)

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "migrations" / "versions" / "a8c2e5f1b7d4_add_department_specialties.py"


class FakeRepository:
    """In-memory stand-in honouring the provider filter the real queries apply."""

    def __init__(self, departments=(), specialties=()):
        self.departments = list(departments)
        self.specialties = list(specialties)
        self.links: set[tuple] = set()
        self.fail_next_add = False
        self.rolled_back = False

    def get_department(self, provider_id, department_id):
        return next((d for d in self.departments if d.id == department_id and d.provider_id == provider_id), None)

    def get_specialty(self, provider_id, specialty_id):
        return next((s for s in self.specialties if s.id == specialty_id and s.provider_id == provider_id), None)

    def department_specialty_exists(self, provider_id, department_id, specialty_id):
        return (provider_id, department_id, specialty_id) in self.links

    def add_department_specialty(self, provider_id, department_id, specialty_id):
        if self.fail_next_add:
            self.fail_next_add = False
            raise IntegrityError("INSERT", {}, Exception("UQ_department_specialties_department_specialty"))
        self.links.add((provider_id, department_id, specialty_id))

    def rollback(self):
        self.rolled_back = True

    def list_department_specialties(self, provider_id, department_id):
        ids = {s for (p, d, s) in self.links if p == provider_id and d == department_id}
        return [s for s in self.specialties if s.id in ids]


def _dept(provider_id, branch_id=None):
    return SimpleNamespace(id=uuid4(), provider_id=provider_id, branch_id=branch_id)


def _spec(provider_id):
    return SimpleNamespace(id=uuid4(), provider_id=provider_id)


@pytest.fixture
def tenants():
    a, b, branch_a1, branch_a2 = uuid4(), uuid4(), uuid4(), uuid4()
    return SimpleNamespace(
        a=a,
        b=b,
        branch_a1=branch_a1,
        branch_a2=branch_a2,
        wide=_dept(a),
        branch_dept=_dept(a, branch_a1),
        dept_b=_dept(b),
        spec_a=_spec(a),
        spec_b=_spec(b),
    )


def _service(t):
    repo = FakeRepository(
        departments=[t.wide, t.branch_dept, t.dept_b],
        specialties=[t.spec_a, t.spec_b],
    )
    return CatalogService(repo), repo


# ---------------------------------------------------------------- model


def test_link_model_enforces_same_provider_on_both_sides():
    table = DepartmentSpecialty.__table__
    assert table.name == "department_specialties"
    assert all(not table.c[c].nullable for c in ("provider_id", "department_id", "specialty_id"))
    fks = {fk.name: fk for fk in table.foreign_key_constraints}
    dept_fk = fks["FK_department_specialties_department_provider"]
    spec_fk = fks["FK_department_specialties_specialty_provider"]
    assert [c.name for c in dept_fk.columns] == ["department_id", "provider_id"]
    assert [e.target_fullname for e in dept_fk.elements] == ["departments.id", "departments.provider_id"]
    assert [c.name for c in spec_fk.columns] == ["specialty_id", "provider_id"]
    assert [e.target_fullname for e in spec_fk.elements] == ["specialties.id", "specialties.provider_id"]
    names = {c.name for c in table.constraints}
    assert "UQ_department_specialties_department_specialty" in names
    ddl = str(CreateTable(table).compile(dialect=mssql.dialect()))
    assert "FOREIGN KEY(specialty_id, provider_id) REFERENCES specialties (id, provider_id)" in ddl


def test_specialty_has_composite_key_target():
    names = {c.name for c in Specialty.__table__.constraints}
    assert "UQ_specialties_id_provider" in names


# ---------------------------------------------------------------- linking


def test_link_and_retrieve(tenants):
    service, repo = _service(tenants)
    result = service.link_department_specialty(tenants.a, tenants.wide.id, tenants.spec_a.id)
    assert result is tenants.spec_a
    assert service.get_department_specialties(tenants.a, tenants.wide.id) == [tenants.spec_a]


def test_link_is_idempotent(tenants):
    service, repo = _service(tenants)
    service.link_department_specialty(tenants.a, tenants.wide.id, tenants.spec_a.id)
    service.link_department_specialty(tenants.a, tenants.wide.id, tenants.spec_a.id)
    assert len(repo.links) == 1


def test_concurrent_duplicate_is_treated_as_linked(tenants):
    service, repo = _service(tenants)
    repo.fail_next_add = True
    repo.links.add((tenants.a, tenants.wide.id, tenants.spec_a.id))
    original = repo.department_specialty_exists
    calls = iter([False, True])
    repo.department_specialty_exists = lambda *args: next(calls)
    assert service.link_department_specialty(tenants.a, tenants.wide.id, tenants.spec_a.id) is tenants.spec_a
    assert repo.rolled_back
    repo.department_specialty_exists = original


def test_unrelated_integrity_error_is_raised(tenants):
    service, repo = _service(tenants)
    repo.fail_next_add = True
    with pytest.raises(IntegrityError):
        service.link_department_specialty(tenants.a, tenants.wide.id, tenants.spec_a.id)
    assert repo.rolled_back


# ---------------------------------------------------------------- provider isolation / invalid


def test_cannot_link_other_providers_specialty(tenants):
    service, repo = _service(tenants)
    with pytest.raises(SpecialtyNotFoundError):
        service.link_department_specialty(tenants.a, tenants.wide.id, tenants.spec_b.id)
    assert not repo.links


def test_cannot_link_or_read_other_providers_department(tenants):
    service, repo = _service(tenants)
    with pytest.raises(DepartmentNotFoundError):
        service.link_department_specialty(tenants.a, tenants.dept_b.id, tenants.spec_a.id)
    with pytest.raises(DepartmentNotFoundError):
        service.get_department_specialties(tenants.a, tenants.dept_b.id)
    assert not repo.links


def test_unknown_ids_are_rejected(tenants):
    service, repo = _service(tenants)
    with pytest.raises(DepartmentNotFoundError):
        service.link_department_specialty(tenants.a, uuid4(), tenants.spec_a.id)
    with pytest.raises(SpecialtyNotFoundError):
        service.link_department_specialty(tenants.a, tenants.wide.id, uuid4())
    assert not repo.links


def test_link_payload_requires_uuid():
    with pytest.raises(ValueError):
        DepartmentSpecialtyLinkIn(specialty_id="not-a-uuid")


# ---------------------------------------------------------------- branch scope


def test_branch_scope(tenants):
    service, repo = _service(tenants)
    # Provider-wide department is visible from any branch.
    service.link_department_specialty(tenants.a, tenants.wide.id, tenants.spec_a.id, tenants.branch_a2)
    # Branch department is visible in its own branch and without a branch filter.
    service.link_department_specialty(tenants.a, tenants.branch_dept.id, tenants.spec_a.id, tenants.branch_a1)
    assert service.get_department_specialties(tenants.a, tenants.branch_dept.id) == [tenants.spec_a]
    # ...but not from another branch.
    with pytest.raises(DepartmentNotFoundError):
        service.get_department_specialties(tenants.a, tenants.branch_dept.id, tenants.branch_a2)
    with pytest.raises(DepartmentNotFoundError):
        service.link_department_specialty(tenants.a, tenants.branch_dept.id, tenants.spec_a.id, tenants.branch_a2)


# ---------------------------------------------------------------- repository SQL


class CapturingSession:
    def __init__(self):
        self.statement = None

    def scalars(self, statement):
        self.statement = statement
        return self

    def all(self):
        return []

    def first(self):
        return None


def _sql(statement) -> str:
    return str(statement.compile(dialect=mssql.dialect(), compile_kwargs={"literal_binds": True}))


def test_repository_queries_are_provider_scoped():
    provider_id, dept_id, spec_id = uuid4(), uuid4(), uuid4()
    session = CapturingSession()
    repo = CatalogRepository(session)

    repo.get_department(provider_id, dept_id)
    assert f"departments.provider_id = '{provider_id}'" in _sql(session.statement)
    repo.get_specialty(provider_id, spec_id)
    assert f"specialties.provider_id = '{provider_id}'" in _sql(session.statement)
    assert "specialties.is_active = 1" in _sql(session.statement)

    repo.list_department_specialties(provider_id, dept_id)
    sql = _sql(session.statement)
    assert "department_specialties.provider_id = specialties.provider_id" in sql
    assert f"department_specialties.provider_id = '{provider_id}'" in sql
    assert f"department_specialties.department_id = '{dept_id}'" in sql


# ---------------------------------------------------------------- migration


def test_migration_is_single_head_after_departments():
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    heads = script.get_heads()
    assert len(heads) == 1
    assert script.get_revision("a8c2e5f1b7d4").down_revision == "d3a7c9e1f5b2"
    # Later revisions build on it (c3d9e6a2f8b1: doctor verification decisions).
    assert "a8c2e5f1b7d4" in {rev.revision for rev in script.iterate_revisions(heads[0], "base")}


def _offline_sql(fn_name: str) -> str:
    spec = importlib.util.spec_from_file_location("dept_spec_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    buffer = io.StringIO()
    context = MigrationContext.configure(dialect_name="mssql", opts={"as_sql": True, "output_buffer": buffer})
    with Operations.context(context):
        spec.loader.exec_module(module)
        getattr(module, fn_name)()
    return buffer.getvalue()


def test_migration_upgrade_and_downgrade_sql():
    up = _offline_sql("upgrade")
    assert "ADD CONSTRAINT [UQ_specialties_id_provider] UNIQUE (id, provider_id)" in up
    assert up.index("UQ_specialties_id_provider") < up.index("CREATE TABLE department_specialties")
    assert "FOREIGN KEY(department_id, provider_id) REFERENCES departments (id, provider_id)" in up
    assert "FOREIGN KEY(specialty_id, provider_id) REFERENCES specialties (id, provider_id)" in up
    assert "UNIQUE (department_id, specialty_id)" in up
    assert "INSERT" not in up.upper()
    down = _offline_sql("downgrade")
    assert "DROP TABLE department_specialties" in down
    assert "DROP CONSTRAINT [UQ_specialties_id_provider]" in down
    # Pre-existing key is preserved: only the copy tagged by this revision is ever dropped.
    assert "sp_addextendedproperty @name = N'medmind_created_by_revision', @value = N'a8c2e5f1b7d4'" in up
    assert up.index("IF NOT EXISTS") < up.index("sp_addextendedproperty")
    assert "ep.name = N'medmind_created_by_revision'" in down
    assert "CAST(ep.value AS nvarchar(100)) = N'a8c2e5f1b7d4'" in down
    assert down.index("DROP TABLE department_specialties") < down.index("DROP CONSTRAINT")


# ---------------------------------------------------------------- API


def _client(t, role="provider_admin"):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import dependencies as deps
    from app.api.routers import catalog
    from app.security.staff_context import StaffContext

    service, repo = _service(t)
    app = FastAPI()
    app.include_router(catalog.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_current_provider] = lambda: SimpleNamespace(id=t.a)
    app.dependency_overrides[deps.get_catalog_service] = lambda: service
    app.dependency_overrides[deps.get_current_staff] = lambda: StaffContext(
        user_id=uuid4(), membership_id=uuid4(), provider_id=t.a, role=role, doctor_id=None
    )
    return TestClient(app), repo


def _full_spec(s):
    return SimpleNamespace(
        id=s.id, provider_id=s.provider_id, code="c", name_ar="ع", name_en="E",
        description_ar=None, description_en=None, is_active=True,
    )


@pytest.fixture
def api_tenants(tenants):
    tenants.spec_a = _full_spec(tenants.spec_a)
    tenants.spec_b = _full_spec(tenants.spec_b)
    return tenants


def test_api_link_and_list(api_tenants):
    t = api_tenants
    client, repo = _client(t)
    url = f"/api/v1/departments/{t.wide.id}/specialties"
    response = client.post(url, json={"specialty_id": str(t.spec_a.id)})
    assert response.status_code == 201
    assert response.json()["id"] == str(t.spec_a.id)
    listed = client.get(url)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [str(t.spec_a.id)]


def test_api_rejects_cross_provider_and_branch(api_tenants):
    t = api_tenants
    client, repo = _client(t)
    other = client.post(f"/api/v1/departments/{t.wide.id}/specialties", json={"specialty_id": str(t.spec_b.id)})
    assert other.status_code == 404 and other.json()["detail"]["code"] == "SPECIALTY_NOT_FOUND"
    foreign = client.get(f"/api/v1/departments/{t.dept_b.id}/specialties")
    assert foreign.status_code == 404 and foreign.json()["detail"]["code"] == "DEPARTMENT_NOT_FOUND"
    wrong_branch = client.get(f"/api/v1/departments/{t.branch_dept.id}/specialties", params={"branch_id": str(t.branch_a2)})
    assert wrong_branch.status_code == 404
    bad_body = client.post(f"/api/v1/departments/{t.wide.id}/specialties", json={"specialty_id": "x"})
    assert bad_body.status_code == 422
    assert not repo.links


def test_api_link_requires_provider_admin(api_tenants):
    t = api_tenants
    client, repo = _client(t, role="receptionist")
    response = client.post(f"/api/v1/departments/{t.wide.id}/specialties", json={"specialty_id": str(t.spec_a.id)})
    assert response.status_code == 403
    assert not repo.links
