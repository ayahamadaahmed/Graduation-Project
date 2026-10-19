"""POST /diagnostics/attachments: trusted gateway + tenant allow-list + owned session.

Real service authentication (MEDMIND_SERVICE_CREDENTIALS) and the real session
registry; storage and patient binding are recording fakes so we can prove that
a rejected upload writes nothing. No database.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

from app.api import dependencies as deps
from app.api.routers import diagnostics
from app.core.config import get_settings
from app.security.service_auth import SERVICE_TOKEN_HEADER
from app.services.ai_chat_session_registry import AIChatSessionRegistry
from tests.test_diagnostic_attachment_upload_api import FakeAttachmentService, FakeBindingService

# Test-only credentials (not real secrets).
VOICE_TOKEN = "voice-gateway-test-token-0123456789abcdef"
WEB_TOKEN = "web-bff-test-token-0123456789abcdef012345"
CREDENTIALS = (
    f"voice_gateway={VOICE_TOKEN}@clinic-001,clinic-002;"
    f"web_bff={WEB_TOKEN}@clinic-001"
)

PROVIDERS = {
    "clinic-001": SimpleNamespace(id=uuid4(), tenant_key="clinic-001"),
    "clinic-002": SimpleNamespace(id=uuid4(), tenant_key="clinic-002"),
}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("MEDMIND_SERVICE_CREDENTIALS", CREDENTIALS)
    get_settings.cache_clear()
    now = [1000.0]
    sessions = AIChatSessionRegistry(idle_timeout_seconds=60, clock=lambda: now[0])
    store, binding = FakeAttachmentService(), FakeBindingService()

    app = FastAPI()
    app.include_router(diagnostics.router, prefix="/api/v1")
    app.state.ai_chat_session_registry = sessions

    def provider_from_header(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
        return PROVIDERS[x_tenant_id]

    app.dependency_overrides[deps.get_current_provider] = provider_from_header
    app.dependency_overrides[deps.get_diagnostic_attachment_service] = lambda: store
    app.dependency_overrides[deps.get_diagnostic_attachment_binding_service] = lambda: binding
    yield SimpleNamespace(client=TestClient(app), sessions=sessions, store=store, binding=binding, now=now)
    get_settings.cache_clear()


def _session(env, *, tenant="clinic-001", service="voice_gateway", channel="voice"):
    return env.sessions.create(
        provider_id=PROVIDERS[tenant].id, service_name=service, channel=channel
    ).session_id


def _upload(env, session_id, *, tenant="clinic-001", token=VOICE_TOKEN, **form):
    headers = {"X-Tenant-ID": tenant}
    if token is not None:
        headers[SERVICE_TOKEN_HEADER] = token
    return env.client.post(
        "/api/v1/diagnostics/attachments",
        headers=headers,
        data={"session_id": session_id, **{k: str(v) for k, v in form.items()}},
        files={"file": ("xray.jpg", b"fake-image-data", "image/jpeg")},
    )


def _nothing_written(env):
    return not env.store.calls and not env.binding.calls


# ---------------------------------------------------------------- accepted


def test_owned_session_upload_is_stored_with_that_session(env):
    session_id = _session(env)
    response = _upload(env, session_id)
    assert response.status_code == 201
    assert env.store.calls[0]["session_id"] == session_id
    assert env.store.calls[0]["provider_id"] == PROVIDERS["clinic-001"].id


def test_session_from_any_channel_of_the_same_owner_is_accepted(env):
    session_id = _session(env, channel="web")
    assert _upload(env, session_id).status_code == 201


def test_patient_binding_still_goes_through_identity_binding(env):
    session_id = _session(env)
    patient_id = uuid4()
    response = _upload(env, session_id, patient_id=patient_id, national_id="29001010100011")
    assert response.status_code == 201
    # National-ID verification itself (real binding service) is covered in
    # tests/test_diagnostic_attachment_identity.py; here: binding is still reached.
    assert env.binding.calls[0]["patient_id"] == patient_id


# ---------------------------------------------------------------- service credential


@pytest.mark.parametrize("token, code", [(None, "SERVICE_AUTH_REQUIRED"),
                                         ("wrong-token-0123456789abcdef0123456789", "SERVICE_AUTH_INVALID")])
def test_upload_without_valid_service_credential_is_401(env, token, code):
    session_id = _session(env)
    response = _upload(env, session_id, token=token)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == code
    assert _nothing_written(env)


def test_upload_fails_closed_without_configured_credentials(env, monkeypatch):
    monkeypatch.delenv("MEDMIND_SERVICE_CREDENTIALS")
    get_settings.cache_clear()
    response = _upload(env, _session(env))
    assert response.status_code == 503
    assert _nothing_written(env)


def test_upload_for_a_tenant_the_service_is_not_allowed_is_403(env):
    session_id = _session(env, tenant="clinic-002", service="web_bff")
    response = _upload(env, session_id, tenant="clinic-002", token=WEB_TOKEN)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SERVICE_TENANT_NOT_ALLOWED"
    assert _nothing_written(env)


# ---------------------------------------------------------------- session ownership


def _assert_rejected(env, response):
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "CHAT_SESSION_NOT_FOUND"
    assert _nothing_written(env)


@pytest.mark.parametrize("session_id", ["session-1", "mms_invented", "voice-PJSIP/100-00000001"])
def test_unknown_session_is_rejected(env, session_id):
    _assert_rejected(env, _upload(env, session_id))


def test_expired_session_is_rejected(env):
    session_id = _session(env)
    env.now[0] += 61
    _assert_rejected(env, _upload(env, session_id))


def test_closed_session_is_rejected(env):
    session_id = _session(env)
    env.sessions.close(session_id=session_id, provider_id=PROVIDERS["clinic-001"].id, service_name="voice_gateway")
    _assert_rejected(env, _upload(env, session_id))


def test_session_of_another_service_is_rejected(env):
    session_id = _session(env, service="web_bff")
    _assert_rejected(env, _upload(env, session_id, token=VOICE_TOKEN))


def test_session_of_another_tenant_is_rejected(env):
    # voice_gateway is allowed for both tenants, so only session ownership can stop this.
    session_id = _session(env, tenant="clinic-002")
    _assert_rejected(env, _upload(env, session_id, tenant="clinic-001"))


def test_foreign_session_with_patient_binding_never_reaches_identity_lookup(env):
    session_id = _session(env, service="web_bff")
    response = _upload(env, session_id, patient_id=uuid4(), national_id="29001010100011")
    _assert_rejected(env, response)
