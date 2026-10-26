"""API Blueprint path aliases (2026-10-22): each new path reuses the existing
handler and must behave exactly like its original.

- GET /api/v1/providers, GET /api/v1/providers/{id}/branches
  -> GET /api/v1/public/providers, /api/v1/public/providers/{id}/branches
- POST /api/v1/ai/voice/session -> POST /api/v1/ai/sessions with channel "voice"
  (gateway/tenant auth for it runs with every other gateway route in
  test_service_auth_before_tenant_lookup.py and test_gateway_service_policy.py)
- GET /api/v1/health, GET /api/v1/ready -> GET /health, GET /ready

Real routers on the real application where wiring matters; only the catalog
service, the agent and the database engine are fakes. No database, network
or AI. Test-only values.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.main as backend_main
from app.api import dependencies as deps
from app.core.config import get_settings
from tests.test_ai_chat_service_auth import (  # noqa: F401  api is a fixture
    CREDENTIALS,
    VOICE_TOKEN,
    WHATSAPP_TOKEN,
    _chat,
    _h,
    api,
)
from tests.test_catalog_patient_ops_http import (  # noqa: F401  health_client is a fixture
    PROVIDER_A,
    UNLISTED_PROVIDER_ID,
    FakeCatalogService,
    health_client,
)

# ============================================================ catalog aliases


@pytest.fixture
def real_app_catalog():
    """The real application, with only the catalog service replaced."""
    catalog_service = FakeCatalogService()
    backend_main.app.dependency_overrides[deps.get_catalog_service] = lambda: catalog_service
    try:
        yield TestClient(backend_main.app), catalog_service
    finally:
        backend_main.app.dependency_overrides.pop(deps.get_catalog_service, None)


def _same(client, original, alias, **kwargs):
    first, second = client.get(original, **kwargs), client.get(alias, **kwargs)
    assert second.status_code == first.status_code
    assert second.json() == first.json()
    return second


@pytest.mark.parametrize("org_type", ["clinic", "hospital", "diagnostic_lab"])
def test_providers_alias_matches_the_public_list(real_app_catalog, org_type):
    client, catalog_service = real_app_catalog

    response = _same(client, "/api/v1/public/providers", "/api/v1/providers", params={"org_type": org_type})

    assert response.status_code == 200
    assert catalog_service.calls[-2:] == [("get_public_providers", org_type)] * 2


@pytest.mark.parametrize("params", [{"org_type": "pharmacy"}, {"org_type": ""}])
def test_providers_alias_rejects_an_invalid_org_type(real_app_catalog, params):
    client, catalog_service = real_app_catalog

    response = _same(client, "/api/v1/public/providers", "/api/v1/providers", params=params)

    assert response.status_code == 422
    assert not [c for c in catalog_service.calls if c[0] == "get_public_providers"]


@pytest.mark.parametrize(
    "provider_id, status_code",
    [(PROVIDER_A.id, 200), (uuid4(), 200), (UNLISTED_PROVIDER_ID, 404), ("not-a-uuid", 422)],
    ids=["branches", "no-branches", "unavailable-provider", "malformed-id"],
)
def test_branches_alias_matches_the_public_branches(real_app_catalog, provider_id, status_code):
    client, _ = real_app_catalog

    response = _same(
        client, f"/api/v1/public/providers/{provider_id}/branches", f"/api/v1/providers/{provider_id}/branches",
    )

    assert response.status_code == status_code
    if status_code == 404:
        assert response.json()["detail"]["code"] == "PUBLIC_PROVIDER_NOT_FOUND"


def test_branches_alias_keeps_the_public_shape(real_app_catalog):
    client, _ = real_app_catalog

    body = client.get(f"/api/v1/providers/{PROVIDER_A.id}/branches").json()

    assert {b["code"] for b in body} == {"A-MAIN", "A-EAST"}
    assert set(body[0]) == {"id", "provider_id", "code", "name_ar", "name_en", "address_ar", "address_en", "governorate"}


def test_catalog_aliases_are_registered_once_under_api_v1(real_app_catalog):
    client, _ = real_app_catalog

    assert client.get("/api/v1/api/v1/providers", params={"org_type": "clinic"}).status_code == 404
    assert client.get("/providers", params={"org_type": "clinic"}).status_code == 404
    assert client.get(f"/providers/{PROVIDER_A.id}/branches").status_code == 404
    paths = backend_main.app.openapi()["paths"]
    assert "/api/v1/providers" in paths
    assert "/api/v1/providers/{provider_id}/branches" in paths
    assert "/api/v1/public/providers" in paths  # the original paths stay


def test_current_provider_route_is_not_shadowed(real_app_catalog):
    _, catalog_service = real_app_catalog
    # Routing only: the fake provider is not a full ProviderOut, so the
    # handler's own response is not asserted here.
    client = TestClient(backend_main.app, raise_server_exceptions=False)

    # /providers/current resolves the tenant, not the public list.
    client.get("/api/v1/providers/current", headers={"X-Tenant-ID": "clinic-001"})

    assert ("get_provider", "clinic-001") in catalog_service.calls
    assert not [c for c in catalog_service.calls if c[0] == "get_public_providers"]


# ============================================================ voice session alias


def _voice_session(api, **kw):
    return api.client.post("/api/v1/ai/voice/session", headers=_h(**kw))


def test_voice_session_alias_creates_a_voice_session_like_ai_sessions(api):
    original = api.client.post("/api/v1/ai/sessions", json={"channel": "voice"}, headers=_h())
    alias = _voice_session(api)

    assert (alias.status_code, original.status_code) == (201, 201)
    assert set(alias.json()) == set(original.json())
    assert alias.json()["channel"] == "voice"
    assert alias.json()["idle_timeout_seconds"] == original.json()["idle_timeout_seconds"]
    assert alias.json()["session_id"] != original.json()["session_id"]


def test_voice_session_alias_cannot_be_switched_to_another_channel(api):
    response = api.client.post("/api/v1/ai/voice/session", json={"channel": "web"}, headers=_h())

    assert response.status_code == 201
    assert response.json()["channel"] == "voice"


def test_voice_session_alias_session_works_for_voice_chat_and_close(api):
    session_id = _voice_session(api).json()["session_id"]

    assert _chat(api, session_id, channel="voice").status_code == 200
    assert api.agent.chat_calls[0]["session_id"] == session_id
    # Bound to the voice channel, like a voice session from /ai/sessions.
    assert _chat(api, session_id, channel="web").status_code == 404
    closed = api.client.post("/api/v1/ai/sessions/close", json={"session_id": session_id}, headers=_h())
    assert closed.status_code == 204


def test_voice_session_alias_is_bound_to_its_service_and_tenant(api):
    session_id = _voice_session(api, token=VOICE_TOKEN).json()["session_id"]

    assert _chat(api, session_id, channel="voice", token=WHATSAPP_TOKEN).status_code == 404
    assert _chat(api, session_id, channel="voice", tenant="clinic-002").status_code == 404
    assert not api.agent.chat_calls


@pytest.mark.parametrize("token, status_code", [(None, 401), ("wrong-token-0123456789abcdef0123456789", 401)])
def test_voice_session_alias_rejects_missing_or_invalid_tokens(api, token, status_code):
    assert _voice_session(api, token=token).status_code == status_code


def test_voice_session_alias_rejects_a_tenant_outside_the_allow_list(api):
    response = _voice_session(api, tenant="clinic-002", token=WHATSAPP_TOKEN)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SERVICE_TENANT_NOT_ALLOWED"


def test_voice_session_alias_is_registered_on_the_real_application(monkeypatch):
    monkeypatch.setenv("MEDMIND_SERVICE_CREDENTIALS", CREDENTIALS)
    get_settings.cache_clear()
    try:
        client = TestClient(backend_main.app)
        # The token is checked before any tenant lookup: 401 proves the route
        # exists (404 otherwise) without touching the database.
        response = client.post("/api/v1/ai/voice/session", headers={"X-Tenant-ID": "clinic-001"})
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "SERVICE_AUTH_REQUIRED"
        assert client.post("/api/v1/api/v1/ai/voice/session").status_code == 404
    finally:
        get_settings.cache_clear()


# ============================================================ health aliases

HEALTH_PAIRS = [("/health", "/api/v1/health"), ("/ready", "/api/v1/ready")]


@pytest.mark.parametrize("original, alias", HEALTH_PAIRS)
@pytest.mark.parametrize("fail", [False, True], ids=["reachable", "unreachable"])
def test_health_aliases_match_the_root_routes(health_client, original, alias, fail):
    client, engine = health_client
    engine.fail = fail

    first, second = client.get(original), client.get(alias)

    assert second.status_code == first.status_code == (503 if fail else 200)
    assert second.json() == first.json()
    # Unauthenticated: exactly these keys, nothing about the database itself.
    assert set(second.json()) == {"status", "database"}
    assert get_settings().db_name not in second.text
    assert "simulated outage" not in second.text


@pytest.mark.parametrize("alias", ["/api/v1/health", "/api/v1/ready"])
def test_health_aliases_run_the_same_check_without_auth(health_client, alias):
    client, engine = health_client

    response = client.get(alias, headers={})

    assert response.status_code == 200
    assert engine.statements == ["SELECT 1"]
