"""Agent -> MCP and MCP -> Backend credentials (mcp_server/auth.py,
mcp_server/backend_client.py, agent/medmind/service.py).

All tokens are test-only values. No MCP server is started and no network
call leaves the process.
"""

import inspect
import logging
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from starlette.datastructures import Headers

import mcp_server.auth as mcp_auth
import mcp_server.backend_client as backend_client_module
from mcp_server import server
from mcp_server.auth import MCPUnauthorizedError, authorize_mcp_request
from mcp_server.backend_client import BackendClient
from mcp_server.config import MCPSettings

SERVER_TOKEN = "mcp-inbound-test-token-0123456789abcdef01"
BACKEND_TOKEN = "mcp-backend-test-token-0123456789abcdef01"
WRONG_TOKEN = "wrong-token-0123456789abcdef0123456789"
TENANT = "clinic-001"
NATIONAL_ID = "29001011234567"


def _settings(**values):
    return MCPSettings(_env_file=None, **values)


def _headers(token=None, tenant=TENANT):
    raw = {"X-Tenant-ID": tenant}
    if token is not None:
        raw["X-MedMind-Service-Token"] = token
    return Headers(raw)


# ============================================================ inbound check


@pytest.mark.parametrize("mode", ["audit", "enforce"])
def test_the_configured_token_is_accepted_in_both_modes(mode):
    settings = _settings(server_token=SERVER_TOKEN, auth_mode=mode)

    assert authorize_mcp_request(_headers(SERVER_TOKEN), settings=settings) is None


@pytest.mark.parametrize("mode", ["audit", "enforce"])
@pytest.mark.parametrize("token", [WRONG_TOKEN, "", SERVER_TOKEN[:-1], SERVER_TOKEN + "x"])
def test_a_present_but_wrong_token_is_rejected_in_both_modes(mode, token):
    settings = _settings(server_token=SERVER_TOKEN, auth_mode=mode)

    with pytest.raises(MCPUnauthorizedError) as error:
        authorize_mcp_request(_headers(token), settings=settings)

    assert str(error.value) == "Unauthorized MCP request."


def test_audit_mode_serves_a_missing_token_and_logs_the_caller(caplog):
    caplog.set_level(logging.DEBUG)
    settings = _settings(server_token=SERVER_TOKEN, auth_mode="audit")

    authorize_mcp_request(_headers(), client_host="127.0.0.1", settings=settings)

    (message,) = [r.getMessage() for r in caplog.records if "mcp_service_auth_missing" in r.getMessage()]
    assert "mode=audit" in message and "client=127.0.0.1" in message


def test_enforce_mode_rejects_a_missing_token():
    settings = _settings(server_token=SERVER_TOKEN, auth_mode="enforce")

    with pytest.raises(MCPUnauthorizedError):
        authorize_mcp_request(_headers(), settings=settings)


@pytest.mark.parametrize("configured", [None, "", "too-short-token"])
def test_enforce_mode_without_a_usable_server_token_fails_closed(configured):
    settings = _settings(server_token=configured, auth_mode="enforce")

    for token in (None, SERVER_TOKEN, configured or ""):
        with pytest.raises(MCPUnauthorizedError):
            authorize_mcp_request(_headers(token), settings=settings)


def test_audit_mode_without_a_server_token_still_rejects_a_presented_token():
    settings = _settings(auth_mode="audit")

    with pytest.raises(MCPUnauthorizedError):
        authorize_mcp_request(_headers(SERVER_TOKEN), settings=settings)


def test_the_comparison_is_timing_safe(monkeypatch):
    calls = []
    real = mcp_auth.hmac.compare_digest

    def counting(a, b):
        calls.append(1)
        return real(a, b)

    monkeypatch.setattr(mcp_auth.hmac, "compare_digest", counting)
    settings = _settings(server_token=SERVER_TOKEN, auth_mode="enforce")

    authorize_mcp_request(_headers(SERVER_TOKEN), settings=settings)
    with pytest.raises(MCPUnauthorizedError):
        authorize_mcp_request(_headers(WRONG_TOKEN), settings=settings)

    assert len(calls) == 2


def test_tokens_never_appear_in_mcp_logs(caplog):
    caplog.set_level(logging.DEBUG)

    for mode in ("audit", "enforce"):
        for configured in (SERVER_TOKEN, None, "tiny-secret-value"):
            settings = _settings(server_token=configured, auth_mode=mode)
            for token in (SERVER_TOKEN, WRONG_TOKEN, None):
                try:
                    authorize_mcp_request(_headers(token), client_host="127.0.0.1", settings=settings)
                except MCPUnauthorizedError:
                    pass

    assert caplog.records
    for secret in (SERVER_TOKEN, WRONG_TOKEN, "tiny-secret-value"):
        assert secret not in caplog.text


def test_an_unknown_mcp_auth_mode_fails_settings_loading():
    with pytest.raises(ValidationError):
        _settings(auth_mode="off")

    assert _settings(auth_mode=" ENFORCE ").auth_mode == "enforce"
    assert _settings().auth_mode == "audit"


# ============================================================ every MCP tool


SAMPLE_ARGS = {
    "national_id": NATIONAL_ID,
    "patient_name": "Test Patient",
    "phone": "+201000000000",
    "channel": "voice",
    "preferred_language": "ar",
    "language": "ar",
    "appointment_reference": "APT-260828-ABC123",
    "idempotency_key": "test-idempotency-key-0001",
    "slot_date": date(2026, 11, 1),
}


def _tool_args(fn):
    args = {}
    for name, parameter in inspect.signature(fn).parameters.items():
        if name == "context":
            continue
        if name in SAMPLE_ARGS:
            args[name] = SAMPLE_ARGS[name]
        elif name.endswith("_id"):
            args[name] = uuid4()
        elif parameter.default is not inspect.Parameter.empty:
            args[name] = parameter.default
        else:
            args[name] = None
    return args


def _context(headers):
    request = SimpleNamespace(headers=headers, client=SimpleNamespace(host="127.0.0.1"))
    return SimpleNamespace(request_context=SimpleNamespace(request=request))


@pytest.fixture
def tools(monkeypatch):
    """Every registered MCP tool, with its backend call replaced by a recorder."""
    impls = {}
    for name in dir(server):
        if name.endswith("_impl"):
            impls[name] = AsyncMock(return_value={"ok": True})
            monkeypatch.setattr(server, name, impls[name])

    def use(settings):
        monkeypatch.setattr(mcp_auth, "get_mcp_settings", lambda: settings)

    registered = server.mcp._tool_manager.list_tools()
    return SimpleNamespace(registered=registered, impls=impls, use=use)


def test_all_fourteen_mcp_tools_are_covered(tools):
    assert len(tools.registered) == 14


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["audit", "enforce"])
async def test_every_mcp_tool_rejects_a_wrong_token_before_any_backend_call(tools, mode):
    tools.use(_settings(server_token=SERVER_TOKEN, auth_mode=mode))

    for tool in tools.registered:
        with pytest.raises(MCPUnauthorizedError):
            await tool.fn(context=_context(_headers(WRONG_TOKEN)), **_tool_args(tool.fn))

    assert all(not impl.called for impl in tools.impls.values())


@pytest.mark.asyncio
async def test_every_mcp_tool_rejects_a_missing_token_in_enforce_mode(tools):
    tools.use(_settings(server_token=SERVER_TOKEN, auth_mode="enforce"))

    for tool in tools.registered:
        with pytest.raises(MCPUnauthorizedError):
            await tool.fn(context=_context(_headers()), **_tool_args(tool.fn))

    assert all(not impl.called for impl in tools.impls.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("token, mode", [(SERVER_TOKEN, "enforce"), (SERVER_TOKEN, "audit"), (None, "audit")])
async def test_every_mcp_tool_serves_an_accepted_call_for_its_own_tenant(tools, token, mode):
    tools.use(_settings(server_token=SERVER_TOKEN, auth_mode=mode))

    for tool in tools.registered:
        await tool.fn(context=_context(_headers(token)), **_tool_args(tool.fn))

    called = [impl for impl in tools.impls.values() if impl.called]
    assert len(called) == 14
    assert all(impl.call_args.kwargs["tenant_id"] == TENANT for impl in called)


@pytest.mark.asyncio
async def test_tenant_validation_still_applies_after_authentication(tools):
    tools.use(_settings(server_token=SERVER_TOKEN, auth_mode="enforce"))
    tool = tools.registered[0]

    with pytest.raises(RuntimeError, match="Invalid X-Tenant-ID"):
        await tool.fn(context=_context(_headers(SERVER_TOKEN, tenant="bad tenant!")))


def test_dns_rebinding_protection_is_unchanged():
    security = server.mcp.settings.transport_security
    assert security.enable_dns_rebinding_protection is True
    assert "127.0.0.1:*" in security.allowed_hosts


# ============================================================ MCP -> Backend


def _backend_client(monkeypatch, **values):
    settings = _settings(backend_base_url="http://backend.test", **values)
    monkeypatch.setattr(backend_client_module, "get_mcp_settings", lambda: settings)
    return BackendClient()


@pytest.mark.asyncio
async def test_backend_requests_carry_the_backend_credential_not_the_inbound_one(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    client = _backend_client(monkeypatch, backend_service_token=BACKEND_TOKEN, server_token=SERVER_TOKEN)
    seen = []

    def handler(request):
        seen.append(request.headers)
        return httpx.Response(200, json={"ok": True})

    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        await client.request(
            tenant_id=TENANT, method="POST", path="/api/v1/patients/lookup",
            json={"national_id": NATIONAL_ID}, idempotency_key="test-idempotency-key-0001",
        )
    finally:
        await client.close()

    (headers,) = seen
    assert headers["X-MedMind-Service-Token"] == BACKEND_TOKEN
    assert headers["X-Tenant-ID"] == TENANT
    assert headers["Idempotency-Key"] == "test-idempotency-key-0001"
    for secret in (BACKEND_TOKEN, SERVER_TOKEN, NATIONAL_ID):
        assert secret not in caplog.text


@pytest.mark.parametrize("configured", [None, "", "   "])
def test_without_a_backend_credential_no_token_header_is_sent(monkeypatch, configured):
    client = _backend_client(monkeypatch, backend_service_token=configured)

    headers = client._build_headers(tenant_id=TENANT)

    assert "X-MedMind-Service-Token" not in headers
    assert headers["X-Tenant-ID"] == TENANT


# ============================================================ Agent -> MCP


def test_the_agent_sends_the_inbound_mcp_credential(monkeypatch):
    from medmind.service import _mcp_request_headers

    monkeypatch.setenv("MCP_SERVER_TOKEN", SERVER_TOKEN)
    monkeypatch.setenv("MCP_AUTH_MODE", "enforce")

    assert _mcp_request_headers(TENANT) == {
        "X-Tenant-ID": TENANT,
        "X-MedMind-Service-Token": SERVER_TOKEN,
    }


def test_the_agent_sends_only_the_tenant_without_a_token_in_audit_mode(monkeypatch):
    from medmind.service import _mcp_request_headers

    monkeypatch.delenv("MCP_SERVER_TOKEN", raising=False)
    monkeypatch.setenv("MCP_AUTH_MODE", "audit")

    assert _mcp_request_headers(TENANT) == {"X-Tenant-ID": TENANT}


@pytest.mark.parametrize("missing", [None, "", "  "])
def test_the_agent_fails_fast_without_a_token_in_enforce_mode(monkeypatch, missing):
    from medmind.service import _mcp_request_headers

    if missing is None:
        monkeypatch.delenv("MCP_SERVER_TOKEN", raising=False)
    else:
        monkeypatch.setenv("MCP_SERVER_TOKEN", missing)
    monkeypatch.setenv("MCP_AUTH_MODE", "Enforce")

    with pytest.raises(RuntimeError, match="MCP_SERVER_TOKEN"):
        _mcp_request_headers(TENANT)


def test_the_agent_mcp_client_uses_the_header_builder():
    from medmind.service import MedMindService

    source = inspect.getsource(MedMindService.create)
    assert "_mcp_request_headers(" in source
    assert '"X-Tenant-ID"' not in source  # no second, token-less header dict
