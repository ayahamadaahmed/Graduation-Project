"""MCP -> Backend service token, end to end and in-process.

The real MCP tool (mcp_server/tools/appointments.py) and the real
BackendClient (mcp_server/backend_client.py) call the real booking guard
(app/security/booking_auth.py) on POST /api/v1/appointments/search-by-national-id
through httpx.ASGITransport. Only the tenant lookup and the appointment
service are fakes. No socket, no database, no .env: both sides read the same
environment variables as production, with the .env file switched off.

All tokens are test-only values, distinct per hop. The national ID is a
synthetic 14-digit value that the fake service never stores or logs.
"""

import logging
import socket
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Header

import mcp_server.backend_client as backend_client_module
import mcp_server.tools.appointments as appointment_tools
from app.api import dependencies as deps
from app.api.routers import appointments
from app.core.config import Settings
from app.schemas.appointment import AppointmentsByNationalIdResponse
from app.security import booking_auth
from app.security.service_auth import SERVICE_TOKEN_HEADER
from mcp_server.backend_client import BackendClient
from mcp_server.config import MCPSettings

MCP_BACKEND_TOKEN = "test-only-mcp-to-backend-token-0123456789abcd"
VOICE_TOKEN = "test-only-voice-to-backend-token-0123456789ab"
AGENT_TOKEN = "test-only-agent-to-mcp-token-0123456789abcdef"
WRONG_TOKEN = "test-only-wrong-token-0123456789abcdef012345"
CREDENTIALS = f"mcp_server={MCP_BACKEND_TOKEN}@clinic-001;voice_gateway={VOICE_TOKEN}@clinic-001"
TEST_JWT_SECRET = "test-only-signing-key-not-production-0123456789abcdef"
SYNTHETIC_NATIONAL_ID = "00000000000000"  # 14 digits, not a valid national ID
BACKEND_URL = "http://backend.test"
ROUTE = "/appointments/search-by-national-id"

PROVIDERS = {
    "clinic-001": SimpleNamespace(id=uuid4(), tenant_key="clinic-001", timezone="Africa/Cairo"),
    "clinic-002": SimpleNamespace(id=uuid4(), tenant_key="clinic-002", timezone="Africa/Cairo"),
}
EMPTY_RESULT = {"patient_code": "TEST-ONLY", "patient_name": "Synthetic Patient", "count": 0, "appointments": []}


def _offline(*args, **kwargs):
    raise AssertionError("network access attempted")


@pytest.fixture
def chain(monkeypatch):
    # Fail loudly on any name resolution or outbound connection.
    monkeypatch.setattr(socket, "getaddrinfo", _offline)
    monkeypatch.setattr(socket, "create_connection", _offline)

    for name in ("MCP_BACKEND_SERVICE_TOKEN", "MEDMIND_SERVICE_CREDENTIALS_NEXT", "MCP_SERVER_TOKEN_NEXT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MEDMIND_SERVICE_CREDENTIALS", CREDENTIALS)
    monkeypatch.setenv("MCP_SERVER_TOKEN", AGENT_TOKEN)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    monkeypatch.setenv("MCP_BACKEND_BASE_URL", BACKEND_URL)

    # The production settings classes and variables, without any .env file.
    monkeypatch.setattr(booking_auth, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(backend_client_module, "get_mcp_settings", lambda: MCPSettings(_env_file=None))

    lookups, calls, header_sent, client_options = [], [], [], []

    def recording_provider(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
        lookups.append(x_tenant_id)  # stands in for the tenant database lookup
        return PROVIDERS[x_tenant_id]

    class FakeAppointments:
        def search_bookings_by_national_id(self, *, provider_id, provider_timezone, data):
            calls.append(provider_id)  # never the national ID
            return AppointmentsByNationalIdResponse(**EMPTY_RESULT)

    app = FastAPI()
    app.include_router(appointments.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_current_provider] = recording_provider
    app.dependency_overrides[deps.get_appointment_service] = FakeAppointments

    @app.middleware("http")
    async def record_header(request, call_next):
        header_sent.append(SERVICE_TOKEN_HEADER.lower() in request.headers)  # presence only
        return await call_next(request)

    # BackendClient.start() builds its own AsyncClient; keep its options and
    # route it to the app in-process instead of a socket.
    real_async_client = httpx.AsyncClient

    def in_process_client(**kwargs):
        client_options.append(kwargs)
        return real_async_client(transport=httpx.ASGITransport(app=app), **kwargs)

    monkeypatch.setattr(backend_client_module.httpx, "AsyncClient", in_process_client)

    def configure(mcp_backend_token, auth_mode):
        if mcp_backend_token is None:
            monkeypatch.delenv("MCP_BACKEND_SERVICE_TOKEN", raising=False)
        else:
            monkeypatch.setenv("MCP_BACKEND_SERVICE_TOKEN", mcp_backend_token)
        monkeypatch.setenv("BOOKING_SERVICE_AUTH_MODE", auth_mode)

    async def search(tenant="clinic-001"):
        client = BackendClient()  # reads MCP_BACKEND_SERVICE_TOKEN like production
        monkeypatch.setattr(appointment_tools, "backend_client", client)
        await client.start()
        try:
            return await appointment_tools.search_patient_bookings(
                tenant_id=tenant, national_id=SYNTHETIC_NATIONAL_ID,
            )
        finally:
            await client.close()

    return SimpleNamespace(
        configure=configure, search=search, lookups=lookups, calls=calls,
        header_sent=header_sent, client_options=client_options,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_mode", ["audit", "enforce"])
async def test_the_mcp_backend_token_reaches_the_guarded_route(chain, auth_mode):
    chain.configure(MCP_BACKEND_TOKEN, auth_mode)

    assert await chain.search() == EMPTY_RESULT
    assert chain.header_sent == [True]
    assert chain.lookups == ["clinic-001"]
    assert chain.calls == [PROVIDERS["clinic-001"].id]
    assert chain.client_options[0]["trust_env"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_mode", ["audit", "enforce"])
async def test_a_wrong_backend_token_is_rejected_before_the_tenant_lookup(chain, auth_mode):
    chain.configure(WRONG_TOKEN, auth_mode)

    with pytest.raises(RuntimeError, match=r"^SERVICE_AUTH_INVALID: .* \(HTTP 401\)$"):
        await chain.search()

    assert chain.header_sent == [True]
    assert chain.lookups == [] and chain.calls == []


# The real client strips the configured token and sends no header when it is
# blank, so an empty header cannot leave it: blank behaves as "not configured".
@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [None, "", "   "])
async def test_without_a_backend_token_enforce_mode_rejects_before_the_tenant_lookup(chain, configured):
    chain.configure(configured, "enforce")

    with pytest.raises(RuntimeError, match=r"^SERVICE_AUTH_REQUIRED: .* \(HTTP 401\)$"):
        await chain.search()

    assert chain.header_sent == [False]
    assert chain.lookups == [] and chain.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [None, "", "   "])
async def test_without_a_backend_token_audit_mode_serves_and_logs_the_route(chain, caplog, configured):
    caplog.set_level(logging.DEBUG)
    chain.configure(configured, "audit")

    assert await chain.search() == EMPTY_RESULT
    assert chain.header_sent == [False]
    assert chain.lookups == ["clinic-001"]
    assert len(chain.calls) == 1
    warnings = [r.getMessage() for r in caplog.records if "booking_service_auth_missing" in r.getMessage()]
    assert warnings == [f"booking_service_auth_missing mode=audit method=POST route={ROUTE}"]


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_mode", ["audit", "enforce"])
async def test_a_tenant_outside_the_mcp_allow_list_is_rejected(chain, auth_mode):
    chain.configure(MCP_BACKEND_TOKEN, auth_mode)

    with pytest.raises(RuntimeError, match=r"^SERVICE_TENANT_NOT_ALLOWED: .* \(HTTP 403\)$"):
        await chain.search(tenant="clinic-002")

    assert chain.lookups == ["clinic-002"]  # token first, then the tenant, then the allow-list
    assert chain.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_mode", ["audit", "enforce"])
@pytest.mark.parametrize(
    "other_hop_token, status_code, code",
    [
        (VOICE_TOKEN, 403, "SERVICE_NOT_ALLOWED"),   # valid backend credential of the voice gateway
        (AGENT_TOKEN, 401, "SERVICE_AUTH_INVALID"),  # the Agent -> MCP credential
    ],
    ids=["voice_gateway_token", "agent_to_mcp_token"],
)
async def test_another_hops_valid_token_does_not_authenticate_as_mcp(chain, auth_mode, other_hop_token, status_code, code):
    chain.configure(other_hop_token, auth_mode)

    with pytest.raises(RuntimeError, match=rf"^{code}: .* \(HTTP {status_code}\)$"):
        await chain.search()

    assert chain.header_sent == [True]
    assert chain.lookups == [] and chain.calls == []


@pytest.mark.asyncio
async def test_tokens_and_the_national_id_never_appear_in_logs(chain, caplog):
    caplog.set_level(logging.DEBUG)

    for auth_mode in ("audit", "enforce"):
        for token in (MCP_BACKEND_TOKEN, WRONG_TOKEN, VOICE_TOKEN, AGENT_TOKEN, None):
            for tenant in ("clinic-001", "clinic-002"):
                chain.configure(token, auth_mode)
                try:
                    await chain.search(tenant=tenant)
                except RuntimeError:
                    pass

    assert "booking_service_auth_missing" in caplog.text  # the guard's warnings were captured
    for secret in (MCP_BACKEND_TOKEN, WRONG_TOKEN, VOICE_TOKEN, AGENT_TOKEN, TEST_JWT_SECRET, SYNTHETIC_NATIONAL_ID):
        assert secret not in caplog.text
