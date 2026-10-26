"""Booking lifecycle Option A (create-as-confirmed, idempotent confirm) and the
API Blueprint read path GET /api/v1/appointments/{id}, where {id} is the
appointment reference.

GET /appointments/{appointment_reference} is the same staff-only read as
GET /appointments/reference/{appointment_reference}: staff JWT, role and
doctor/lab scope, provider from the token, audited. Service (AI/MCP) callers
have no access there; their read stays POST /appointments/lookup, which also
verifies the patient's national ID.

No database: SQL is captured, repositories and services are fakes. Synthetic
values only.
"""

import re
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import app.main as backend_main
from app.api import dependencies as deps
from app.api.routers import appointments
from app.core.config import get_settings
from app.repositories.appointment_repository import AppointmentRepository
from app.security.service_auth import SERVICE_TOKEN_HEADER
from tests.test_appointment_confirm import FakeRepository as ConfirmRepository
from tests.test_appointment_confirm import _confirm, _service
from tests.test_appointment_staff_read_api import (
    DOCTOR_1,
    PATIENT,
    PROVIDER_A,
    PROVIDER_B,
    ROWS,
    _client,
    _staff,
)

MCP_TOKEN = "test-only-mcp-server-token-0123456789abcdef"


# ============================================================ Option A: create-as-confirmed


class CapturingSession:
    def __init__(self):
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        return SimpleNamespace(rowcount=1)


def _insert_columns_and_values(sql):
    """Pair the column list of an INSERT with its VALUES list."""
    columns = re.search(r"INSERT INTO [\w.]+\s*\((.*?)\)\s*VALUES", sql, re.S).group(1)
    values = re.search(r"VALUES\s*\((.*)\)\s*;", sql, re.S).group(1)
    split = lambda text: [part.strip() for part in text.split(",")]  # noqa: E731
    columns, values = split(columns), split(values)
    assert len(columns) == len(values)
    return dict(zip(columns, values))


def _created_row():
    session = CapturingSession()
    AppointmentRepository(session).insert_appointment(
        appointment_id=uuid4(), provider_id=uuid4(), appointment_reference="APT-TEST-0001",
        patient_id=uuid4(), patient_name="Test Patient", phone="+201000000000", slot_id=uuid4(),
        doctor_id=uuid4(), branch_id=uuid4(), service_id=uuid4(), scheduled_date=None,
        start_time=None, end_time=None, channel="voice", notes=None,
        created_by_type="ai_agent", created_by_reference=None,
    )
    (sql,) = session.statements
    return _insert_columns_and_values(sql)


def test_create_inserts_a_confirmed_booking_with_confirmed_at_set():
    row = _created_row()

    assert row["status"] == "'confirmed'"
    assert row["confirmed_at"] == "SYSUTCDATETIME()"
    assert (row["cancelled_at"], row["cancellation_reason"]) == ("NULL", "NULL")
    assert row["reschedule_count"] == "0"


def test_create_records_one_created_history_row_ending_confirmed():
    session = CapturingSession()
    AppointmentRepository(session).insert_status_history(
        provider_id=uuid4(), appointment_id=uuid4(), slot_id=uuid4(),
        changed_by="ai_agent", actor_reference=None,
    )
    (sql,) = session.statements
    row = _insert_columns_and_values(sql)

    assert (row["event_type"], row["previous_status"], row["new_status"]) == ("'created'", "NULL", "'confirmed'")


def test_the_create_service_is_the_confirmed_path():
    # The router's create route calls create_confirmed_booking (no pending path).
    route = next(r for r in appointments.router.routes if r.path == "/appointments" and "POST" in r.methods)
    assert route.endpoint is appointments.create_appointment
    import inspect

    assert "service.create_confirmed_booking(" in inspect.getsource(appointments.create_appointment)


def test_confirming_a_freshly_created_booking_is_an_idempotent_success():
    created_status = _created_row()["status"].strip("'")
    repository = ConfirmRepository(created_status)
    service = _service(repository)

    first = _confirm(service)
    second = _confirm(service)

    for result in (first, second):
        assert (result.previous_status, result.status) == ("confirmed", "confirmed")
    assert repository.history == []  # no confirmation transition was recorded
    assert repository.row["status"] == "confirmed"
    assert repository.session.commits == 2 and repository.session.rollbacks == 0


# ============================================================ staff read alias


def _get(client, reference):
    return client.get(f"/api/v1/appointments/{reference}")


def _old(client, reference):
    return client.get(f"/api/v1/appointments/reference/{reference}")


@pytest.mark.parametrize("role", ["provider_admin", "receptionist"])
def test_staff_alias_matches_the_reference_route(role):
    client, repo, audit = _client(_staff(role))

    for reference in ("APT-DOC1", "APT-DOC2", "APT-LAB"):
        new, old = _get(client, reference), _old(client, reference)
        assert (new.status_code, old.status_code) == (200, 200)
        assert new.json() == old.json()

    reads = [r for r in audit.records if r["action"] == "appointment.read"]
    assert len(reads) == 6
    assert reads[0]["resource_id"] == reads[1]["resource_id"] == str(ROWS[0]["id"])


def test_staff_alias_normalizes_the_reference_like_the_original():
    client, repo, _ = _client(_staff("provider_admin"))

    assert _get(client, " apt-doc1 ").status_code == 200
    assert repo.calls[-1] == ("ref", PROVIDER_A, None, None)


def test_staff_alias_keeps_doctor_and_lab_scope():
    client, _, _ = _client(_staff("doctor", doctor_id=DOCTOR_1))
    assert _get(client, "APT-DOC1").status_code == 200
    assert _get(client, "APT-DOC2").status_code == 404
    assert _get(client, "APT-LAB").status_code == 404

    client, _, _ = _client(_staff("lab_staff"))
    assert _get(client, "APT-LAB").status_code == 200
    assert _get(client, "APT-DOC1").status_code == 404


@pytest.mark.parametrize(
    "staff", [_staff("pharmacist"), _staff("doctor", doctor_id=None)], ids=["unknown-role", "doctor-without-id"],
)
def test_staff_alias_rejects_unauthorized_roles(staff):
    client, repo, audit = _client(staff)

    response = _get(client, "APT-DOC1")

    assert response.status_code == 403
    assert not repo.calls and not audit.records


def test_staff_alias_requires_a_staff_token():
    client, repo, audit = _client(staff=None)

    assert _get(client, "APT-DOC1").status_code == 401
    assert not repo.calls and not audit.records


def test_staff_of_another_provider_cannot_read_the_appointment():
    client, repo, audit = _client(_staff("provider_admin", provider_id=PROVIDER_B))

    response = _get(client, "APT-DOC1")  # belongs to provider A

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "APPOINTMENT_NOT_FOUND"
    assert repo.calls == [("ref", PROVIDER_B, None, None)]
    assert not audit.records


def test_unknown_reference_is_the_same_not_found_as_the_original():
    client, _, audit = _client(_staff("provider_admin"))

    new, old = _get(client, "APT-NOPE"), _old(client, "APT-NOPE")

    assert (new.status_code, old.status_code) == (404, 404)
    assert new.json() == old.json()
    assert not audit.records


def test_an_internal_uuid_is_not_an_alternate_identifier():
    client, repo, audit = _client(_staff("provider_admin"))
    internal_id = ROWS[0]["id"]  # APT-DOC1's database id

    response = _get(client, str(internal_id))

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "APPOINTMENT_NOT_FOUND"
    # Looked up as a reference only (normalized), never by id.
    assert repo.calls == [("ref", PROVIDER_A, None, None)]
    assert not audit.records


# ============================================================ service callers


@pytest.fixture
def booking_credentials(monkeypatch):
    monkeypatch.setenv("MEDMIND_SERVICE_CREDENTIALS", f"mcp_server={MCP_TOKEN}@clinic-001")
    monkeypatch.setenv("BOOKING_SERVICE_AUTH_MODE", "enforce")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_a_valid_service_token_cannot_read_through_the_staff_path(booking_credentials):
    client, repo, audit = _client(staff=None)

    response = client.get(
        "/api/v1/appointments/APT-DOC1",
        headers={SERVICE_TOKEN_HEADER: MCP_TOKEN, "X-Tenant-ID": "clinic-001"},
    )

    # Staff JWT is required; the booking-service credential is not accepted here.
    assert response.status_code == 401
    assert not repo.calls and not audit.records


def test_the_service_read_path_is_unchanged_and_needs_the_national_id():
    spec = FastAPI()
    spec.include_router(appointments.router, prefix="/api/v1")
    paths = spec.openapi()["paths"]

    lookup = paths["/api/v1/appointments/lookup"]["post"]
    assert "security" not in lookup  # service auth, not staff bearer
    body = lookup["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
    required = spec.openapi()["components"]["schemas"][body]["required"]
    assert {"national_id", "appointment_reference"} <= set(required)
    # The new read is staff-only, like the reference route.
    for path in ("/api/v1/appointments/{appointment_reference}",
                 "/api/v1/appointments/reference/{appointment_reference}"):
        assert paths[path]["get"]["security"] == [{"HTTPBearer": []}]


# ============================================================ routing


class Recorder:
    """Service stand-in: any call is recorded and answered with 418."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def reached(*args, **kwargs):
            self.calls.append(name)
            raise HTTPException(status_code=418, detail={"code": "REACHED"})
        return reached


def test_existing_appointment_routes_are_not_shadowed(monkeypatch):
    monkeypatch.setenv("BOOKING_SERVICE_AUTH_MODE", "audit")
    monkeypatch.delenv("MEDMIND_SERVICE_CREDENTIALS", raising=False)
    get_settings.cache_clear()
    service = Recorder()
    app = FastAPI()
    app.include_router(appointments.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_current_provider] = lambda: SimpleNamespace(
        id=PROVIDER_A, tenant_key="clinic-001", timezone="Africa/Cairo",
    )
    app.dependency_overrides[deps.get_current_staff] = lambda: _staff("provider_admin")
    app.dependency_overrides[deps.get_appointment_service] = lambda: service
    app.dependency_overrides[deps.get_staff_audit_service] = lambda: SimpleNamespace(record=lambda **_: None)
    client = TestClient(app)
    nid = "00000000000000"
    try:
        expected = [
            (client.post("/api/v1/appointments/lookup",
                         json={"national_id": nid, "appointment_reference": "APT-1"}), "lookup_booking_for_patient"),
            (client.post("/api/v1/appointments/search-by-national-id",
                         json={"national_id": nid}), "search_bookings_by_national_id"),
            (client.get(f"/api/v1/appointments/patient/{PATIENT}"), "list_patient_bookings_for_staff"),
            (client.get("/api/v1/appointments/reference/APT-1"), "get_booking_by_reference_for_staff"),
            (client.get("/api/v1/appointments/APT-1"), "get_booking_by_reference_for_staff"),
            (client.post("/api/v1/appointments/APT-1/cancel", json={"national_id": nid}), "cancel_booking"),
        ]
        for response, method in expected:
            assert response.status_code == 418
        assert service.calls == [method for _, method in expected]
    finally:
        get_settings.cache_clear()


@pytest.fixture
def recorded_routing(monkeypatch):
    """The appointments router with every dependency that would run recorded."""
    monkeypatch.setenv("BOOKING_SERVICE_AUTH_MODE", "audit")
    monkeypatch.delenv("MEDMIND_SERVICE_CREDENTIALS", raising=False)
    get_settings.cache_clear()
    seen = SimpleNamespace(provider=[], staff=[], service=Recorder())

    def provider():
        seen.provider.append(1)
        return SimpleNamespace(id=PROVIDER_A, tenant_key="clinic-001", timezone="Africa/Cairo")

    def staff():
        seen.staff.append(1)
        return _staff("provider_admin")

    app = FastAPI()
    app.include_router(appointments.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_current_provider] = provider
    app.dependency_overrides[deps.get_current_staff] = staff
    app.dependency_overrides[deps.get_appointment_service] = lambda: seen.service
    app.dependency_overrides[deps.get_staff_audit_service] = lambda: SimpleNamespace(record=lambda **_: None)
    seen.client = TestClient(app)
    yield seen
    get_settings.cache_clear()


@pytest.mark.parametrize("segment", ["lookup", "search-by-national-id"])
@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
def test_post_only_paths_answer_405_before_any_dependency(recorded_routing, segment, method):
    response = recorded_routing.client.request(
        method, f"/api/v1/appointments/{segment}", headers={"X-Tenant-ID": "clinic-001"},
    )

    assert response.status_code == 405
    assert response.headers["allow"] == "POST"
    assert recorded_routing.provider == [] and recorded_routing.staff == []
    assert recorded_routing.service.calls == []


def test_post_only_segments_match_the_router():
    # Every single-segment path of this router that is not readable with GET.
    literal = {
        r.path.removeprefix("/appointments/") for r in appointments.router.routes
        if r.path.startswith("/appointments/") and "/" not in r.path.removeprefix("/appointments/")
        and "{" not in r.path and "GET" not in r.methods
    }
    assert literal == appointments.POST_ONLY_SEGMENTS


def test_only_the_new_route_skips_the_reserved_segments(recorded_routing):
    # The original reference route is unchanged: "lookup" there is a reference.
    response = recorded_routing.client.get("/api/v1/appointments/reference/lookup")

    assert response.status_code == 418
    assert recorded_routing.service.calls == ["get_booking_by_reference_for_staff"]


@pytest.mark.parametrize("reference", ["APT-1", "apt-1", "LOOKUP", "lookup-2", "x-search-by-national-id"])
def test_other_single_segments_still_reach_the_staff_read(recorded_routing, reference):
    response = recorded_routing.client.get(f"/api/v1/appointments/{reference}")

    assert response.status_code == 418
    assert recorded_routing.service.calls == ["get_booking_by_reference_for_staff"]
    assert recorded_routing.staff == [1]


def test_the_real_application_answers_405_for_the_post_only_paths():
    client = TestClient(backend_main.app)

    for segment in ("lookup", "search-by-national-id"):
        response = client.get(f"/api/v1/appointments/{segment}")
        assert response.status_code == 405
        assert response.headers["allow"] == "POST"


def test_the_alias_is_registered_once_on_the_real_application():
    paths = backend_main.app.openapi()["paths"]

    assert set(paths["/api/v1/appointments/{appointment_reference}"]) == {"get"}
    assert "get" in paths["/api/v1/appointments/reference/{appointment_reference}"]
    assert "post" in paths["/api/v1/appointments/lookup"]
    assert not [p for p in paths if p.startswith("/api/v1/api/v1")]
    assert paths["/api/v1/appointments/{appointment_reference}"]["get"]["security"] == [{"HTTPBearer": []}]
