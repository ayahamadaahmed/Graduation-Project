"""Offline tests for mcp_server/patient_lookup_check.py.

The real MCP Streamable HTTP app runs in-process (httpx.ASGITransport, no
socket); the backend call behind each MCP tool is a recorder. No database,
network or AI. All tokens and personal values are fake.
"""

import json
import os
from unittest.mock import AsyncMock

import httpx
import pytest

import mcp_server.auth as mcp_auth
import mcp_server.patient_lookup_check as check
from mcp_server import server
from mcp_server.config import MCPSettings

TOKEN = "test-only-mcp-inbound-token-0123456789ab"
URL = "http://127.0.0.1:9000/mcp"
TENANT = "clinic-001"
ENV = {"MCP_URL": URL, "MCP_SERVER_TOKEN": TOKEN, "TENANT_ID": TENANT}

# Fake personal data that must never be printed.
FAKE_PATIENT = {
    "patient_id": "0b6f7f1e-1111-4222-8333-944445555666",
    "patient_code": "P-FAKE-0001",
    "display_name": "Fake Patient Name",
    "masked_national_id": "**********9999",
    "phone": "+20100000999",
    "existing_patient": True,
}


class RecordingTransport(httpx.AsyncBaseTransport):
    """Records every request body, then hands it to the in-process MCP app."""

    def __init__(self, app):
        self.inner = httpx.ASGITransport(app=app)
        self.bodies = []

    async def handle_async_request(self, request):
        content = request.content
        self.bodies.append(json.loads(content) if content else None)
        return await self.inner.handle_async_request(request)


class ForbiddenTransport(httpx.AsyncBaseTransport):
    """Fails the test if any request is attempted."""

    async def handle_async_request(self, request):
        raise AssertionError("no request may be sent")


@pytest.fixture
def mcp(monkeypatch):
    for name in ("start", "warmup", "close"):
        monkeypatch.setattr(server.backend_client, name, AsyncMock())
    impls = {}
    for name in dir(server):
        if name.endswith("_impl"):
            impls[name] = AsyncMock(return_value={"found": False, "patient": None})
            monkeypatch.setattr(server, name, impls[name])
    settings = MCPSettings(_env_file=None, server_token=TOKEN, auth_mode="enforce")
    monkeypatch.setattr(mcp_auth, "get_mcp_settings", lambda: settings)
    monkeypatch.setattr(server, "get_mcp_settings", lambda: settings)

    async def run(env=ENV, lookup_result=None, lookup_error=None):
        if lookup_error is not None:
            impls["lookup_patient_impl"].side_effect = lookup_error
        elif lookup_result is not None:
            impls["lookup_patient_impl"].return_value = lookup_result
        monkeypatch.setattr(server.mcp, "_session_manager", None)
        app = server.mcp.streamable_http_app()
        transport = RecordingTransport(app)
        async with server.mcp.session_manager.run():
            async with httpx.AsyncClient(transport=transport) as client:
                code, line = await check.run(env, client=client)
        return code, line, transport.bodies

    return run, impls


def _tool_calls(bodies):
    return [b["params"] for b in bodies if isinstance(b, dict) and b.get("method") == "tools/call"]


def _assert_nothing_sensitive(line):
    for secret in (check.NOT_FOUND_NATIONAL_ID, TOKEN, URL, "127.0.0.1", TENANT, *map(str, FAKE_PATIENT.values())):
        if secret not in ("True",):
            assert secret not in line, secret


# ============================================================ refusal before any call


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["", "29001011234567"])
async def test_refuses_when_the_existing_id_variable_exists_even_empty(value):
    env = {**ENV, check.FORBIDDEN_ENV: value}

    async with httpx.AsyncClient(transport=ForbiddenTransport()) as client:
        code, line = await check.run(env, client=client)

    assert code == 2
    assert line == f"REFUSED: {check.FORBIDDEN_ENV} is set; unset it to run this check"
    assert "29001011234567" not in line


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["MCP_URL", "MCP_SERVER_TOKEN", "TENANT_ID"])
async def test_refuses_without_explicit_settings(missing):
    env = {k: v for k, v in ENV.items() if k != missing}

    async with httpx.AsyncClient(transport=ForbiddenTransport()) as client:
        code, line = await check.run(env, client=client)

    assert code == 2 and line.startswith("REFUSED: ")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.5:9000/mcp",
        "http://example.com/mcp",
        "https://staging.example.org:9000/mcp",
        "http://127.0.0.1.evil.example/mcp",
        "http://fakeuser:fake-pass@127.0.0.1:9000/mcp",
        "ftp://127.0.0.1:9000/mcp",
        "http://127.0.0.1:notaport/mcp",
        "not a url",
    ],
)
async def test_refuses_non_loopback_or_malformed_urls_without_a_request(url):
    async with httpx.AsyncClient(transport=ForbiddenTransport()) as client:
        code, line = await check.run({**ENV, "MCP_URL": url}, client=client)

    assert code == 2 and line.startswith("REFUSED: ")
    assert url not in line and "fake-pass" not in line


@pytest.mark.parametrize("url", ["http://127.0.0.1:9000/mcp", "http://localhost:9000/mcp", "http://[::1]:9000/mcp"])
def test_loopback_urls_are_accepted(url):
    assert check.load_config({**ENV, "MCP_URL": url}).url == url


def test_refuses_an_invalid_tenant():
    with pytest.raises(check.CheckRefused):
        check.load_config({**ENV, "TENANT_ID": "bad tenant!"})


def test_dotenv_is_never_read(tmp_path, monkeypatch):
    # A .env in the working directory must not influence the check.
    (tmp_path / ".env").write_text(f"{check.FORBIDDEN_ENV}=29001011234567\nMCP_URL=http://10.0.0.5/mcp\n")
    monkeypatch.chdir(tmp_path)

    assert check.load_config(ENV).url == URL  # neither .env value was applied
    source = open(check.__file__, encoding="utf-8").read()
    assert "dotenv" not in source.split('"""', 2)[2]  # no dotenv import or call in code


# ============================================================ the lookup itself


@pytest.mark.asyncio
async def test_not_found_prints_only_found_false(mcp):
    run, impls = mcp

    code, line, bodies = await run()

    assert (code, line) == (0, "found: false")
    impls["lookup_patient_impl"].assert_awaited_once_with(
        tenant_id=TENANT, national_id=check.NOT_FOUND_NATIONAL_ID, language="ar"
    )
    assert [c["name"] for c in _tool_calls(bodies)] == ["lookup_patient"]
    _assert_nothing_sensitive(line)


@pytest.mark.asyncio
async def test_only_the_read_only_lookup_tool_is_ever_called(mcp):
    run, impls = mcp

    _, _, bodies = await run()

    (call,) = _tool_calls(bodies)
    assert call == {"name": "lookup_patient",
                    "arguments": {"national_id": check.NOT_FOUND_NATIONAL_ID, "language": "ar"}}
    called = [name for name, impl in impls.items() if impl.called]
    assert called == ["lookup_patient_impl"]  # no create/cancel/reschedule/resolve/profile


@pytest.mark.asyncio
async def test_a_found_patient_prints_only_found_true(mcp, capsys):
    run, _ = mcp

    code, line, _ = await run(lookup_result={"found": True, "patient": FAKE_PATIENT})

    assert (code, line) == (1, "found: true")  # unexpected for the built-in ID
    _assert_nothing_sensitive(line)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [{"found": "yes"}, {"found": False, "extra": "x"}, {"patient": None}, ["found", False], "found: false"],
)
async def test_unexpected_shapes_fail_closed_without_echoing(mcp, payload):
    run, _ = mcp

    code, line, _ = await run(lookup_result=payload)

    assert (code, line) == (1, "FAILED: unexpected tool response shape")


@pytest.mark.asyncio
async def test_a_tool_error_fails_without_echoing_its_detail(mcp):
    run, _ = mcp

    code, line, _ = await run(lookup_error=RuntimeError("detail with Fake Patient Name"))

    assert (code, line) == (1, "FAILED: the lookup tool returned an error")


@pytest.mark.asyncio
async def test_a_wrong_token_fails_closed(mcp):
    run, impls = mcp

    code, line, _ = await run(env={**ENV, "MCP_SERVER_TOKEN": "test-only-wrong-token-0123456789abcdef"})

    assert (code, line) == (1, "FAILED: the lookup tool returned an error")
    assert not impls["lookup_patient_impl"].called


@pytest.mark.asyncio
async def test_an_unreachable_server_fails_without_details():
    class Down(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise httpx.ConnectError("connection refused to 127.0.0.1:9000")

    async with httpx.AsyncClient(transport=Down()) as client:
        code, line = await check.run(ENV, client=client)

    assert (code, line) == (1, "FAILED: could not open an MCP session")


def test_main_refuses_from_the_process_environment(monkeypatch, capsys):
    monkeypatch.setenv(check.FORBIDDEN_ENV, "")
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)

    assert check.main() == 2
    out = capsys.readouterr().out
    assert out.strip() == f"REFUSED: {check.FORBIDDEN_ENV} is set; unset it to run this check"
    assert TOKEN not in out and os.environ["MCP_URL"] not in out
