"""MCP -> Backend authentication on the booking and patient routes, and the
service-or-staff rule on appointment confirmation (app/security/booking_auth.py).

The tenant lookup is replaced by a recorder so we can prove credentials are
checked first. Services are fakes; no database, no network. All tokens are
test-only values.
"""

import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import dependencies as deps
from app.api.routers import appointments, catalog, patients
from app.core.config import Settings, get_settings
from app.schemas.appointment import AppointmentConfirmResponse
from app.security.service_auth import SERVICE_TOKEN_HEADER
from app.security.tokens import create_access_token
from app.services.staff_access_service import StaffAccessService
from tests.test_admin_ops_rbac_api import StubAudit
from tests.test_current_staff_resolution import FakeAuthRepository

MCP_TOKEN = "mcp-server-test-token-0123456789abcdef0123"
VOICE_TOKEN = "voice-gateway-test-token-0123456789abcdef"
WRONG_TOKEN = "wrong-token-0123456789abcdef0123456789"
CREDENTIALS = f"mcp_server={MCP_TOKEN}@clinic-001;voice_gateway={VOICE_TOKEN}@clinic-001"
TEST_JWT_SECRET = "test-only-signing-key-not-production-0123456789abcdef"
NATIONAL_ID = "29001011234567"

PROVIDERS = {
    "clinic-001": SimpleNamespace(id=uuid4(), tenant_key="clinic-001", timezone="Africa/Cairo"),
    "clinic-002": SimpleNamespace(id=uuid4(), tenant_key="clinic-002", timezone="Africa/Cairo"),
}

# Every booking/patient route the MCP server calls (mcp_server/tools/*).
PROTECTED = [
    ("post", "/api/v1/appointments",
     {"national_id": NATIONAL_ID, "slot_id": str(uuid4()), "service_id": str(uuid4()), "channel": "voice"}),
    ("post", "/api/v1/appointments/APT-260828-ABC123/cancel", {"national_id": NATIONAL_ID}),
    ("post", "/api/v1/appointments/APT-260828-ABC123/reschedule",
     {"national_id": NATIONAL_ID, "new_slot_id": str(uuid4())}),
    ("post", "/api/v1/appointments/lookup",
     {"national_id": NATIONAL_ID, "appointment_reference": "APT-260828-ABC123"}),
    ("post", "/api/v1/appointments/search-by-national-id", {"national_id": NATIONAL_ID}),
    ("post", "/api/v1/patients/resolve",
     {"national_id": NATIONAL_ID, "patient_name": "Test Patient", "phone": "+201000000000", "channel": "voice"}),
    ("post", "/api/v1/patients/lookup", {"national_id": NATIONAL_ID}),
    ("patch", f"/api/v1/patients/{uuid4()}/profile",
     {"national_id": NATIONAL_ID, "patient_name": "Test Patient", "language": "ar", "channel": "voice"}),
]
CONFIRM = "/api/v1/appointments/APT-260828-ABC123/confirm"


class Recorder:
    """Any service call is recorded and answered with 418, i.e. 'auth let it through'."""

    def __init__(self):
        self.calls = []

    def confirm_booking(self, **kwargs):
        self.calls.append(("confirm_booking", kwargs))
        if kwargs.get("audit") is not None:
            kwargs["audit"]("appointment-id")
        return AppointmentConfirmResponse(
            appointment_reference="APT-260828-ABC123",
            previous_status="pending",
            status="confirmed",
            confirmed_at=None,
        )

    def __getattr__(self, name):
        def reached(*args, **kwargs):
            self.calls.append((name, kwargs))
            raise HTTPException(status_code=418, detail={"code": "REACHED"})
        return reached


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setenv("MEDMIND_SERVICE_CREDENTIALS", CREDENTIALS)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    monkeypatch.setenv("BOOKING_SERVICE_AUTH_MODE", "enforce")
    get_settings.cache_clear()

    lookups = []

    def recording_provider(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
        lookups.append(x_tenant_id)  # stands in for the tenant database lookup
        return PROVIDERS[x_tenant_id]

    service, audit = Recorder(), StubAudit()
    state = SimpleNamespace(access=None)

    app = FastAPI()
    for router in (appointments.router, patients.router, catalog.router):
        app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[deps.get_current_provider] = recording_provider
    for dep in (deps.get_appointment_service, deps.get_patient_service, deps.get_catalog_service):
        app.dependency_overrides[dep] = lambda: service
    app.dependency_overrides[deps.get_staff_audit_service] = lambda: audit
    app.dependency_overrides[deps.get_staff_access_service] = lambda: state.access or object()

    def call(method, path, body=None, *, tenant="clinic-001", token=None, bearer=None):
        headers = {"X-Tenant-ID": tenant}
        if token is not None:
            headers[SERVICE_TOKEN_HEADER] = token
        if bearer is not None:
            headers["Authorization"] = f"Bearer {bearer}"
        return client.request(method.upper(), path, headers=headers, json=body)

    def mode(value):
        monkeypatch.setenv("BOOKING_SERVICE_AUTH_MODE", value)
        get_settings.cache_clear()

    def staff(role, provider="clinic-001", *, active=True):
        user = SimpleNamespace(id=uuid4())
        membership = SimpleNamespace(
            id=uuid4(), provider_id=PROVIDERS[provider].id, role=role,
            doctor_id=uuid4() if role == "doctor" else None,
        )
        # An inactive or removed membership is not returned by the repository.
        state.access = StaffAccessService(
            FakeAuthRepository(user=user, membership=membership if active else None)
        )
        token = create_access_token(
            user_id=user.id, membership_id=membership.id, provider_id=PROVIDERS[provider].id,
        )
        return token, user

    client = TestClient(app)
    yield SimpleNamespace(
        call=call, mode=mode, staff=staff, lookups=lookups, service=service, audit=audit,
    )
    get_settings.cache_clear()


def _code(response):
    return response.json()["detail"]["code"]


# ============================================================ route coverage


def test_every_mcp_booking_route_checks_the_service_before_the_tenant():
    def dependency_names(router, path, method):
        route = next(r for r in router.routes if r.path == path and method in r.methods)
        return [d.call.__name__ for d in route.dependant.dependencies]

    for router, path, method in [
        (appointments.router, "/appointments", "POST"),
        (appointments.router, "/appointments/{appointment_reference}/cancel", "POST"),
        (appointments.router, "/appointments/{appointment_reference}/reschedule", "POST"),
        (appointments.router, "/appointments/lookup", "POST"),
        (appointments.router, "/appointments/search-by-national-id", "POST"),
        (patients.router, "/patients/resolve", "POST"),
        (patients.router, "/patients/lookup", "POST"),
        (patients.router, "/patients/{patient_id}/profile", "PATCH"),
    ]:
        assert dependency_names(router, path, method)[0] == "require_booking_service", path

    confirm = dependency_names(appointments.router, "/appointments/{appointment_reference}/confirm", "POST")
    assert confirm[0] == "require_confirm_credentials"
    assert "require_confirm_caller" in confirm

    # Staff reads keep staff auth only.
    for path in ("/appointments/reference/{appointment_reference}", "/appointments/patient/{patient_id}"):
        assert "require_booking_service" not in dependency_names(appointments.router, path, "GET")


# ============================================================ MCP -> Backend


@pytest.mark.parametrize("auth_mode", ["audit", "enforce"])
@pytest.mark.parametrize("method, path, body", PROTECTED)
def test_an_invalid_token_is_rejected_in_every_mode_before_the_tenant_lookup(world, auth_mode, method, path, body):
    world.mode(auth_mode)

    for token, code in [(WRONG_TOKEN, "SERVICE_AUTH_INVALID"), ("", "SERVICE_AUTH_REQUIRED")]:
        response = world.call(method, path, body, token=token)
        assert response.status_code == 401
        assert _code(response) == code

    assert world.lookups == []
    assert world.service.calls == []


@pytest.mark.parametrize("method, path, body", PROTECTED)
def test_enforce_mode_rejects_a_missing_token_before_the_tenant_lookup(world, method, path, body):
    response = world.call(method, path, body)

    assert response.status_code == 401
    assert _code(response) == "SERVICE_AUTH_REQUIRED"
    assert world.lookups == [] and world.service.calls == []


@pytest.mark.parametrize("method, path, body", PROTECTED)
def test_enforce_mode_without_configured_credentials_fails_closed(world, monkeypatch, method, path, body):
    monkeypatch.delenv("MEDMIND_SERVICE_CREDENTIALS")
    monkeypatch.setattr(Settings, "model_config", {**Settings.model_config, "env_file": None})
    get_settings.cache_clear()

    for token in (None, MCP_TOKEN):
        response = world.call(method, path, body, token=token)
        assert response.status_code == 503
        assert _code(response) == "SERVICE_AUTH_NOT_CONFIGURED"

    assert world.lookups == [] and world.service.calls == []


@pytest.mark.parametrize("method, path, body", PROTECTED)
def test_audit_mode_accepts_a_missing_token_and_logs_only_the_route(world, caplog, method, path, body):
    world.mode("audit")
    caplog.set_level(logging.DEBUG)

    response = world.call(method, path, body)

    assert response.status_code == 418  # reached the service
    assert world.lookups == ["clinic-001"]
    warnings = [r.getMessage() for r in caplog.records if "booking_service_auth_missing" in r.getMessage()]
    assert len(warnings) == 1
    assert "mode=audit" in warnings[0]
    # The route template only: no reference, patient id or national id.
    assert "APT-260828-ABC123" not in warnings[0]
    assert NATIONAL_ID not in caplog.text
    if "{patient_id}" in warnings[0]:
        assert path.split("/")[4] not in warnings[0]


@pytest.mark.parametrize("auth_mode", ["audit", "enforce"])
@pytest.mark.parametrize("method, path, body", PROTECTED)
def test_a_valid_mcp_token_for_an_allowed_tenant_reaches_the_service(world, auth_mode, method, path, body):
    world.mode(auth_mode)

    response = world.call(method, path, body, token=MCP_TOKEN)

    assert response.status_code == 418
    assert world.lookups == ["clinic-001"]  # one tenant lookup
    assert len(world.service.calls) == 1


@pytest.mark.parametrize("auth_mode", ["audit", "enforce"])
@pytest.mark.parametrize("method, path, body", PROTECTED)
def test_a_tenant_outside_the_mcp_allow_list_is_rejected(world, auth_mode, method, path, body):
    world.mode(auth_mode)

    response = world.call(method, path, body, tenant="clinic-002", token=MCP_TOKEN)

    assert response.status_code == 403
    assert _code(response) == "SERVICE_TENANT_NOT_ALLOWED"
    assert world.service.calls == []


@pytest.mark.parametrize("method, path, body", PROTECTED)
def test_another_gateways_valid_token_cannot_call_booking_routes(world, method, path, body):
    response = world.call(method, path, body, token=VOICE_TOKEN)

    assert response.status_code == 403
    assert _code(response) == "SERVICE_NOT_ALLOWED"
    assert world.lookups == [] and world.service.calls == []


def test_tokens_never_appear_in_logs(world, caplog):
    caplog.set_level(logging.DEBUG)

    for auth_mode in ("audit", "enforce"):
        world.mode(auth_mode)
        for method, path, body in PROTECTED:
            for token in (MCP_TOKEN, WRONG_TOKEN, VOICE_TOKEN, None):
                world.call(method, path, body, token=token)
                world.call(method, path, body, tenant="clinic-002", token=token)
        world.call("post", CONFIRM, {"national_id": NATIONAL_ID}, token=MCP_TOKEN)
        world.call("post", CONFIRM, {"national_id": NATIONAL_ID}, token=WRONG_TOKEN)

    assert caplog.records  # the warnings were captured
    for secret in (MCP_TOKEN, WRONG_TOKEN, VOICE_TOKEN, NATIONAL_ID):
        assert secret not in caplog.text


def test_an_unknown_auth_mode_fails_settings_loading(monkeypatch):
    monkeypatch.setenv("BOOKING_SERVICE_AUTH_MODE", "off")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)

    monkeypatch.setenv("BOOKING_SERVICE_AUTH_MODE", " Enforce ")
    assert Settings(_env_file=None).booking_service_auth_mode == "enforce"

    monkeypatch.delenv("BOOKING_SERVICE_AUTH_MODE")
    assert Settings(_env_file=None).booking_service_auth_mode == "audit"


# ============================================================ unchanged routes


def test_public_catalog_reads_need_no_service_token_in_enforce_mode(world):
    response = world.call("get", "/api/v1/specialties")

    assert response.status_code == 418  # reached the catalog service
    assert world.lookups == ["clinic-001"]


def test_staff_reads_keep_staff_auth_and_ignore_the_mcp_token(world):
    path = "/api/v1/appointments/reference/APT-260828-ABC123"

    # The MCP credential grants no staff privileges.
    response = world.call("get", path, token=MCP_TOKEN)
    assert response.status_code == 401
    assert _code(response) == "STAFF_AUTH_REQUIRED"

    token, _ = world.staff("receptionist")
    response = world.call("get", path, bearer=token)
    assert response.status_code == 418  # staff read reached without a service token


# ============================================================ confirmation


@pytest.mark.parametrize("auth_mode", ["audit", "enforce"])
def test_confirmation_without_any_credential_is_rejected_in_every_mode(world, auth_mode):
    world.mode(auth_mode)

    response = world.call("post", CONFIRM, {"national_id": NATIONAL_ID})

    assert response.status_code == 401
    assert _code(response) == "AUTH_REQUIRED"
    assert world.lookups == [] and world.service.calls == []


def test_confirmation_rejects_both_credentials_at_once(world):
    token, _ = world.staff("receptionist")

    response = world.call("post", CONFIRM, {"national_id": NATIONAL_ID}, token=MCP_TOKEN, bearer=token)

    assert response.status_code == 400
    assert _code(response) == "MULTIPLE_CREDENTIALS"
    assert world.lookups == [] and world.service.calls == []


@pytest.mark.parametrize("auth_mode", ["audit", "enforce"])
def test_mcp_confirmation_passes_service_and_tenant_checks_and_is_not_staff(world, auth_mode):
    world.mode(auth_mode)

    response = world.call("post", CONFIRM, {"national_id": NATIONAL_ID}, token=MCP_TOKEN)

    assert response.status_code == 200
    (_, kwargs), = world.service.calls
    assert kwargs["provider_id"] == PROVIDERS["clinic-001"].id
    assert kwargs["data"].changed_by == "ai_agent"
    assert kwargs["data"].national_id == NATIONAL_ID  # patient identity still required
    assert kwargs["audit"] is None  # no staff audit row for a service call
    assert world.audit.records == []


@pytest.mark.parametrize(
    "token, tenant, status_code, code",
    [
        (WRONG_TOKEN, "clinic-001", 401, "SERVICE_AUTH_INVALID"),
        (VOICE_TOKEN, "clinic-001", 403, "SERVICE_NOT_ALLOWED"),
        (MCP_TOKEN, "clinic-002", 403, "SERVICE_TENANT_NOT_ALLOWED"),
    ],
)
def test_mcp_confirmation_rejects_bad_service_credentials(world, token, tenant, status_code, code):
    response = world.call("post", CONFIRM, {"national_id": NATIONAL_ID}, tenant=tenant, token=token)

    assert response.status_code == status_code
    assert _code(response) == code
    assert world.service.calls == []


def test_the_mcp_credential_cannot_claim_a_staff_confirmation(world):
    response = world.call(
        "post", CONFIRM, {"national_id": NATIONAL_ID, "changed_by": "staff"}, token=MCP_TOKEN,
    )

    assert response.status_code == 403
    assert _code(response) == "SERVICE_CANNOT_ACT_AS_STAFF"
    assert world.service.calls == []


@pytest.mark.parametrize("role", ["provider_admin", "receptionist"])
def test_staff_confirmation_is_attributed_to_the_user_and_audited(world, role):
    token, user = world.staff(role)

    response = world.call(
        "post", CONFIRM,
        {"national_id": NATIONAL_ID, "changed_by": "patient", "actor_reference": "spoofed"},
        bearer=token,
    )

    assert response.status_code == 200
    (_, kwargs), = world.service.calls
    assert kwargs["provider_id"] == PROVIDERS["clinic-001"].id
    assert kwargs["data"].changed_by == "staff"
    assert kwargs["data"].actor_reference == str(user.id)
    assert kwargs["data"].national_id == NATIONAL_ID
    (record,) = world.audit.records
    assert record["action"] == "appointment.confirm"
    assert record["user_id"] == user.id
    assert record["outcome"] == "success"
    assert world.audit.repository.session.commits == 0  # staged for the service's commit


@pytest.mark.parametrize("role", ["doctor", "lab_staff"])
def test_other_staff_roles_cannot_confirm(world, role):
    token, _ = world.staff(role)

    response = world.call("post", CONFIRM, {"national_id": NATIONAL_ID}, bearer=token)

    assert response.status_code == 403
    assert _code(response) == "STAFF_PERMISSION_DENIED"
    assert world.service.calls == []


def test_a_staff_token_cannot_confirm_for_another_provider(world):
    token, _ = world.staff("provider_admin", provider="clinic-001")

    response = world.call("post", CONFIRM, {"national_id": NATIONAL_ID}, tenant="clinic-002", bearer=token)

    assert response.status_code == 403
    assert _code(response) == "STAFF_TENANT_MISMATCH"
    assert world.service.calls == [] and world.audit.records == []


@pytest.mark.parametrize("role", ["provider_admin", "receptionist"])
def test_a_staff_member_without_an_active_membership_cannot_confirm(world, role):
    token, _ = world.staff(role, active=False)

    response = world.call("post", CONFIRM, {"national_id": NATIONAL_ID}, bearer=token)

    assert response.status_code == 401
    assert _code(response) == "INVALID_STAFF_SESSION"
    assert world.service.calls == [] and world.audit.records == []


@pytest.mark.parametrize("caller", ["provider_admin", "receptionist", "mcp"])
@pytest.mark.parametrize("body", [{}, {"national_id": None}, {"national_id": "123"}, {"changed_by": "staff"}])
def test_confirmation_still_requires_a_valid_national_id(world, caller, body):
    if caller == "mcp":
        response = world.call("post", CONFIRM, body, token=MCP_TOKEN)
    else:
        token, _ = world.staff(caller)
        response = world.call("post", CONFIRM, body, bearer=token)

    assert response.status_code == 422
    assert world.service.calls == [] and world.audit.records == []


def test_the_mcp_credential_cannot_set_staff_identity_even_with_a_staff_reference(world):
    token, user = world.staff("receptionist")

    claimed = world.call(
        "post", CONFIRM,
        {"national_id": NATIONAL_ID, "changed_by": "staff", "actor_reference": str(user.id)},
        token=MCP_TOKEN,
    )
    assert claimed.status_code == 403
    assert _code(claimed) == "SERVICE_CANNOT_ACT_AS_STAFF"
    # The MCP token is not a bearer token either.
    as_bearer = world.call("post", CONFIRM, {"national_id": NATIONAL_ID}, bearer=MCP_TOKEN)
    assert as_bearer.status_code == 401
    assert world.service.calls == [] and world.audit.records == []


def test_staff_confirmation_logs_no_token_or_national_id(world, caplog):
    caplog.set_level(logging.DEBUG)

    for role in ("provider_admin", "receptionist", "doctor"):
        token, _ = world.staff(role)
        world.call("post", CONFIRM, {"national_id": NATIONAL_ID}, bearer=token)
        world.call("post", CONFIRM, {"national_id": NATIONAL_ID}, tenant="clinic-002", bearer=token)
        assert token not in caplog.text
    world.call("post", CONFIRM, {"national_id": NATIONAL_ID}, token=MCP_TOKEN)

    assert len(world.audit.records) == 2  # provider_admin and receptionist only
    for secret in (NATIONAL_ID, MCP_TOKEN):
        assert secret not in caplog.text


def test_an_invalid_staff_token_cannot_confirm(world):
    world.staff("provider_admin")

    response = world.call("post", CONFIRM, {"national_id": NATIONAL_ID}, bearer="not-a-jwt")

    assert response.status_code == 401
    assert _code(response) == "INVALID_ACCESS_TOKEN"
    assert world.service.calls == []


def test_staff_confirmation_works_without_service_credentials_configured(world, monkeypatch):
    monkeypatch.delenv("MEDMIND_SERVICE_CREDENTIALS")
    monkeypatch.setattr(Settings, "model_config", {**Settings.model_config, "env_file": None})
    get_settings.cache_clear()
    token, _ = world.staff("receptionist")

    response = world.call("post", CONFIRM, {"national_id": NATIONAL_ID}, bearer=token)

    assert response.status_code == 200
    assert world.service.calls[0][1]["data"].changed_by == "staff"


# ============================================================ staff attribution on MCP routes

# (method, path, body, attribution field) for create, cancel and reschedule.
ATTRIBUTED = [
    (*PROTECTED[0], "created_by_type"),
    (*PROTECTED[1], "changed_by"),
    (*PROTECTED[2], "changed_by"),
]


@pytest.mark.parametrize("auth_mode", ["audit", "enforce"])
@pytest.mark.parametrize("method, path, body, field", ATTRIBUTED)
def test_the_mcp_credential_cannot_attribute_create_cancel_or_reschedule_to_staff(
    world, auth_mode, method, path, body, field,
):
    world.mode(auth_mode)

    response = world.call(method, path, {**body, field: "staff"}, token=MCP_TOKEN)

    assert response.status_code == 403
    assert _code(response) == "SERVICE_CANNOT_ACT_AS_STAFF"
    assert world.service.calls == []


@pytest.mark.parametrize("method, path, body, field", ATTRIBUTED)
def test_an_unauthenticated_audit_mode_caller_cannot_claim_staff(world, caplog, method, path, body, field):
    world.mode("audit")
    caplog.set_level(logging.DEBUG)

    response = world.call(method, path, {**body, field: "staff"})

    assert response.status_code == 403
    assert _code(response) == "SERVICE_CANNOT_ACT_AS_STAFF"
    assert world.service.calls == []
    assert "staff_attribution_denied caller=unauthenticated" in caplog.text


@pytest.mark.parametrize("method, path, body, field", ATTRIBUTED)
def test_an_unauthenticated_enforce_mode_caller_is_rejected_before_attribution(world, method, path, body, field):
    response = world.call(method, path, {**body, field: "staff"})

    assert response.status_code == 401
    assert _code(response) == "SERVICE_AUTH_REQUIRED"
    assert world.service.calls == [] and world.lookups == []


@pytest.mark.parametrize("auth_mode", ["audit", "enforce"])
@pytest.mark.parametrize("method, path, body, field", ATTRIBUTED)
def test_an_invalid_token_claiming_staff_is_still_rejected_as_invalid(world, auth_mode, method, path, body, field):
    world.mode(auth_mode)

    for token in (WRONG_TOKEN, ""):
        response = world.call(method, path, {**body, field: "staff"}, token=token)
        assert response.status_code == 401
    assert world.service.calls == [] and world.lookups == []


@pytest.mark.parametrize("auth_mode", ["audit", "enforce"])
@pytest.mark.parametrize("method, path, body, field", ATTRIBUTED)
def test_a_staff_bearer_token_does_not_unlock_staff_attribution_on_mcp_routes(
    world, auth_mode, method, path, body, field,
):
    # These routes have no staff authentication; a bearer token proves nothing here.
    world.mode(auth_mode)
    token, _ = world.staff("provider_admin")

    response = world.call(method, path, {**body, field: "staff"}, bearer=token)

    assert response.status_code == (403 if auth_mode == "audit" else 401)
    assert world.service.calls == []


@pytest.mark.parametrize("auth_mode", ["audit", "enforce"])
@pytest.mark.parametrize("method, path, body, field", ATTRIBUTED)
@pytest.mark.parametrize("claimed", [None, "ai_agent", "patient", "system"])
def test_non_staff_attribution_still_reaches_the_service(world, auth_mode, method, path, body, field, claimed):
    world.mode(auth_mode)
    request = dict(body) if claimed is None else {**body, field: claimed}

    response = world.call(method, path, request, token=MCP_TOKEN)

    assert response.status_code == 418  # reached the service
    (_, kwargs), = world.service.calls
    assert getattr(kwargs["data"], field) == (claimed or "ai_agent")  # default unchanged


def test_staff_attribution_denials_never_log_tokens_or_national_ids(world, caplog):
    caplog.set_level(logging.DEBUG)

    for auth_mode in ("audit", "enforce"):
        world.mode(auth_mode)
        for method, path, body, field in ATTRIBUTED:
            for token in (MCP_TOKEN, WRONG_TOKEN, None):
                world.call(method, path, {**body, field: "staff"}, token=token)

    assert "staff_attribution_denied caller=mcp_server" in caplog.text
    for secret in (MCP_TOKEN, WRONG_TOKEN, NATIONAL_ID):
        assert secret not in caplog.text
