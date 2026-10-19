"""AI chat: trusted-service auth, server-issued session ownership, voice gateway
session handling and fresh identity for cancel/reschedule. No database."""

import asyncio
import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr

import app.api.routers.medmind_ai as medmind_router
from app.api import dependencies as deps
from app.core.config import Settings, get_settings
from app.security.service_auth import (
    SERVICE_TOKEN_HEADER,
    ServiceCredentialsConfigError,
    authenticate_service_token,
    parse_service_credentials,
)
from app.services.ai_chat_session_registry import SESSION_ID_PREFIX, AIChatSessionRegistry

# Test-only credentials (not real secrets).
VOICE_TOKEN = "voice-gateway-test-token-0123456789abcdef"
WHATSAPP_TOKEN = "whatsapp-gateway-test-token-0123456789abcd"
# voice_gateway may act for both clinics; whatsapp_gateway only for clinic-001.
CREDENTIALS = (
    f"voice_gateway={VOICE_TOKEN}@clinic-001,clinic-002;"
    f"whatsapp_gateway={WHATSAPP_TOKEN}@clinic-001"
)


def _settings(raw):
    return Settings(medmind_service_credentials=SecretStr(raw) if raw is not None else None)


# ================================================================ credential parsing / auth


def test_parse_service_credentials():
    parsed = parse_service_credentials(CREDENTIALS)
    assert parsed["voice_gateway"].token == VOICE_TOKEN
    assert parsed["voice_gateway"].allowed_tenants == {"clinic-001", "clinic-002"}
    assert parsed["whatsapp_gateway"].allowed_tenants == {"clinic-001"}


@pytest.mark.parametrize("raw", [
    "", "voice_gateway=short@clinic-001", "Bad Name=" + "x" * 40 + "@clinic-001", "noseparator",
    f"a={VOICE_TOKEN}@clinic-001;a={WHATSAPP_TOKEN}@clinic-001",
    f"a={VOICE_TOKEN}@clinic-001;b={VOICE_TOKEN}@clinic-002",
    # tenant authorization must be explicit and well-formed
    f"voice_gateway={VOICE_TOKEN}",                    # no tenant list
    f"voice_gateway={VOICE_TOKEN}@",                   # empty tenant list
    f"voice_gateway={VOICE_TOKEN}@clinic-001,,x",      # empty tenant entry
    f"voice_gateway={VOICE_TOKEN}@*",                  # wildcard
    f"voice_gateway={VOICE_TOKEN}@clinic-*",           # partial wildcard
    f"voice_gateway={VOICE_TOKEN}@bad tenant",         # invalid tenant id
])
def test_malformed_credentials_are_rejected_without_echoing_tokens(raw):
    with pytest.raises(ServiceCredentialsConfigError) as exc_info:
        parse_service_credentials(raw)
    assert VOICE_TOKEN not in str(exc_info.value) and WHATSAPP_TOKEN not in str(exc_info.value)


@pytest.mark.parametrize("raw", [None, "voice_gateway=short", f"voice_gateway={VOICE_TOKEN}",
                                 f"voice_gateway={VOICE_TOKEN}@*"])
def test_unconfigured_or_malformed_credentials_fail_closed(raw):
    with pytest.raises(HTTPException) as exc_info:
        authenticate_service_token(VOICE_TOKEN, _settings(raw))
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "SERVICE_AUTH_NOT_CONFIGURED"


@pytest.mark.parametrize("token, code", [(None, "SERVICE_AUTH_REQUIRED"), ("", "SERVICE_AUTH_REQUIRED"),
                                         ("wrong-token-0123456789abcdef0123456789", "SERVICE_AUTH_INVALID")])
def test_missing_or_invalid_token_is_401(token, code):
    with pytest.raises(HTTPException) as exc_info:
        authenticate_service_token(token, _settings(CREDENTIALS))
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["code"] == code


def test_valid_token_identifies_its_service_and_tenants():
    voice = authenticate_service_token(VOICE_TOKEN, _settings(CREDENTIALS))
    whatsapp = authenticate_service_token(WHATSAPP_TOKEN, _settings(CREDENTIALS))
    assert (voice.name, voice.allowed_tenants) == ("voice_gateway", {"clinic-001", "clinic-002"})
    assert (whatsapp.name, whatsapp.allowed_tenants) == ("whatsapp_gateway", {"clinic-001"})


# ================================================================ API


class FakeAgent:
    def __init__(self):
        self.chat_calls = []
        self.cleared = []
        self.state_store = SimpleNamespace(clear=self._clear)

    async def _clear(self, session_id):
        self.cleared.append(session_id)

    async def chat(self, **kwargs):
        self.chat_calls.append(kwargs)
        return {"reply": "ok", "stage": "new"}


class FakeAgentRegistry:
    def __init__(self, agent):
        self.agent = agent

    async def get(self, *, tenant_id, tenant_context=None):
        return self.agent

    async def clear_session_state(self, *, tenant_id, session_id):
        await self.agent.state_store.clear(session_id)


PROVIDERS = {
    "clinic-001": SimpleNamespace(id=uuid4(), tenant_key="clinic-001", org_type="clinic"),
    "clinic-002": SimpleNamespace(id=uuid4(), tenant_key="clinic-002", org_type="clinic"),
}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("MEDMIND_SERVICE_CREDENTIALS", CREDENTIALS)
    get_settings.cache_clear()
    agent = FakeAgent()
    app = FastAPI()
    app.include_router(medmind_router.router, prefix="/api/v1")
    app.state.medmind_registry = FakeAgentRegistry(agent)

    def provider_from_header(x_tenant_id: str = medmind_router.Header(..., alias="X-Tenant-ID")):
        return PROVIDERS[x_tenant_id]

    app.dependency_overrides[deps.get_current_provider] = provider_from_header
    monkeypatch.setattr(medmind_router, "build_tenant_context",
                        lambda provider: SimpleNamespace(tenant_id=provider.tenant_key))
    client = TestClient(app)
    yield SimpleNamespace(client=client, agent=agent, app=app)
    get_settings.cache_clear()


def _h(tenant="clinic-001", token=VOICE_TOKEN):
    headers = {"X-Tenant-ID": tenant}
    if token is not None:
        headers[SERVICE_TOKEN_HEADER] = token
    return headers


def _new_session(api, channel="voice", **kw):
    response = api.client.post("/api/v1/ai/sessions", json={"channel": channel}, headers=_h(**kw))
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def _chat(api, session_id, channel="voice", **kw):
    return api.client.post("/api/v1/ai/chat", headers=_h(**kw),
                           json={"session_id": session_id, "message": "hello", "channel": channel})


@pytest.mark.parametrize("path, method, body", [
    ("/api/v1/ai/sessions", "post", {"channel": "voice"}),
    ("/api/v1/ai/chat", "post", {"session_id": "x", "message": "hi", "channel": "voice"}),
    ("/api/v1/ai/chat-v2", "post", {"session_id": "x", "message": "hi", "channel": "voice"}),
    ("/api/v1/ai/warmup", "post", None),
    ("/api/v1/ai/sessions/close", "post", {"session_id": "x"}),
])
@pytest.mark.parametrize("token", [None, "wrong-token-0123456789abcdef0123456789"])
def test_ai_routes_reject_missing_or_invalid_service_token(api, path, method, body, token):
    kwargs = {"headers": _h(token=token)}
    if body is not None:
        kwargs["json"] = body
    response = getattr(api.client, method)(path, **kwargs)
    assert response.status_code == 401
    assert not api.agent.chat_calls


def test_chat_fails_closed_when_credentials_are_not_configured(api, monkeypatch):
    monkeypatch.delenv("MEDMIND_SERVICE_CREDENTIALS")
    get_settings.cache_clear()
    assert _chat(api, "anything").status_code == 503
    assert api.client.post("/api/v1/ai/sessions", json={"channel": "voice"}, headers=_h()).status_code == 503
    assert not api.agent.chat_calls


def test_session_ids_are_server_issued_and_unpredictable(api):
    ids = {_new_session(api) for _ in range(5)}
    assert len(ids) == 5
    assert all(i.startswith(SESSION_ID_PREFIX) and len(i) >= 40 for i in ids)


def test_valid_session_reaches_the_agent_with_that_session(api):
    session_id = _new_session(api)
    response = _chat(api, session_id)
    assert response.status_code == 200
    assert api.agent.chat_calls[0]["session_id"] == session_id


@pytest.mark.parametrize("invented", ["voice-PJSIP/100-00000001", "session-1", "mms_guess"])
def test_client_chosen_session_id_is_rejected(api, invented):
    response = _chat(api, invented)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "CHAT_SESSION_NOT_FOUND"
    assert not api.agent.chat_calls


# ---------------------------------------------------------------- tenant authorization


TENANT_ROUTES = [
    ("post", "/api/v1/ai/sessions", {"channel": "voice"}),
    ("post", "/api/v1/ai/sessions/close", {"session_id": "mms_any"}),
    ("post", "/api/v1/ai/chat", {"session_id": "mms_any", "message": "hi", "channel": "voice"}),
    ("post", "/api/v1/ai/chat-v2", {"session_id": "mms_any", "message": "hi", "channel": "voice"}),
    ("post", "/api/v1/ai/warmup", None),
]


@pytest.mark.parametrize("method, path, body", TENANT_ROUTES)
def test_service_is_denied_for_a_tenant_it_is_not_allowed(api, method, path, body):
    kwargs = {"headers": _h(tenant="clinic-002", token=WHATSAPP_TOKEN)}
    if body is not None:
        kwargs["json"] = body
    response = getattr(api.client, method)(path, **kwargs)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SERVICE_TENANT_NOT_ALLOWED"
    assert not api.agent.chat_calls and not api.agent.cleared


@pytest.mark.parametrize("method, path, body", TENANT_ROUTES)
def test_service_passes_tenant_check_for_an_allowed_tenant(api, method, path, body):
    kwargs = {"headers": _h(tenant="clinic-001", token=WHATSAPP_TOKEN)}
    if body is not None:
        kwargs["json"] = body
    response = getattr(api.client, method)(path, **kwargs)
    # Past the tenant gate: whatever the route answers next, it is not an auth/tenant rejection.
    assert response.status_code not in (401, 403)


def test_allowed_service_can_run_a_full_session_in_its_tenant(api):
    session_id = _new_session(api, tenant="clinic-001", token=WHATSAPP_TOKEN)
    assert _chat(api, session_id, tenant="clinic-001", token=WHATSAPP_TOKEN).status_code == 200
    assert api.client.post("/api/v1/ai/sessions/close", json={"session_id": session_id}, headers=_h(tenant="clinic-001", token=WHATSAPP_TOKEN)).status_code == 204


def test_session_of_another_service_cannot_be_used(api):
    session_id = _new_session(api, token=VOICE_TOKEN)
    assert _chat(api, session_id, token=WHATSAPP_TOKEN).status_code == 404
    assert not api.agent.chat_calls


def test_session_of_another_tenant_cannot_be_used(api):
    session_id = _new_session(api, tenant="clinic-001")
    response = _chat(api, session_id, tenant="clinic-002")
    assert response.status_code == 404
    assert not api.agent.chat_calls


def test_session_cannot_switch_channel(api):
    session_id = _new_session(api, channel="voice")
    assert _chat(api, session_id, channel="web").status_code == 404
    assert not api.agent.chat_calls


def test_closing_a_session_forgets_its_state_and_blocks_reuse(api):
    session_id = _new_session(api)
    assert _chat(api, session_id).status_code == 200
    closed = api.client.post("/api/v1/ai/sessions/close", json={"session_id": session_id}, headers=_h())
    assert closed.status_code == 204
    assert api.agent.cleared == [session_id]
    assert _chat(api, session_id).status_code == 404


def test_only_the_owner_can_close_a_session(api):
    session_id = _new_session(api, token=VOICE_TOKEN)
    assert api.client.post("/api/v1/ai/sessions/close", json={"session_id": session_id}, headers=_h(token=WHATSAPP_TOKEN)).status_code == 404
    assert api.client.post("/api/v1/ai/sessions/close", json={"session_id": session_id}, headers=_h(tenant="clinic-002")).status_code == 404
    assert not api.agent.cleared
    assert _chat(api, session_id).status_code == 200


def test_idle_session_expires(api):
    now = [1000.0]
    api.app.state.ai_chat_session_registry = AIChatSessionRegistry(idle_timeout_seconds=60, clock=lambda: now[0])
    session_id = _new_session(api)
    now[0] += 59
    assert _chat(api, session_id).status_code == 200
    now[0] += 61
    assert _chat(api, session_id).status_code == 404


def test_service_token_is_never_logged(api, caplog):
    with caplog.at_level(logging.DEBUG):
        session_id = _new_session(api)
        _chat(api, session_id)
        _chat(api, session_id, token="wrong-token-0123456789abcdef0123456789")
    assert VOICE_TOKEN not in caplog.text


# ================================================================ voice gateway client


class RecordingHttp:
    def __init__(self, session_payload=None, close_error=None):
        self.requests = []
        self.session_payload = session_payload or {"session_id": "mms_server_issued", "channel": "voice"}
        self.close_error = close_error

    async def post(self, url, *, headers, json=None, timeout=None):
        self.requests.append(("POST", url, dict(headers), json))
        if url.endswith("/ai/sessions/close"):
            if self.close_error:
                raise self.close_error
            return SimpleNamespace(status_code=204)
        payload = self.session_payload if url.endswith("/ai/sessions") else {"reply": "ok", "stage": "new"}
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload, status_code=200)

    async def aclose(self):
        return None


def _voice_client(token=VOICE_TOKEN, **http_kwargs):
    from voice_gateway.medmind_client import MedMindClient

    client = MedMindClient(base_url="http://test", service_token=token)
    client._client = RecordingHttp(**http_kwargs)
    return client


def test_voice_client_creates_server_session_with_service_token():
    client = _voice_client()
    session_id = asyncio.run(client.start_session(tenant_id="clinic-001"))
    method, url, headers, body = client._client.requests[0]
    assert (method, url, body) == ("POST", "/api/v1/ai/sessions", {"channel": "voice"})
    assert headers == {"X-Tenant-ID": "clinic-001", SERVICE_TOKEN_HEADER: VOICE_TOKEN}
    assert session_id == "mms_server_issued"


def test_voice_client_sends_service_token_on_chat():
    client = _voice_client()
    asyncio.run(client.chat(session_id="mms_server_issued", tenant_id="clinic-001", message="hi"))
    _, url, headers, body = client._client.requests[0]
    assert url == "/api/v1/ai/chat"
    assert headers[SERVICE_TOKEN_HEADER] == VOICE_TOKEN
    assert body["session_id"] == "mms_server_issued"


def test_voice_client_rejects_session_response_without_id():
    from voice_gateway.medmind_client import MedMindResponseError

    client = _voice_client(session_payload={"channel": "voice"})
    with pytest.raises(MedMindResponseError):
        asyncio.run(client.start_session(tenant_id="clinic-001"))


def test_voice_client_end_session_is_best_effort_and_keeps_id_out_of_url():
    client = _voice_client(close_error=RuntimeError("network down"))
    asyncio.run(client.end_session(tenant_id="clinic-001", session_id="mms_server_issued"))
    method, url, headers, body = client._client.requests[0]
    assert (method, url) == ("POST", "/api/v1/ai/sessions/close")
    assert body == {"session_id": "mms_server_issued"}
    assert "mms_server_issued" not in url
    assert headers[SERVICE_TOKEN_HEADER] == VOICE_TOKEN


class FailingHttp:
    """Every request fails with a network error, so every error log path runs."""

    def __init__(self, exc):
        self.exc = exc

    async def post(self, *args, **kwargs):
        raise self.exc

    async def aclose(self):
        return None


def test_voice_client_logs_session_fingerprint_not_raw_id(caplog):
    import httpx

    from voice_gateway.medmind_client import session_fingerprint

    secret_session = "mms_" + "S" * 43
    with caplog.at_level(logging.DEBUG):
        ok = _voice_client()
        asyncio.run(ok.chat(session_id=secret_session, tenant_id="clinic-001", message="hi"))
        asyncio.run(ok.end_session(tenant_id="clinic-001", session_id=secret_session))
        for exc in (httpx.ReadTimeout("t"), httpx.ConnectError("c")):
            failing = _voice_client()
            failing._client = FailingHttp(exc)
            with pytest.raises(Exception):
                asyncio.run(failing.chat(session_id=secret_session, tenant_id="clinic-001", message="hi"))
    assert secret_session not in caplog.text
    assert session_fingerprint(secret_session) in caplog.text
    assert len(session_fingerprint(secret_session)) == 12
    assert session_fingerprint(None) == "-"


def test_voice_client_without_token_warns_and_sends_no_credential(monkeypatch, caplog):
    monkeypatch.delenv("MEDMIND_SERVICE_TOKEN", raising=False)
    with caplog.at_level(logging.WARNING):
        client = _voice_client(token=None)
    assert "medmind_service_token_missing" in caplog.text
    asyncio.run(client.chat(session_id="s", tenant_id="clinic-001", message="hi"))
    assert SERVICE_TOKEN_HEADER not in client._client.requests[0][2]


def test_voice_client_never_logs_the_token(caplog):
    with caplog.at_level(logging.DEBUG):
        client = _voice_client()
        asyncio.run(client.start_session(tenant_id="clinic-001"))
        asyncio.run(client.chat(session_id="mms_x", tenant_id="clinic-001", message="hi"))
        asyncio.run(client.end_session(tenant_id="clinic-001", session_id="mms_x"))
    assert VOICE_TOKEN not in caplog.text


def test_voice_gateway_uses_server_session_not_channel_id():
    # voice_gateway.main imports audioop (via audio/codec.py), which Python 3.13
    # removed, so read the function's source instead of importing the module.
    import ast
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "voice_gateway" / "main.py"
    text = path.read_text(encoding="utf-8-sig")
    node = next(n for n in ast.walk(ast.parse(text))
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "consume_final_transcripts")
    source = ast.get_source_segment(text, node)
    assert 'f"voice-{channel_id}"' not in source
    assert "session_id: str | None = None" in source
    assert "medmind.start_session(" in source
    assert "medmind.end_session(" in source


# ================================================================ fresh identity for cancel / reschedule


class StopAtTool(Exception):
    pass


class RecordingTools:
    def __init__(self):
        self.calls = []

    async def call(self, name, **kwargs):
        self.calls.append((name, kwargs))
        raise StopAtTool(name)


OLD_NID = "29001010100011"
FRESH_NID = "29001010100022"


def _state(**overrides):
    from medmind.state.models import SessionState

    values = {"channel": "voice", "session_id": "mms_test", "tenant_id": "clinic-001", "language": "ar",
              "national_id": OLD_NID, "patient_id": "patient-1", "patient_name": "Aya"}
    values.update(overrides)
    return SessionState(**values)


def _nlu(operation, national_id=None):
    from medmind.understanding.types import NLUEntities, NLUResult

    return NLUResult(intent=operation, operation_type=operation,
                     entities=NLUEntities(national_id=national_id), confirmation="unknown", confidence=1.0)


def _workflow(operation):
    from medmind.workflows.cancel import CancelWorkflow
    from medmind.workflows.reschedule import RescheduleWorkflow

    tools = RecordingTools()
    cls = CancelWorkflow if operation == "cancel_appointment" else RescheduleWorkflow
    return cls(tools=tools), tools


OPERATIONS = ["cancel_appointment", "reschedule_appointment"]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("previous", [
    {"operation_type": "book_appointment", "stage": "booking_completed"},
    {"operation_type": None, "stage": "new"},
])
def test_retained_national_id_is_not_trusted_for_a_new_operation(operation, previous):
    workflow, tools = _workflow(operation)
    state = _state(**previous)
    result = asyncio.run(workflow.handle(state=state, nlu=_nlu(operation)))
    assert state.national_id is None
    assert "national_id" in state.stage
    assert not tools.calls, "no booking lookup or change without a fresh national ID"
    assert result.reply


@pytest.mark.parametrize("operation, completed", [
    ("cancel_appointment", "cancel_completed"),
    ("reschedule_appointment", "reschedule_completed"),
])
def test_repeat_operation_after_completion_needs_fresh_identity(operation, completed):
    workflow, tools = _workflow(operation)
    state = _state(operation_type=operation, stage=completed)
    asyncio.run(workflow.handle(state=state, nlu=_nlu(operation)))
    assert state.national_id is None
    assert not tools.calls


@pytest.mark.parametrize("operation", OPERATIONS)
def test_national_id_given_in_this_operation_is_used(operation):
    workflow, tools = _workflow(operation)
    state = _state(operation_type="book_appointment", stage="booking_completed")
    with pytest.raises(StopAtTool):
        asyncio.run(workflow.handle(state=state, nlu=_nlu(operation, national_id=FRESH_NID)))
    sent = tools.calls[0][1]
    assert sent.get("national_id") == FRESH_NID
    assert OLD_NID not in str(tools.calls)


def test_booking_flow_keeps_patient_context():
    """forget_identity_proof only drops the national ID; booking is untouched."""
    state = _state(operation_type="book_appointment", stage="booking_completed")
    state.forget_identity_proof()
    assert state.national_id is None
    assert (state.patient_id, state.patient_name) == ("patient-1", "Aya")
