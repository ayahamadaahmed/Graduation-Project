"""Gateway caller policy: mcp_server is booking-only.

The gateway routes (/ai/*, post-call, diagnostic attachments, and the
development-only debug route) accept gateway services only and refuse the
booking-only mcp_server identity with 403 SERVICE_NOT_ALLOWED, right after
the token check and before any tenant lookup. The booking/patient routes stay
mcp_server-only. No database, no network, no AI; test-only tokens.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

from app.api import dependencies as deps
from app.api.routers import diagnostics, medmind_ai, post_call
from app.core.config import get_settings
from app.security.service_auth import SERVICE_TOKEN_HEADER
from tests.test_booking_service_auth import (  # noqa: F401  world is a fixture
    MCP_TOKEN as BOOKING_MCP_TOKEN,
    PROTECTED,
    VOICE_TOKEN as BOOKING_VOICE_TOKEN,
    world,
)
from tests.test_service_auth_before_tenant_lookup import ROUTES, Everything
from tests.test_staging_safety import (  # noqa: F401  clean_env, no_database are fixtures
    MCP_BACKEND_TOKEN as PREFLIGHT_MCP_TOKEN,
    VOICE_TOKEN as PREFLIGHT_VOICE_TOKEN,
    _preflight,
    _valid_auth_env,
    clean_env,
    no_database,
)

VOICE_TOKEN = "voice-gateway-test-token-0123456789abcdef"
MCP_TOKEN = "mcp-server-test-token-0123456789abcdef0123"
WRONG_TOKEN = "wrong-token-0123456789abcdef0123456789"
CREDENTIALS = f"voice_gateway={VOICE_TOKEN}@clinic-001;mcp_server={MCP_TOKEN}@clinic-001,clinic-002"

PROVIDERS = {
    "clinic-001": SimpleNamespace(id=uuid4(), tenant_key="clinic-001", org_type="clinic"),
    "clinic-002": SimpleNamespace(id=uuid4(), tenant_key="clinic-002", org_type="clinic"),
}

SERVICE_AUTH_CODES = {
    "SERVICE_AUTH_REQUIRED", "SERVICE_AUTH_INVALID", "SERVICE_AUTH_NOT_CONFIGURED",
    "SERVICE_TENANT_NOT_ALLOWED", "SERVICE_NOT_ALLOWED",
}


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setenv("MEDMIND_SERVICE_CREDENTIALS", CREDENTIALS)
    get_settings.cache_clear()
    lookups = []

    def recording_provider(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
        lookups.append(x_tenant_id)  # stands in for the tenant database lookup
        return PROVIDERS[x_tenant_id]

    app = FastAPI()
    for router in (post_call.router, medmind_ai.router, diagnostics.router):
        app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[deps.get_current_provider] = recording_provider
    for dep in (deps.get_appointment_service, deps.get_diagnostic_attachment_service,
                deps.get_diagnostic_attachment_binding_service):
        app.dependency_overrides[dep] = lambda: Everything()
    app.state.medmind_semantic_router = SimpleNamespace(
        route=lambda message, top_k: [SimpleNamespace(name="booking", score=0.9)]
    )
    client = TestClient(app, raise_server_exceptions=False)

    def call(path, kind, body, *, tenant="clinic-001", token=None):
        headers = {"X-Tenant-ID": tenant}
        if token is not None:
            headers[SERVICE_TOKEN_HEADER] = token
        if kind == "json":
            return client.post(path, headers=headers, json=body)
        if kind == "form":
            return client.post(path, headers=headers, data=body, files={"file": ("x.jpg", b"img", "image/jpeg")})
        return client.post(path, headers=headers)

    yield SimpleNamespace(call=call, client=client, lookups=lookups, monkeypatch=monkeypatch)
    get_settings.cache_clear()


def _code(response):
    try:
        return response.json()["detail"]["code"]
    except Exception:
        return None


def test_every_gateway_route_is_covered():
    paths = {path for path, _, _ in ROUTES}
    assert paths == {
        "/api/v1/post-call/booking-confirmation",
        "/api/v1/ai/warmup",
        "/api/v1/ai/sessions",
        "/api/v1/ai/voice/session",
        "/api/v1/ai/sessions/close",
        "/api/v1/ai/chat",
        "/api/v1/ai/chat-v2",
        "/api/v1/diagnostics/attachments",
    }


# ============================================================ mcp_server refused


@pytest.mark.parametrize("tenant", ["clinic-001", "clinic-002"])
@pytest.mark.parametrize("path, kind, body", ROUTES)
def test_mcp_server_is_refused_on_every_gateway_route_before_the_tenant_lookup(gateway, path, kind, body, tenant):
    response = gateway.call(path, kind, body, tenant=tenant, token=MCP_TOKEN)

    assert response.status_code == 403
    assert _code(response) == "SERVICE_NOT_ALLOWED"
    assert gateway.lookups == []  # refused before any tenant data access


def test_the_refusal_logs_the_service_name_not_the_token(gateway, caplog):
    caplog.set_level("DEBUG")
    path, kind, body = ROUTES[0]

    gateway.call(path, kind, body, token=MCP_TOKEN)

    assert "gateway_service_not_allowed service=mcp_server" in caplog.text
    assert MCP_TOKEN not in caplog.text


# ============================================================ voice gateway unchanged


@pytest.mark.parametrize("path, kind, body", ROUTES)
def test_the_voice_gateway_still_passes_service_auth(gateway, path, kind, body):
    response = gateway.call(path, kind, body, token=VOICE_TOKEN)

    assert _code(response) not in SERVICE_AUTH_CODES
    assert gateway.lookups == ["clinic-001"]


@pytest.mark.parametrize("path, kind, body", ROUTES)
def test_the_voice_tenant_allow_list_is_unchanged(gateway, path, kind, body):
    response = gateway.call(path, kind, body, tenant="clinic-002", token=VOICE_TOKEN)

    assert response.status_code == 403
    assert _code(response) == "SERVICE_TENANT_NOT_ALLOWED"
    assert gateway.lookups == ["clinic-002"]


@pytest.mark.parametrize("path, kind, body", ROUTES)
@pytest.mark.parametrize("token, code", [(None, "SERVICE_AUTH_REQUIRED"), (WRONG_TOKEN, "SERVICE_AUTH_INVALID")])
def test_missing_and_wrong_tokens_are_unchanged(gateway, path, kind, body, token, code):
    response = gateway.call(path, kind, body, token=token)

    assert response.status_code == 401
    assert _code(response) == code
    assert gateway.lookups == []


# ============================================================ debug route


def test_debug_route_refuses_mcp_server_in_development(gateway):
    response = gateway.client.get(
        "/api/v1/ai/debug/router", params={"message": "hi"}, headers={SERVICE_TOKEN_HEADER: MCP_TOKEN}
    )

    assert response.status_code == 403
    assert _code(response) == "SERVICE_NOT_ALLOWED"


def test_debug_route_still_serves_the_voice_gateway_in_development(gateway):
    response = gateway.client.get(
        "/api/v1/ai/debug/router", params={"message": "hi"}, headers={SERVICE_TOKEN_HEADER: VOICE_TOKEN}
    )

    assert response.status_code == 200


@pytest.mark.parametrize("app_env", ["production", "staging", "test"])
@pytest.mark.parametrize("token", [VOICE_TOKEN, MCP_TOKEN, None])
def test_debug_route_stays_hidden_outside_development(gateway, app_env, token):
    gateway.monkeypatch.setenv("APP_ENV", app_env)
    get_settings.cache_clear()
    headers = {SERVICE_TOKEN_HEADER: token} if token else {}

    response = gateway.client.get("/api/v1/ai/debug/router", params={"message": "hi"}, headers=headers)

    assert response.status_code == 404


# ============================================================ booking routes unchanged


@pytest.mark.parametrize("auth_mode", ["audit", "enforce"])
@pytest.mark.parametrize("method, path, body", PROTECTED)
def test_mcp_server_still_reaches_the_booking_routes(world, auth_mode, method, path, body):
    world.mode(auth_mode)

    response = world.call(method, path, body, token=BOOKING_MCP_TOKEN)

    assert response.status_code == 418  # reached the service
    assert world.lookups == ["clinic-001"]


@pytest.mark.parametrize("method, path, body", PROTECTED)
def test_booking_routes_still_refuse_the_voice_gateway(world, method, path, body):
    response = world.call(method, path, body, token=BOOKING_VOICE_TOKEN)

    assert response.status_code == 403
    assert _code(response) == "SERVICE_NOT_ALLOWED"


@pytest.mark.parametrize("method, path, body", PROTECTED)
def test_booking_tenant_allow_list_is_unchanged(world, method, path, body):
    response = world.call(method, path, body, tenant="clinic-002", token=BOOKING_MCP_TOKEN)

    assert response.status_code == 403
    assert _code(response) == "SERVICE_TENANT_NOT_ALLOWED"


def test_mcp_confirmation_still_works(world):
    response = world.call(
        "post", "/api/v1/appointments/APT-260828-ABC123/confirm",
        {"national_id": "29001011234567"}, token=BOOKING_MCP_TOKEN,
    )

    assert response.status_code == 200


# ============================================================ preflight


def test_preflight_fails_a_voice_gateway_using_the_mcp_server_token(clean_env, no_database):
    report, output = _preflight(**_valid_auth_env(MEDMIND_SERVICE_TOKEN=PREFLIGHT_MCP_TOKEN))

    assert report.failed
    assert (
        "FAIL  voice gateway -> /ai/chat: MEDMIND_SERVICE_TOKEN is a booking-only (mcp_server) "
        "credential; gateway routes refuse it with 403 SERVICE_NOT_ALLOWED"
    ) in output
    assert PREFLIGHT_MCP_TOKEN not in output


def test_preflight_labels_gateway_and_booking_only_services(clean_env, no_database):
    report, output = _preflight(**_valid_auth_env())

    assert not report.failed
    assert "service mcp_server: booking-only" in output
    assert "service voice_gateway: gateway" in output


def test_preflight_ai_tenants_count_gateway_services_only(clean_env, no_database):
    # mcp_server's own extra tenants are not /ai/chat tenants any more.
    report, output = _preflight(
        **_valid_auth_env(
            MEDMIND_SERVICE_CREDENTIALS=(
                f"voice_gateway={PREFLIGHT_VOICE_TOKEN}@clinic-001;"
                f"mcp_server={PREFLIGHT_MCP_TOKEN}@clinic-001,clinic-009"
            ),
        )
    )

    assert not report.failed
    assert "OK    AI booking tenants: every gateway (/ai/chat) tenant is in the mcp_server credential" in output
