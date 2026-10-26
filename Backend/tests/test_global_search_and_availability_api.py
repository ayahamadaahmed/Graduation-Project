"""Global search (no tenant header, public fields only) and tenant-scoped
doctor availability: validation and scoping. No database."""

from datetime import date, time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import dependencies as deps
from app.api.routers import catalog, search

PROVIDER_A, PROVIDER_B = uuid4(), uuid4()
DOCTOR_A = uuid4()


class FakeSearchRepository:
    def __init__(self):
        self.calls = []

    def search_providers(self, **filters):
        self.calls.append(("providers", filters))
        return [
            SimpleNamespace(
                id=PROVIDER_A, name="Clinic A", slug="clinic-a", org_type="clinic",
                default_language="ar",
                # Private fields that must never be serialized.
                tenant_key="clinic-001", phone="0100", email="a@x", is_active=True,
            )
        ]

    def search_doctors(self, **filters):
        self.calls.append(("doctors", filters))
        return [
            {
                "id": DOCTOR_A, "provider_id": PROVIDER_A, "provider_name": "Clinic A",
                "provider_org_type": "clinic", "specialty_id": uuid4(),
                "specialty_code": "CARDIOLOGY", "specialty_name_ar": "قلب",
                "specialty_name_en": "Cardiology", "full_name_ar": "د", "full_name_en": "Dr A",
                "consultation_fee": None, "experience_years": 5, "gender": "male",
                "rating_avg": None, "review_count": 0, "accepting_new_patients": True,
                "license_number": "SECRET-LICENSE",
            }
        ]

    def search_availability(self, **filters):
        self.calls.append(("availability", filters))
        return [
            {
                "id": uuid4(), "provider_id": provider_id, "provider_name": name,
                "provider_org_type": "clinic", "branch_id": uuid4(),
                "branch_name_ar": "فرع", "branch_name_en": "Branch", "governorate": "Cairo",
                "doctor_id": uuid4(), "doctor_name_ar": "د", "doctor_name_en": "Dr",
                "specialty_code": "CARDIOLOGY", "specialty_name_ar": "قلب",
                "specialty_name_en": "Cardiology", "slot_date": filters["date_from"],
                "start_time": time(10), "end_time": time(10, 30),
            }
            for provider_id, name in ((PROVIDER_A, "Clinic A"), (PROVIDER_B, "Clinic B"))
        ]


def _search_client():
    app = FastAPI()
    app.include_router(search.router, prefix="/api/v1")
    repository = FakeSearchRepository()
    app.dependency_overrides[deps.get_search_repository] = lambda: repository
    return TestClient(app), repository


def test_search_needs_no_tenant_and_returns_public_provider_fields_only():
    client, repository = _search_client()

    response = client.get("/api/v1/search/providers?org_type=clinic&governorate=Cairo")

    assert response.status_code == 200
    assert set(response.json()[0]) == {"id", "name", "slug", "org_type", "default_language"}
    assert repository.calls[0][1]["governorate"] == "Cairo"


def test_doctor_search_hides_license_number():
    client, _ = _search_client()

    response = client.get("/api/v1/search/doctors?specialty_code=CARDIOLOGY")

    assert response.status_code == 200
    assert "license_number" not in response.json()[0]


def test_availability_spans_providers_and_defaults_to_one_day():
    client, repository = _search_client()

    response = client.get("/api/v1/search/availability?date_from=2026-10-20")

    assert response.status_code == 200
    assert {row["provider_id"] for row in response.json()} == {str(PROVIDER_A), str(PROVIDER_B)}
    filters = repository.calls[0][1]
    assert filters["date_from"] == filters["date_to"] == date(2026, 10, 20)


@pytest.mark.parametrize(
    "query,code",
    [
        ("date_from=2026-10-20&date_to=2026-10-19", "INVALID_DATE_RANGE"),
        ("date_from=2026-10-01&date_to=2026-10-31", "DATE_RANGE_TOO_LARGE"),
        ("date_from=2026-10-20&time_from=12:00&time_to=11:00", "INVALID_TIME_RANGE"),
    ],
)
def test_availability_rejects_bad_ranges(query, code):
    client, repository = _search_client()

    response = client.get(f"/api/v1/search/availability?{query}")

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    assert repository.calls == []


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/search/doctors?specialty_code=a%25b",
        "/api/v1/search/doctors?q=x",
        "/api/v1/search/providers?org_type=pharmacy",
        "/api/v1/search/doctors?limit=101",
        "/api/v1/search/availability",
    ],
)
def test_search_input_validation(path):
    client, repository = _search_client()

    response = client.get(path)

    assert response.status_code == 422
    assert repository.calls == []


# ================================================================ availability


class FakeCatalogService:
    def __init__(self):
        self.slot_calls = []

    def doctor_is_active(self, provider_id, doctor_id):
        return provider_id == PROVIDER_A and doctor_id == DOCTOR_A

    def get_available_slots(self, *, provider_id, slot_date, doctor_id, branch_id, limit):
        self.slot_calls.append((provider_id, slot_date, doctor_id, limit))
        return [
            SimpleNamespace(
                id=uuid4(), provider_id=provider_id, doctor_id=doctor_id, branch_id=uuid4(),
                slot_date=slot_date, start_time=time(9), end_time=time(9, 30), status="available",
            )
        ]

    def get_branches(self, provider_id):
        return []


def _catalog_client(provider_id):
    app = FastAPI()
    app.include_router(catalog.router, prefix="/api/v1")
    service = FakeCatalogService()
    app.dependency_overrides[deps.get_current_provider] = lambda: SimpleNamespace(
        id=provider_id, tenant_key="t", timezone="Africa/Cairo"
    )
    app.dependency_overrides[deps.get_catalog_service] = lambda: service
    return TestClient(app), service


def test_doctor_availability_covers_each_day_in_range():
    client, service = _catalog_client(PROVIDER_A)

    response = client.get(
        f"/api/v1/doctors/{DOCTOR_A}/availability?date_from=2026-10-20&date_to=2026-10-22"
    )

    assert response.status_code == 200
    assert [call[1] for call in service.slot_calls] == [
        date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22),
    ]
    assert all(call[0] == PROVIDER_A for call in service.slot_calls)


def test_doctor_of_another_provider_is_404():
    client, service = _catalog_client(PROVIDER_B)

    response = client.get(f"/api/v1/doctors/{DOCTOR_A}/availability?date_from=2026-10-20")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "DOCTOR_NOT_FOUND"
    assert service.slot_calls == []


def test_doctor_availability_rejects_long_range():
    client, service = _catalog_client(PROVIDER_A)

    response = client.get(
        f"/api/v1/doctors/{DOCTOR_A}/availability?date_from=2026-10-01&date_to=2026-11-30"
    )

    assert response.status_code == 422
    assert service.slot_calls == []
