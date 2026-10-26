"""Approved Catalog API decisions (2026-10-22).

B. GET /services: service_type must be one of the service types the database
   accepts; anything else is 422. Omitted keeps the optional-filter behavior.
C. GET /providers (and /public/providers): org_type is optional. Omitted means
   every publicly visible type (clinic, hospital, diagnostic_lab), still only
   verified and active providers. A supplied invalid value stays 422.
D. GET /doctors/{id}/availability: the existing date rules are pinned as they
   are, including that past dates are not rejected.

(Decision A, doctor verification in catalog results, is not implemented: the
codebase has no rule or workflow that verifies doctors.)

Routers are real; catalog services are fakes; repository SQL is captured,
never executed. No database, network or AI.
"""

import inspect
import re
from datetime import date, time, timedelta
from types import SimpleNamespace
from typing import get_args
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import dependencies as deps
from app.api.routers import catalog
from app.models.service import Service
from app.repositories.catalog_repository import PUBLIC_PROVIDER_ORG_TYPES, CatalogRepository
from app.schemas.admin_catalog import AdminServiceCreate
from app.schemas.catalog import ServiceType
from app.services.catalog_service import CatalogService
from tests.test_blueprint_aliases import real_app_catalog  # noqa: F401  fixture
from tests.test_catalog_patient_ops_http import PROVIDER_A, _tenant, api  # noqa: F401  api is a fixture

SERVICE_TYPES = ("consultation", "follow_up", "teleconsultation", "procedure", "surgery", "diagnostic")


# ============================================================ B. service_type


def test_service_types_match_the_database_and_admin_contract():
    assert set(get_args(ServiceType)) == set(SERVICE_TYPES)
    assert set(get_args(AdminServiceCreate.model_fields["service_type"].annotation)) == set(SERVICE_TYPES)
    (check,) = [c for c in Service.__table__.constraints if c.name == "CK_services_service_type"]
    assert set(re.findall(r"service_type='([a-z_]+)'", str(check.sqltext))) == set(SERVICE_TYPES)


@pytest.mark.parametrize("service_type", SERVICE_TYPES)
def test_every_valid_service_type_is_passed_to_the_service(api, service_type):
    response = api.client.get("/api/v1/services", headers=_tenant(), params={"service_type": service_type})

    assert response.status_code == 200
    (_, kwargs), = [c for c in api.catalog.calls if c[0] == "get_services"]
    assert kwargs["service_type"] == service_type
    assert kwargs["provider_id"] == PROVIDER_A.id


@pytest.mark.parametrize("service_type", ["lab_test", "radiology", "Consultation", "consultation ", "", "x" * 31])
def test_an_invalid_service_type_is_422_before_the_service(api, service_type):
    response = api.client.get("/api/v1/services", headers=_tenant(), params={"service_type": service_type})

    assert response.status_code == 422
    assert not [c for c in api.catalog.calls if c[0] == "get_services"]


def test_an_omitted_service_type_keeps_the_other_filters(api):
    doctor_id = uuid4()

    response = api.client.get("/api/v1/services", headers=_tenant(), params={"doctor_id": str(doctor_id)})

    assert response.status_code == 200
    assert {s["code"] for s in response.json()} == {"CONSULT", "CBC"}
    (_, kwargs), = [c for c in api.catalog.calls if c[0] == "get_services"]
    assert (kwargs["service_type"], kwargs["doctor_id"]) == (None, doctor_id)


def test_a_valid_service_type_without_matches_is_an_empty_200(api):
    response = api.client.get("/api/v1/services", headers=_tenant(), params={"service_type": "teleconsultation"})

    assert response.status_code == 200
    assert response.json() == []


# ============================================================ C. optional org_type


@pytest.mark.parametrize("path", ["/api/v1/providers", "/api/v1/public/providers"])
def test_an_omitted_org_type_lists_every_public_type(real_app_catalog, path):
    client, catalog_service = real_app_catalog

    response = client.get(path)

    assert response.status_code == 200
    assert {p["slug"] for p in response.json()} == {"clinic-a", "lab-b"}
    assert set(response.json()[0]) == {"id", "name", "slug", "org_type", "default_language"}
    assert catalog_service.calls[-1] == ("get_public_providers", None)


@pytest.mark.parametrize("org_type", ["clinic", "hospital", "diagnostic_lab"])
@pytest.mark.parametrize("path", ["/api/v1/providers", "/api/v1/public/providers"])
def test_a_supplied_org_type_still_filters(real_app_catalog, path, org_type):
    client, catalog_service = real_app_catalog

    response = client.get(path, params={"org_type": org_type})

    assert response.status_code == 200
    assert all(p["org_type"] == org_type for p in response.json())
    assert catalog_service.calls[-1] == ("get_public_providers", org_type)


@pytest.mark.parametrize("org_type", ["pharmacy", "", "Clinic", "lab"])
@pytest.mark.parametrize("path", ["/api/v1/providers", "/api/v1/public/providers"])
def test_a_supplied_invalid_org_type_is_422(real_app_catalog, path, org_type):
    client, catalog_service = real_app_catalog

    assert client.get(path, params={"org_type": org_type}).status_code == 422
    assert not [c for c in catalog_service.calls if c[0] == "get_public_providers"]


class RecordingRepository:
    def __init__(self):
        self.calls = []

    def list_public_providers(self, *, org_type):
        self.calls.append(org_type)
        return []


@pytest.mark.parametrize("org_type, expected", [(None, None), ("clinic", "clinic"), (" Hospital ", "hospital")])
def test_the_service_passes_the_public_type_or_none(org_type, expected):
    repository = RecordingRepository()

    CatalogService(repository).get_public_providers(org_type=org_type)

    assert repository.calls == [expected]


@pytest.mark.parametrize("org_type", ["pharmacy", ""])
def test_the_service_still_rejects_a_non_public_type(org_type):
    repository = RecordingRepository()

    with pytest.raises(ValueError):
        CatalogService(repository).get_public_providers(org_type=org_type)
    assert repository.calls == []


class CapturingSession:
    def __init__(self):
        self.statements = []

    def scalars(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(all=lambda: [])


def _sql(statement):
    return str(statement.compile(compile_kwargs={"literal_binds": True})).replace("\n", " ")


def test_omitted_org_type_sql_keeps_every_visibility_rule():
    session = CapturingSession()

    CatalogRepository(session).list_public_providers(org_type=None)

    sql = _sql(session.statements[0])
    assert "providers.org_type IN ('clinic', 'hospital', 'diagnostic_lab')" in sql
    assert "pharmacy" not in sql
    assert "providers.verification_status = 'verified'" in sql
    assert "providers.is_active = 1" in sql


def test_supplied_org_type_sql_filters_that_type_only():
    session = CapturingSession()

    CatalogRepository(session).list_public_providers(org_type="hospital")

    sql = _sql(session.statements[0])
    assert "providers.org_type = 'hospital'" in sql
    assert " IN (" not in sql
    assert "providers.verification_status = 'verified'" in sql and "providers.is_active = 1" in sql


def test_list_and_branch_visibility_share_one_set_of_public_types():
    assert PUBLIC_PROVIDER_ORG_TYPES == ("clinic", "hospital", "diagnostic_lab")
    assert "PUBLIC_PROVIDER_ORG_TYPES" in inspect.getsource(CatalogRepository.get_public_provider_by_id)
    assert "PUBLIC_PROVIDER_ORG_TYPES" in inspect.getsource(CatalogService.get_public_providers)


# ============================================================ D. availability date rules

DOCTOR = uuid4()
BRANCH = uuid4()


class AvailabilityCatalog:
    """Records every call; one available slot per day."""

    def __init__(self, active=True):
        self.active = active
        self.active_calls = []
        self.slot_calls = []

    def doctor_is_active(self, provider_id, doctor_id):
        self.active_calls.append((provider_id, doctor_id))
        return self.active and provider_id == PROVIDER_A.id and doctor_id == DOCTOR

    def get_available_slots(self, *, provider_id, slot_date, doctor_id, branch_id, limit):
        self.slot_calls.append(dict(provider_id=provider_id, slot_date=slot_date, doctor_id=doctor_id,
                                    branch_id=branch_id, limit=limit))
        return [SimpleNamespace(
            id=uuid4(), provider_id=provider_id, doctor_id=doctor_id, branch_id=branch_id or BRANCH,
            slot_date=slot_date, start_time=time(9), end_time=time(9, 30), status="available",
        )]

    def get_branches(self, provider_id):
        return []


@pytest.fixture
def availability():
    service = AvailabilityCatalog()
    app = FastAPI()
    app.include_router(catalog.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_current_provider] = lambda: SimpleNamespace(
        id=PROVIDER_A.id, tenant_key="clinic-001", timezone="Africa/Cairo",
    )
    app.dependency_overrides[deps.get_catalog_service] = lambda: service
    client = TestClient(app)
    service.get = lambda doctor=DOCTOR, **params: client.get(f"/api/v1/doctors/{doctor}/availability", params=params)
    return service


def _days(service):
    return [call["slot_date"] for call in service.slot_calls]


def _rejected_before_any_lookup(service, response, code=None):
    assert response.status_code == 422
    if code:
        assert response.json()["detail"]["code"] == code
    assert service.active_calls == [] and service.slot_calls == []


def test_date_from_is_required(availability):
    _rejected_before_any_lookup(availability, availability.get())


def test_date_to_defaults_to_date_from(availability):
    response = availability.get(date_from="2026-10-20")

    assert response.status_code == 200
    assert _days(availability) == [date(2026, 10, 20)]


def test_equal_bounds_are_one_day(availability):
    assert availability.get(date_from="2026-10-20", date_to="2026-10-20").status_code == 200
    assert _days(availability) == [date(2026, 10, 20)]


def test_a_reversed_range_is_422_before_any_lookup(availability):
    response = availability.get(date_from="2026-10-21", date_to="2026-10-20")

    _rejected_before_any_lookup(availability, response, "INVALID_DATE_RANGE")


def test_the_longest_allowed_range_is_14_days(availability):
    start = date(2026, 10, 1)

    response = availability.get(date_from=str(start), date_to=str(start + timedelta(days=13)), limit=200)

    assert response.status_code == 200
    assert _days(availability) == [start + timedelta(days=n) for n in range(14)]


def test_a_15_day_range_is_422_before_any_lookup(availability):
    start = date(2026, 10, 1)

    response = availability.get(date_from=str(start), date_to=str(start + timedelta(days=14)))

    _rejected_before_any_lookup(availability, response, "INVALID_DATE_RANGE")


def test_past_dates_are_not_rejected(availability):
    # Current behavior: no past-date rule; each past day is queried like any other.
    response = availability.get(date_from="2020-01-01", date_to="2020-01-03")

    assert response.status_code == 200
    assert _days(availability) == [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3)]
    assert [s["slot_date"] for s in response.json()] == ["2020-01-01", "2020-01-02", "2020-01-03"]


def test_the_slot_query_has_no_current_time_filter():
    session = CapturingSession()

    CatalogRepository(session).list_available_slots(
        provider_id=uuid4(), slot_date=date(2020, 1, 1), doctor_id=uuid4(), branch_id=None, limit=10,
    )

    sql = str(session.statements[0].compile()).lower()
    assert "doctor_availability_slots.slot_date = " in sql
    assert "doctor_availability_slots.status = " in sql
    for now_function in ("sysutcdatetime", "getdate", "current_timestamp", "current_date", "now("):
        assert now_function not in sql


def test_branch_id_is_passed_to_every_day(availability):
    branch_id = uuid4()

    availability.get(date_from="2026-10-20", date_to="2026-10-22", branch_id=str(branch_id))

    assert [call["branch_id"] for call in availability.slot_calls] == [branch_id] * 3
    assert all(call["provider_id"] == PROVIDER_A.id and call["doctor_id"] == DOCTOR
               for call in availability.slot_calls)


def test_the_limit_stops_the_day_loop(availability):
    response = availability.get(date_from="2026-10-20", date_to="2026-10-24", limit=2)

    assert response.status_code == 200
    assert len(response.json()) == 2
    assert [call["limit"] for call in availability.slot_calls] == [2, 1]


@pytest.mark.parametrize("limit", [1, 200])
def test_limit_bounds_are_inclusive(availability, limit):
    assert availability.get(date_from="2026-10-20", limit=limit).status_code == 200
    assert availability.slot_calls[0]["limit"] == limit


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"date_from": "yesterday"},
                                    {"date_to": "2026-13-01"}, {"branch_id": "not-a-uuid"}])
def test_invalid_parameters_are_422_before_any_lookup(availability, params):
    _rejected_before_any_lookup(availability, availability.get(**{"date_from": "2026-10-20", **params}))


def test_a_malformed_doctor_id_is_422_before_any_lookup(availability):
    _rejected_before_any_lookup(availability, availability.get(doctor="not-a-uuid", date_from="2026-10-20"))


def test_an_inactive_or_foreign_doctor_is_404_before_slot_lookup(availability):
    availability.active = False

    response = availability.get(date_from="2026-10-20")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "DOCTOR_NOT_FOUND"
    assert availability.slot_calls == []
