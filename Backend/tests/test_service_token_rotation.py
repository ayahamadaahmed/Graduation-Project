"""Token rotation overlap for both hops.

MCP -> Backend: MEDMIND_SERVICE_CREDENTIALS_NEXT (app/security/service_auth.py).
Agent -> MCP:   MCP_SERVER_TOKEN_NEXT (mcp_server/auth.py).

All tokens are test-only values. No database, no network.
"""

import logging

import pytest

from app.core.config import Settings, get_settings
from app.security.service_auth import (
    ServiceCredentialsConfigError,
    authenticate_service_token,
    merge_rotation_credentials,
    parse_service_credentials,
)
from mcp_server.auth import MCPUnauthorizedError, authorize_mcp_request
from mcp_server.config import MCPSettings
from tests.test_booking_service_auth import (  # noqa: F401  world is a fixture
    MCP_TOKEN as OLD_MCP_TOKEN,
    NATIONAL_ID,
    PROTECTED,
    VOICE_TOKEN,
    WRONG_TOKEN,
    world,
)
from tests.test_mcp_service_auth import _headers

NEW_MCP_TOKEN = "mcp-server-next-test-token-0123456789abcdef"
NEW_VOICE_TOKEN = "voice-gateway-next-test-token-0123456789ab"
AGENT_TOKEN = "agent-to-mcp-test-token-0123456789abcdef01"
NEW_AGENT_TOKEN = "agent-to-mcp-next-test-token-0123456789abc"
BACKEND_TOKEN = "mcp-backend-test-token-0123456789abcdef01"

CURRENT = f"mcp_server={OLD_MCP_TOKEN}@clinic-001;voice_gateway={VOICE_TOKEN}@clinic-001"
PROMOTED = f"mcp_server={NEW_MCP_TOKEN}@clinic-001;voice_gateway={VOICE_TOKEN}@clinic-001"
NEXT = f"mcp_server={NEW_MCP_TOKEN}@clinic-001"
CREATE = PROTECTED[0]


def _code(response):
    return response.json()["detail"]["code"]


@pytest.fixture
def rotation(monkeypatch):
    """Set the backend credential env and reload settings."""

    def configure(current=CURRENT, next_value=None, **extra):
        monkeypatch.setenv("MEDMIND_SERVICE_CREDENTIALS", current)
        if next_value is None:
            monkeypatch.delenv("MEDMIND_SERVICE_CREDENTIALS_NEXT", raising=False)
        else:
            monkeypatch.setenv("MEDMIND_SERVICE_CREDENTIALS_NEXT", next_value)
        for name in ("MCP_SERVER_TOKEN", "MCP_SERVER_TOKEN_NEXT"):
            monkeypatch.delenv(name, raising=False)
        for name, value in extra.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()

    return configure


# ============================================================ MCP -> Backend


@pytest.mark.parametrize("auth_mode", ["audit", "enforce"])
def test_during_the_overlap_old_and_new_tokens_both_reach_the_service(world, rotation, auth_mode):
    rotation(next_value=NEXT)
    world.mode(auth_mode)
    method, path, body = CREATE

    for token in (OLD_MCP_TOKEN, NEW_MCP_TOKEN):
        response = world.call(method, path, body, token=token)
        assert response.status_code == 418, token[:8]

    assert len(world.service.calls) == 2


@pytest.mark.parametrize("auth_mode", ["audit", "enforce"])
def test_during_the_overlap_unrelated_tokens_are_still_rejected(world, rotation, auth_mode):
    rotation(next_value=NEXT)
    world.mode(auth_mode)
    method, path, body = CREATE

    for token in (WRONG_TOKEN, NEW_MCP_TOKEN[:-1], NEW_VOICE_TOKEN, ""):
        response = world.call(method, path, body, token=token)
        assert response.status_code == 401
    # Another service's valid token keeps its own identity.
    assert _code(world.call(method, path, body, token=VOICE_TOKEN)) == "SERVICE_NOT_ALLOWED"
    assert world.service.calls == [] and world.lookups == []


@pytest.mark.parametrize("token", [OLD_MCP_TOKEN, NEW_MCP_TOKEN])
def test_tenant_restrictions_hold_for_both_tokens_during_the_overlap(world, rotation, token):
    rotation(next_value=NEXT)
    method, path, body = CREATE

    response = world.call(method, path, body, tenant="clinic-002", token=token)

    assert response.status_code == 403
    assert _code(response) == "SERVICE_TENANT_NOT_ALLOWED"
    assert world.service.calls == []


@pytest.mark.parametrize("auth_mode", ["audit", "enforce"])
def test_after_promotion_the_removed_old_token_is_rejected(world, rotation, auth_mode):
    rotation(current=PROMOTED)  # new token promoted, NEXT removed
    world.mode(auth_mode)
    method, path, body = CREATE

    old = world.call(method, path, body, token=OLD_MCP_TOKEN)
    new = world.call(method, path, body, token=NEW_MCP_TOKEN)

    assert old.status_code == 401 and _code(old) == "SERVICE_AUTH_INVALID"
    assert new.status_code == 418


def test_without_an_overlap_the_next_token_is_not_accepted_early(world, rotation):
    rotation()  # NEXT not configured yet
    method, path, body = CREATE

    response = world.call(method, path, body, token=NEW_MCP_TOKEN)

    assert response.status_code == 401 and _code(response) == "SERVICE_AUTH_INVALID"


def test_both_tokens_map_to_the_same_identity_and_tenants(rotation):
    rotation(next_value=NEXT)
    settings = get_settings()

    old = authenticate_service_token(OLD_MCP_TOKEN, settings)
    new = authenticate_service_token(NEW_MCP_TOKEN, settings)

    assert old == new
    assert (new.name, new.allowed_tenants) == ("mcp_server", frozenset({"clinic-001"}))


def test_an_empty_next_value_means_no_rotation(world, rotation):
    rotation(next_value="  ")
    method, path, body = CREATE

    assert world.call(method, path, body, token=OLD_MCP_TOKEN).status_code == 418
    assert world.call(method, path, body, token=NEW_MCP_TOKEN).status_code == 401


@pytest.mark.parametrize(
    "next_value",
    [
        f"unknown_service={NEW_MCP_TOKEN}@clinic-001",          # not a listed service
        f"mcp_server={NEW_MCP_TOKEN}@clinic-001,clinic-002",    # widens the tenants
        f"mcp_server={NEW_MCP_TOKEN}@clinic-002",               # different tenants
        f"mcp_server={VOICE_TOKEN}@clinic-001",                 # another service's token
        "mcp_server=too-short@clinic-001",                      # below the minimum length
        f"mcp_server={NEW_MCP_TOKEN}@*",                        # wildcard
        f"mcp_server={NEW_MCP_TOKEN}",                          # no tenant list
        "not a credential",
    ],
)
def test_a_bad_next_value_fails_closed_without_a_tenant_lookup(world, rotation, next_value):
    rotation(next_value=next_value)
    method, path, body = CREATE

    for token in (OLD_MCP_TOKEN, NEW_MCP_TOKEN, None):
        response = world.call(method, path, body, token=token)
        assert response.status_code == 503
        assert _code(response) == "SERVICE_AUTH_NOT_CONFIGURED"

    assert world.lookups == [] and world.service.calls == []


def test_the_merge_rejects_reusing_another_services_rotation_token():
    current = parse_service_credentials(
        f"mcp_server={OLD_MCP_TOKEN}@clinic-001;voice_gateway={VOICE_TOKEN}@clinic-001"
    )

    with pytest.raises(ServiceCredentialsConfigError):
        merge_rotation_credentials(
            current,
            f"mcp_server={NEW_MCP_TOKEN}@clinic-001;voice_gateway={NEW_MCP_TOKEN}@clinic-001",
        )

    same = merge_rotation_credentials(current, f"mcp_server={OLD_MCP_TOKEN}@clinic-001")
    assert same["mcp_server"].next_token is None  # same token adds nothing


@pytest.mark.parametrize("agent_variable", ["MCP_SERVER_TOKEN", "MCP_SERVER_TOKEN_NEXT"])
@pytest.mark.parametrize("shared", [OLD_MCP_TOKEN, NEW_MCP_TOKEN])
def test_one_token_can_never_pass_both_hops(world, rotation, agent_variable, shared):
    rotation(next_value=NEXT, **{agent_variable: shared})
    method, path, body = CREATE

    for token in (OLD_MCP_TOKEN, NEW_MCP_TOKEN):
        response = world.call(method, path, body, token=token)
        assert response.status_code == 503
        assert _code(response) == "SERVICE_AUTH_NOT_CONFIGURED"


def test_distinct_agent_tokens_do_not_affect_backend_auth(world, rotation):
    rotation(next_value=NEXT, MCP_SERVER_TOKEN=AGENT_TOKEN, MCP_SERVER_TOKEN_NEXT=NEW_AGENT_TOKEN)
    method, path, body = CREATE

    assert world.call(method, path, body, token=NEW_MCP_TOKEN).status_code == 418
    # The Agent -> MCP token is not a backend credential.
    assert world.call(method, path, body, token=AGENT_TOKEN).status_code == 401


def test_the_rotation_check_logs_the_service_never_a_token(world, rotation, caplog):
    caplog.set_level(logging.DEBUG)
    rotation(next_value=NEXT)
    method, path, body = CREATE

    world.call(method, path, body, token=OLD_MCP_TOKEN)
    assert "service_auth_next_token_used" not in caplog.text
    world.call(method, path, body, token=NEW_MCP_TOKEN)
    world.call(method, path, body, token=WRONG_TOKEN)
    rotation(next_value=f"mcp_server={VOICE_TOKEN}@clinic-001")  # config error path
    world.call(method, path, body, token=NEW_MCP_TOKEN)

    assert "service_auth_next_token_used service=mcp_server" in caplog.text
    assert "medmind_service_credentials_invalid" in caplog.text
    for secret in (OLD_MCP_TOKEN, NEW_MCP_TOKEN, WRONG_TOKEN, VOICE_TOKEN, NATIONAL_ID):
        assert secret not in caplog.text


def test_settings_read_the_rotation_variables(monkeypatch):
    monkeypatch.setenv("MEDMIND_SERVICE_CREDENTIALS_NEXT", NEXT)
    monkeypatch.setenv("MCP_SERVER_TOKEN", AGENT_TOKEN)

    settings = Settings(_env_file=None)

    assert settings.medmind_service_credentials_next.get_secret_value() == NEXT
    assert settings.mcp_server_token.get_secret_value() == AGENT_TOKEN


# ============================================================ Agent -> MCP


def _mcp(**values):
    values.setdefault("backend_service_token", BACKEND_TOKEN)
    return MCPSettings(_env_file=None, **values)


@pytest.mark.parametrize("mode", ["audit", "enforce"])
def test_mcp_accepts_both_tokens_during_the_overlap(mode):
    settings = _mcp(server_token=AGENT_TOKEN, server_token_next=NEW_AGENT_TOKEN, auth_mode=mode)

    for token in (AGENT_TOKEN, NEW_AGENT_TOKEN):
        assert authorize_mcp_request(_headers(token), settings=settings) is None


@pytest.mark.parametrize("mode", ["audit", "enforce"])
def test_mcp_rejects_unrelated_tokens_during_the_overlap(mode):
    settings = _mcp(server_token=AGENT_TOKEN, server_token_next=NEW_AGENT_TOKEN, auth_mode=mode)

    for token in (WRONG_TOKEN, BACKEND_TOKEN, NEW_AGENT_TOKEN[:-1], ""):
        with pytest.raises(MCPUnauthorizedError):
            authorize_mcp_request(_headers(token), settings=settings)


@pytest.mark.parametrize("mode", ["audit", "enforce"])
def test_mcp_rejects_the_removed_old_token_after_promotion(mode):
    settings = _mcp(server_token=NEW_AGENT_TOKEN, auth_mode=mode)

    with pytest.raises(MCPUnauthorizedError):
        authorize_mcp_request(_headers(AGENT_TOKEN), settings=settings)
    assert authorize_mcp_request(_headers(NEW_AGENT_TOKEN), settings=settings) is None


def test_mcp_does_not_accept_the_next_token_before_it_is_configured():
    settings = _mcp(server_token=AGENT_TOKEN, auth_mode="audit")

    with pytest.raises(MCPUnauthorizedError):
        authorize_mcp_request(_headers(NEW_AGENT_TOKEN), settings=settings)


def test_mcp_current_equal_to_next_is_one_token():
    settings = _mcp(server_token=AGENT_TOKEN, server_token_next=AGENT_TOKEN, auth_mode="enforce")

    assert authorize_mcp_request(_headers(AGENT_TOKEN), settings=settings) is None


def test_an_empty_mcp_next_value_means_no_rotation():
    settings = _mcp(server_token=AGENT_TOKEN, server_token_next="  ", auth_mode="enforce")

    assert authorize_mcp_request(_headers(AGENT_TOKEN), settings=settings) is None


@pytest.mark.parametrize("mode", ["audit", "enforce"])
@pytest.mark.parametrize(
    "values",
    [
        {"server_token": AGENT_TOKEN, "server_token_next": "too-short"},
        {"server_token": BACKEND_TOKEN},                                   # same as MCP -> Backend
        {"server_token": AGENT_TOKEN, "server_token_next": BACKEND_TOKEN},  # same as MCP -> Backend
    ],
)
def test_mcp_misconfiguration_fails_closed(mode, values):
    settings = _mcp(auth_mode=mode, **values)

    for token in (AGENT_TOKEN, BACKEND_TOKEN, values.get("server_token_next") or NEW_AGENT_TOKEN):
        with pytest.raises(MCPUnauthorizedError):
            authorize_mcp_request(_headers(token), settings=settings)

    if mode == "enforce":
        with pytest.raises(MCPUnauthorizedError):
            authorize_mcp_request(_headers(), settings=settings)


def test_mcp_rotation_logs_never_contain_tokens(caplog):
    caplog.set_level(logging.DEBUG)
    overlap = _mcp(server_token=AGENT_TOKEN, server_token_next=NEW_AGENT_TOKEN, auth_mode="enforce")
    clash = _mcp(server_token=AGENT_TOKEN, server_token_next=BACKEND_TOKEN, auth_mode="enforce")

    authorize_mcp_request(_headers(AGENT_TOKEN), client_host="127.0.0.1", settings=overlap)
    assert "mcp_service_auth_next_token_used" not in caplog.text
    authorize_mcp_request(_headers(NEW_AGENT_TOKEN), client_host="127.0.0.1", settings=overlap)
    for settings, token in ((overlap, WRONG_TOKEN), (clash, AGENT_TOKEN)):
        with pytest.raises(MCPUnauthorizedError):
            authorize_mcp_request(_headers(token), client_host="127.0.0.1", settings=settings)

    assert "mcp_service_auth_next_token_used client=127.0.0.1" in caplog.text
    assert "reason=same_as_backend_service_token" in caplog.text
    for secret in (AGENT_TOKEN, NEW_AGENT_TOKEN, BACKEND_TOKEN, WRONG_TOKEN):
        assert secret not in caplog.text
