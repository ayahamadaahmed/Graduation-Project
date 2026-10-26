"""Agent -> MCP authentication through the real Streamable HTTP app.

The MCP ASGI app runs in-process behind httpx.ASGITransport: no socket, no
backend, no database, no AI provider. The backend call behind each tool and
the MCP lifespan's backend client are replaced by recorders. All tokens are
test-only values.
"""

from unittest.mock import AsyncMock

import httpx
import pytest

import mcp_server.auth as mcp_auth
from mcp_server import server
from mcp_server.auth_negative_check import probe_tool_call
from mcp_server.config import MCPSettings

SERVER_TOKEN = "mcp-inbound-test-token-0123456789abcdef01"
WRONG_TOKEN = "wrong-token-0123456789abcdef0123456789"
TENANT = "clinic-001"
URL = "http://127.0.0.1:9000/mcp"  # the Host the MCP server accepts


@pytest.fixture
def mcp_http(monkeypatch):
    """A fresh in-process MCP HTTP app; returns (run, provider_info_backend_call)."""
    for name in ("start", "warmup", "close"):
        monkeypatch.setattr(server.backend_client, name, AsyncMock())
    backend_call = AsyncMock(return_value={"tenant_key": TENANT})
    monkeypatch.setattr(server, "get_provider_info_impl", backend_call)

    def use(mode):
        settings = MCPSettings(_env_file=None, server_token=SERVER_TOKEN, auth_mode=mode)
        monkeypatch.setattr(mcp_auth, "get_mcp_settings", lambda: settings)
        monkeypatch.setattr(server, "get_mcp_settings", lambda: settings)

    async def probe(mode, token=None):
        use(mode)
        # The session manager can run once per instance; build a new one per probe.
        monkeypatch.setattr(server.mcp, "_session_manager", None)
        app = server.mcp.streamable_http_app()
        async with server.mcp.session_manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
                return await probe_tool_call(client, url=URL, tenant_id=TENANT, token=token)

    return probe, backend_call


@pytest.mark.asyncio
async def test_enforce_mode_refuses_a_tool_call_without_a_token_over_http(mcp_http):
    probe, backend_call = mcp_http

    assert await probe("enforce") is True
    backend_call.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["audit", "enforce"])
async def test_a_wrong_token_is_refused_over_http_in_every_mode(mcp_http, mode):
    probe, backend_call = mcp_http

    assert await probe(mode, token=WRONG_TOKEN) is True
    backend_call.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["audit", "enforce"])
async def test_the_configured_token_is_served_over_http(mcp_http, mode):
    probe, backend_call = mcp_http

    assert await probe(mode, token=SERVER_TOKEN) is False
    backend_call.assert_awaited_once_with(tenant_id=TENANT)


@pytest.mark.asyncio
async def test_audit_mode_still_serves_a_missing_token_over_http(mcp_http):
    # Documents the transitional gap: audit mode does not protect this call.
    probe, backend_call = mcp_http

    assert await probe("audit") is False
    backend_call.assert_awaited_once_with(tenant_id=TENANT)


@pytest.mark.asyncio
async def test_the_check_never_prints_or_logs_a_token(mcp_http, caplog, capsys):
    probe, _ = mcp_http

    await probe("enforce", token=WRONG_TOKEN)
    await probe("enforce", token=SERVER_TOKEN)

    output = capsys.readouterr()
    for secret in (SERVER_TOKEN, WRONG_TOKEN):
        assert secret not in caplog.text
        assert secret not in output.out + output.err


def test_the_live_check_does_not_load_dotenv():
    import inspect

    import mcp_server.auth_negative_check as check

    source = inspect.getsource(check)
    # It must send exactly what the caller environment has, so .env cannot
    # re-add the token it is checking without.
    assert "from dotenv" not in source and "import dotenv" not in source
