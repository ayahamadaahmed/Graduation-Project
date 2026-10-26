"""HTTP contracts of the booking and patient-resolve endpoints (API coverage
audit, package 2).

Complements, without repeating:
- test_booking_service_auth.py: service/staff auth, tenant allow-list,
  audit/enforce, staff attribution, confirm caller rules;
- test_appointment_staff_read_api.py: GET /appointments/reference/{ref};
- test_appointment_confirm.py and the *_db.py suites: service and SQL logic.

Here: request validation, the Idempotency-Key header, success and error
response contracts, and that the handler hands the service the provider
resolved from X-Tenant-ID (real get_current_provider over a fake catalog)
plus the path reference unchanged. Services are fakes; no database, network
or AI. All tokens, IDs and names are fake.
"""

from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api import dependencies as deps
from app.api.routers import appointments, patients
from app.core.config import get_settings
from app.schemas.appointment import (
    AppointmentCancelResponse,
    AppointmentConfirmResponse,
    AppointmentCreateResponse,
    AppointmentLookupResponse,
    AppointmentRescheduleResponse,
    AppointmentsByNationalIdResponse,
    AppointmentSearchItem,
)
from app.schemas.patient import PatientRead, PatientResolution
from app.security.service_auth import SERVICE_TOKEN_HEADER

MCP_TOKEN = "mcp-server-test-token-0123456789abcdef0123"
NATIONAL_ID = "29001011234567"  # synthetic
REFERENCE = "APT-260828-ABC123"
NOW = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)

PROVIDER_A = SimpleNamespace(id=uuid4(), tenant_key="clinic-001", timezone="Africa/Cairo", org_type="clinic")
PROVIDER_B = SimpleNamespace(id=uuid4(), tenant_key="clinic-002", timezone="Asia/Riyadh", org_type="clinic")


def _create_response():
    return AppointmentCreateResponse(
        appointment_reference=REFERENCE, patient_code="P-TEST-0001", patient_name="Test Patient",
        branch_medical_record_number="MRN-TEST-1", scheduled_date=date(2026, 11, 2),
        start_time=time(10, 0), end_time=time(10, 30), channel="voice", status="confirmed",
        confirmed_at=NOW, reschedule_count=0,
    )


def _cancel_response():
    return AppointmentCancelResponse(
        appointment_reference=REFERENCE, previous_status="confirmed", status="cancelled",
        slot_id=uuid4(), slot_status="available", cancelled_at=NOW, cancellation_reason="test",
    )


def _reschedule_response():
    return AppointmentRescheduleResponse(
        appointment_reference=REFERENCE, previous_status="confirmed", status="confirmed",
        old_slot_id=uuid4(), new_slot_id=uuid4(), branch_id=uuid4(), service_id=None,
        scheduled_date=date(2026, 11, 3), start_time=time(11, 0), end_time=time(11, 30),
        old_slot_status="available", new_slot_status="booked", reschedule_count=1, updated_at=NOW,
    )


def _lookup_response():
    return AppointmentLookupResponse(
        appointment_reference=REFERENCE, patient_code="P-TEST-0001", patient_name="Test Patient",
        branch_id=uuid4(), slot_id=uuid4(), scheduled_date=date(2026, 11, 2), start_time=time(10, 0),
        end_time=time(10, 30), status="confirmed", channel="voice", reschedule_count=0,
    )


def _search_response():
    item = AppointmentSearchItem(
        appointment_reference=REFERENCE, patient_name="Test Patient", scheduled_date=date(2026, 11, 2),
        start_time=time(10, 0), end_time=time(10, 30), status="confirmed", channel="voice", reschedule_count=0,
    )
    return AppointmentsByNationalIdResponse(
        patient_code="P-TEST-0001", patient_name="Test Patient", count=1, appointments=[item]
    )


def _resolution():
    return PatientResolution(
        patient=PatientRead(
            id=uuid4(), patient_code="P-TEST-0001", masked_national_id="**********4567",
            full_name_ar="مريض اختبار", phone="+20100000000", preferred_language="ar",
            is_active=True, created_at=NOW, updated_at=NOW,
        ),
        provider_profile_id=uuid4(), patient_created=True, provider_profile_created=True,
    )


class FakeCatalog:
    def get_provider(self, tenant_key):
        return {"clinic-001": PROVIDER_A, "clinic-002": PROVIDER_B}.get(tenant_key)


class FakeBookingServices:
    """Records each call; returns a valid response model or raises `error`."""

    def __init__(self):
        self.calls = []
        self.error = None
        self.responses = {
            "create_confirmed_booking": _create_response,
            "cancel_booking": _cancel_response,
            "reschedule_booking": _reschedule_response,
            "lookup_booking_for_patient": _lookup_response,
            "search_bookings_by_national_id": _search_response,
            "confirm_booking": lambda: AppointmentConfirmResponse(
                appointment_reference=REFERENCE, previous_status="pending", status="confirmed", confirmed_at=NOW,
            ),
            "resolve_for_booking": _resolution,
        }

    def __getattr__(self, name):
        if name not in self.responses:
            raise AttributeError(name)

        def call(**kwargs):
            self.calls.append((name, kwargs))
            if self.error is not None:
                raise self.error
            return self.responses[name]()

        return call


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("MEDMIND_SERVICE_CREDENTIALS", f"mcp_server={MCP_TOKEN}@clinic-001,clinic-002")
    monkeypatch.setenv("BOOKING_SERVICE_AUTH_MODE", "enforce")
    get_settings.cache_clear()

    services = FakeBookingServices()
    app = FastAPI()
    for router in (appointments.router, patients.router):
        app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[deps.get_catalog_service] = lambda: FakeCatalog()
    app.dependency_overrides[deps.get_appointment_service] = lambda: services
    app.dependency_overrides[deps.get_patient_service] = lambda: services
    app.dependency_overrides[deps.get_staff_audit_service] = lambda: object()
    client = TestClient(app)

    def call(method, path, body=None, *, tenant="clinic-001", key=None):
        headers = {"X-Tenant-ID": tenant, SERVICE_TOKEN_HEADER: MCP_TOKEN}
        if key is not None:
            headers["Idempotency-Key"] = key
        return client.request(method, path, headers=headers, json=body)

    yield SimpleNamespace(call=call, services=services)
    get_settings.cache_clear()


CREATE = ("POST", "/api/v1/appointments")
CANCEL = ("POST", f"/api/v1/appointments/{REFERENCE}/cancel")
RESCHEDULE = ("POST", f"/api/v1/appointments/{REFERENCE}/reschedule")
CONFIRM = ("POST", f"/api/v1/appointments/{REFERENCE}/confirm")
LOOKUP = ("POST", "/api/v1/appointments/lookup")
SEARCH = ("POST", "/api/v1/appointments/search-by-national-id")
RESOLVE = ("POST", "/api/v1/patients/resolve")


def _create_body(**overrides):
    return {"national_id": NATIONAL_ID, "slot_id": str(uuid4()), "service_id": str(uuid4()),
            "channel": "voice", **overrides}


VALID = {
    CREATE: _create_body,
    CANCEL: lambda **o: {"national_id": NATIONAL_ID, **o},
    RESCHEDULE: lambda **o: {"national_id": NATIONAL_ID, "new_slot_id": str(uuid4()), **o},
    CONFIRM: lambda **o: {"national_id": NATIONAL_ID, **o},
    LOOKUP: lambda **o: {"national_id": NATIONAL_ID, "appointment_reference": REFERENCE, **o},
    SEARCH: lambda **o: {"national_id": NATIONAL_ID, **o},
    RESOLVE: lambda **o: {"national_id": NATIONAL_ID, "patient_name": "Test Patient",
                          "phone": "+20100000000", "channel": "voice", **o},
}


def _code(response):
    return response.json()["detail"]["code"]


# ============================================================ success contracts


@pytest.mark.parametrize(
    "route, status, service_method, response_keys",
    [
        (CREATE, 201, "create_confirmed_booking", set(AppointmentCreateResponse.model_fields)),
        (CANCEL, 200, "cancel_booking", set(AppointmentCancelResponse.model_fields)),
        (RESCHEDULE, 200, "reschedule_booking", set(AppointmentRescheduleResponse.model_fields)),
        (CONFIRM, 200, "confirm_booking", set(AppointmentConfirmResponse.model_fields)),
        (LOOKUP, 200, "lookup_booking_for_patient", set(AppointmentLookupResponse.model_fields)),
        (SEARCH, 200, "search_bookings_by_national_id", set(AppointmentsByNationalIdResponse.model_fields)),
        (RESOLVE, 200, "resolve_for_booking", set(PatientResolution.model_fields)),
    ],
)
def test_each_route_returns_its_response_contract(api, route, status, service_method, response_keys):
    response = api.call(*route, VALID[route]())

    assert response.status_code == status
    assert set(response.json()) == response_keys
    assert [name for name, _ in api.services.calls] == [service_method]
    assert NATIONAL_ID not in response.text  # never echoed back


@pytest.mark.parametrize("route", [CREATE, CANCEL, RESCHEDULE, CONFIRM, LOOKUP, SEARCH, RESOLVE])
@pytest.mark.parametrize("tenant, provider", [("clinic-001", PROVIDER_A), ("clinic-002", PROVIDER_B)])
def test_the_service_gets_the_provider_resolved_from_the_tenant_header(api, route, tenant, provider):
    api.call(*route, VALID[route](), tenant=tenant)

    (_, kwargs), = api.services.calls
    assert kwargs["provider_id"] == provider.id
    if "provider_timezone" in kwargs:
        assert kwargs["provider_timezone"] == provider.timezone


@pytest.mark.parametrize("route", [CANCEL, RESCHEDULE, CONFIRM])
def test_the_path_reference_reaches_the_service_unchanged(api, route):
    method, path = route
    lower = path.replace(REFERENCE, REFERENCE.lower())

    api.call(method, lower, VALID[route]())

    (_, kwargs), = api.services.calls
    assert kwargs["appointment_reference"] == REFERENCE.lower()  # the service normalizes


def test_create_passes_the_validated_request(api):
    body = _create_body(notes="ground floor", created_by_type="patient", created_by_reference="session-1")

    api.call(*CREATE, body)

    (_, kwargs), = api.services.calls
    data = kwargs["data"]
    assert (str(data.slot_id), str(data.service_id), data.channel) == (body["slot_id"], body["service_id"], "voice")
    assert (data.notes, data.created_by_type, data.created_by_reference) == ("ground floor", "patient", "session-1")


def test_create_defaults_attribution_to_the_ai_agent(api):
    api.call(*CREATE, _create_body())

    (_, kwargs), = api.services.calls
    assert kwargs["data"].created_by_type == "ai_agent"


def test_resolve_passes_every_field_and_the_tenant_timezone(api):
    api.call(*RESOLVE, VALID[RESOLVE](preferred_language="en", channel="whatsapp"), tenant="clinic-002")

    (_, kwargs), = api.services.calls
    assert kwargs == {
        "provider_id": PROVIDER_B.id, "provider_timezone": PROVIDER_B.timezone,
        "national_id": NATIONAL_ID, "patient_name": "Test Patient", "phone": "+20100000000",
        "preferred_language": "en", "channel": "whatsapp",
    }


def test_resolve_response_masks_the_national_id(api):
    response = api.call(*RESOLVE, VALID[RESOLVE]())

    patient = response.json()["patient"]
    assert patient["masked_national_id"].endswith("4567")
    assert "national_id" not in patient


def test_search_defaults_and_bounds(api):
    api.call(*SEARCH, VALID[SEARCH]())

    (_, kwargs), = api.services.calls
    data = kwargs["data"]
    assert (data.include_cancelled, data.future_only, data.limit) == (False, False, 20)


# ============================================================ Idempotency-Key


@pytest.mark.parametrize("route", [CREATE, CANCEL, RESCHEDULE])
def test_idempotency_key_is_optional_and_passed_through(api, route):
    api.call(*route, VALID[route]())
    api.call(*route, VALID[route](), key="voice-call-0001-attempt")

    (_, first), (_, second) = api.services.calls
    assert first["idempotency_key"] is None
    assert second["idempotency_key"] == "voice-call-0001-attempt"


@pytest.mark.parametrize("route", [CREATE, CANCEL, RESCHEDULE])
@pytest.mark.parametrize("key", ["short", "x" * 129])
def test_idempotency_key_length_is_validated(api, route, key):
    response = api.call(*route, VALID[route](), key=key)

    assert response.status_code == 422
    assert api.services.calls == []


@pytest.mark.parametrize("route", [CREATE, CANCEL, RESCHEDULE])
@pytest.mark.parametrize("key", ["k" * 8, "k" * 128])
def test_idempotency_key_length_bounds_are_inclusive(api, route, key):
    response = api.call(*route, VALID[route](), key=key)

    assert response.status_code != 422
    assert api.services.calls[0][1]["idempotency_key"] == key


@pytest.mark.parametrize("route", [CONFIRM, LOOKUP, SEARCH, RESOLVE])
def test_routes_without_idempotency_ignore_the_header(api, route):
    response = api.call(*route, VALID[route](), key="short")  # would be 422 on create

    assert response.status_code == 200
    assert "idempotency_key" not in api.services.calls[0][1]


@pytest.mark.parametrize(
    "code, status_code",
    [("IDEMPOTENCY_CONFLICT", 409), ("IDEMPOTENCY_IN_PROGRESS", 409), ("IDEMPOTENCY_UNAVAILABLE", 503)],
)
def test_idempotency_errors_from_the_service_keep_their_contract(api, code, status_code):
    api.services.error = HTTPException(status_code=status_code, detail={"code": code, "message": "fake"})

    response = api.call(*CREATE, _create_body(), key="voice-call-0001-attempt")

    assert response.status_code == status_code
    assert response.json() == {"detail": {"code": code, "message": "fake"}}


# ============================================================ national_id and validation

NATIONAL_ID_ROUTES = [CREATE, CANCEL, RESCHEDULE, CONFIRM, LOOKUP, SEARCH, RESOLVE]


@pytest.mark.parametrize("route", NATIONAL_ID_ROUTES)
@pytest.mark.parametrize("national_id", [None, "", "2900101123456", "290010112345678"])
def test_every_route_requires_a_14_character_national_id(api, route, national_id):
    body = VALID[route]()
    if national_id is None:
        body.pop("national_id")
    else:
        body["national_id"] = national_id

    response = api.call(*route, body)

    assert response.status_code == 422
    assert api.services.calls == []


@pytest.mark.parametrize(
    "route, overrides",
    [
        (CREATE, {"slot_id": "not-a-uuid"}),
        (CREATE, {"service_id": None}),
        (CREATE, {"channel": "sms"}),
        (CREATE, {"notes": "x" * 2001}),
        (CREATE, {"created_by_type": "doctor"}),
        (CREATE, {"created_by_reference": "x" * 101}),
        (CANCEL, {"reason": "x" * 501}),
        (CANCEL, {"changed_by": "robot"}),
        (CANCEL, {"actor_reference": "x" * 101}),
        (RESCHEDULE, {"new_slot_id": "not-a-uuid"}),
        (RESCHEDULE, {"new_slot_id": None}),
        (RESCHEDULE, {"reason": "x" * 501}),
        (CONFIRM, {"changed_by": "robot"}),
        (LOOKUP, {"appointment_reference": "APT1"}),
        (LOOKUP, {"appointment_reference": "A" * 41}),
        (SEARCH, {"limit": 0}),
        (SEARCH, {"limit": 101}),
        (RESOLVE, {"patient_name": "X"}),
        (RESOLVE, {"phone": "1234567"}),
        (RESOLVE, {"channel": "sms"}),
        (RESOLVE, {"preferred_language": "fr"}),
    ],
)
def test_invalid_fields_are_rejected_before_the_service(api, route, overrides):
    body = VALID[route]()
    for key, value in overrides.items():
        if value is None:
            body.pop(key, None)
        else:
            body[key] = value

    response = api.call(*route, body)

    assert response.status_code == 422
    assert api.services.calls == []


@pytest.mark.parametrize("route", NATIONAL_ID_ROUTES)
def test_a_malformed_json_body_is_422(api, route):
    response = api.call(*route, None)

    assert response.status_code == 422
    assert api.services.calls == []


# ============================================================ error contracts


@pytest.mark.parametrize(
    "route, status_code, code",
    [
        (CREATE, 409, "SLOT_UNAVAILABLE"),
        (CREATE, 404, "PATIENT_NOT_FOUND"),
        (CANCEL, 404, "APPOINTMENT_NOT_FOUND"),
        (CANCEL, 409, "APPOINTMENT_NOT_CANCELLABLE"),
        (RESCHEDULE, 409, "SLOT_UNAVAILABLE"),
        (CONFIRM, 409, "APPOINTMENT_NOT_CONFIRMABLE"),
        (LOOKUP, 404, "APPOINTMENT_NOT_FOUND"),
        (SEARCH, 422, "INVALID_NATIONAL_ID"),
        (RESOLVE, 422, "INVALID_NATIONAL_ID"),
    ],
)
def test_service_errors_keep_the_code_and_message_shape(api, route, status_code, code):
    api.services.error = HTTPException(status_code=status_code, detail={"code": code, "message": "fake"})

    response = api.call(*route, VALID[route]())

    assert response.status_code == status_code
    assert response.json() == {"detail": {"code": code, "message": "fake"}}


@pytest.mark.parametrize("route", NATIONAL_ID_ROUTES)
def test_an_unknown_tenant_is_404_before_the_service(api, route):
    # The token is valid and checked first; then the tenant lookup finds nothing.
    response = api.call(*route, VALID[route](), tenant="no-such-clinic")

    assert response.status_code == 404
    assert _code(response) == "PROVIDER_NOT_FOUND"
    assert api.services.calls == []
