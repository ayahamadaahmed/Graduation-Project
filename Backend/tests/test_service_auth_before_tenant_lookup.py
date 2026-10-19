"""Service-only endpoints authenticate the gateway token BEFORE resolving the
tenant/provider (a database lookup), and still enforce the tenant allow-list.

The provider dependency is replaced by a recorder so we can count lookups.
No database, no network.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

import app.security.service_auth as service_auth
from app.api import dependencies as deps
from app.api.routers import diagnostics, medmind_ai, post_call
from app.core.config import get_settings
from app.security.service_auth import SERVICE_TOKEN_HEADER

# Test-only credentials (not real secrets).
VOICE_TOKEN = "voice-gateway-test-token-0123456789abcdef"
CREDENTIALS = f"voice_gateway={VOICE_TOKEN}@clinic-001"
WRONG_TOKEN = "wrong-token-0123456789abcdef0123456789"

PROVIDERS = {
    "clinic-001": SimpleNamespace(id=uuid4(), tenant_key="clinic-001", org_type="clinic"),
    "clinic-002": SimpleNamespace(id=uuid4(), tenant_key="clinic-002", org_type="clinic"),
}

ROUTES = [
    ("/api/v1/post-call/booking-confirmation", "json",
     {"event_type": "booking_confirmation", "appointment_reference": "APT-260828-ABC123", "source": "voice"}),
    ("/api/v1/ai/warmup", "none", None),
    ("/api/v1/ai/sessions", "json", {"channel": "voice"}),
    ("/api/v1/ai/sessions/close", "json", {"session_id": "mms_any"}),
    ("/api/v1/ai/chat", "json", {"session_id": "mms_any", "message": "hi", "channel": "voice"}),
    ("/api/v1/ai/chat-v2", "json", {"session_id": "mms_any", "message": "hi", "channel": "voice"}),
    ("/api/v1/diagnostics/attachments", "form", {"session_id": "mms_any"}),
]


class Everything:
    """Accepts any call; these tests stop at (or just past) authentication."""

    def __getattr__(self, name):
        def anything(*args, **kwargs):
            return None
        return anything


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("MEDMIND_SERVICE_CREDENTIALS", CREDENTIALS)
    get_settings.cache_clear()

    lookups = []

    def recording_provider(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
        lookups.append(x_tenant_id)  # stands in for the tenant database lookup
        return PROVIDERS[x_tenant_id]

    auth_calls = []
    real_authenticate = service_auth.authenticate_service_token

    def counting_authenticate(token, settings):
        auth_calls.append(1)
        return real_authenticate(token, settings)

    monkeypatch.setattr(service_auth, "authenticate_service_token", counting_authenticate)

    app = FastAPI()
    for router in (post_call.router, medmind_ai.router, diagnostics.router):
        app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[deps.get_current_provider] = recording_provider
    for dep in (deps.get_appointment_service, deps.get_diagnostic_attachment_service,
                deps.get_diagnostic_attachment_binding_service):
        app.dependency_overrides[dep] = lambda: Everything()

    # Past authentication the handlers hit do-nothing fakes; surface any handler
    # error as a 500 response instead of raising, since only auth is under test.
    client = TestClient(app, raise_server_exceptions=False)
    yield SimpleNamespace(client=client, lookups=lookups, auth_calls=auth_calls)
    get_settings.cache_clear()


def _call(env, path, kind, body, *, tenant="clinic-001", token=None):
    headers = {"X-Tenant-ID": tenant}
    if token is not None:
        headers[SERVICE_TOKEN_HEADER] = token
    if kind == "json":
        return env.client.post(path, headers=headers, json=body)
    if kind == "form":
        return env.client.post(path, headers=headers, data=body,
                               files={"file": ("x.jpg", b"img", "image/jpeg")})
    return env.client.post(path, headers=headers)


@pytest.mark.parametrize("path, kind, body", ROUTES)
@pytest.mark.parametrize("token, code", [(None, "SERVICE_AUTH_REQUIRED"), (WRONG_TOKEN, "SERVICE_AUTH_INVALID")])
def test_invalid_credentials_never_reach_the_tenant_lookup(env, path, kind, body, token, code):
    response = _call(env, path, kind, body, token=token)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == code
    assert env.lookups == []


@pytest.mark.parametrize("path, kind, body", ROUTES)
def test_unknown_tenant_cannot_be_probed_without_credentials(env, path, kind, body):
    # Before the fix an unknown tenant answered 404 (lookup ran first); now 401.
    response = _call(env, path, kind, body, tenant="no-such-tenant", token=None)
    assert response.status_code == 401
    assert env.lookups == []


@pytest.mark.parametrize("path, kind, body", ROUTES)
def test_unconfigured_credentials_fail_closed_without_lookup(env, monkeypatch, path, kind, body):
    monkeypatch.delenv("MEDMIND_SERVICE_CREDENTIALS")
    get_settings.cache_clear()
    response = _call(env, path, kind, body, token=VOICE_TOKEN)
    assert response.status_code == 503
    assert env.lookups == []


@pytest.mark.parametrize("path, kind, body", ROUTES)
def test_valid_credentials_still_enforce_the_tenant_allow_list(env, path, kind, body):
    response = _call(env, path, kind, body, tenant="clinic-002", token=VOICE_TOKEN)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SERVICE_TENANT_NOT_ALLOWED"
    assert env.lookups == ["clinic-002"]


@pytest.mark.parametrize("path, kind, body", ROUTES)
def test_valid_credentials_for_an_allowed_tenant_pass_auth_once(env, path, kind, body):
    response = _call(env, path, kind, body, tenant="clinic-001", token=VOICE_TOKEN)
    assert response.status_code not in (401, 403, 503) or response.json()["detail"].get("code") not in {
        "SERVICE_AUTH_REQUIRED", "SERVICE_AUTH_INVALID", "SERVICE_AUTH_NOT_CONFIGURED", "SERVICE_TENANT_NOT_ALLOWED"}
    assert env.lookups == ["clinic-001"]
    # The token is verified once per request (cached), not once per dependency.
    assert len(env.auth_calls) == 1


def test_unrelated_routes_keep_their_existing_dependencies():
    def first_dependency(router, path):
        route = next(r for r in router.routes if r.path == path)
        return [d.call.__name__ for d in route.dependant.dependencies][:1]

    assert first_dependency(medmind_ai.router, "/ai/debug/router") == []
    assert first_dependency(diagnostics.router, "/diagnostics/pathology-results") == ["get_current_provider"]
    assert first_dependency(diagnostics.router, "/diagnostics/radiology-results") == ["get_current_provider"]
