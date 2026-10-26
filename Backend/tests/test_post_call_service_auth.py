"""POST /api/v1/post-call/booking-confirmation: trusted gateway + tenant allow-list.

Real service authentication through the route; booking lookup and WhatsApp
delivery are recording fakes, so we can prove rejected requests trigger
neither. No database, no network.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

from app.api import dependencies as deps
from app.api.routers import post_call as post_call_router
from app.core.config import get_settings
from app.security.service_auth import SERVICE_TOKEN_HEADER
from tests.test_post_call_whatsapp_delivery import FakeAppointmentService, FakeN8NWhatsAppClient

# Test-only credentials (not real secrets).
VOICE_TOKEN = "voice-gateway-test-token-0123456789abcdef"
CREDENTIALS = f"voice_gateway={VOICE_TOKEN}@clinic-001"

PROVIDERS = {
    "clinic-001": SimpleNamespace(id=uuid4(), tenant_key="clinic-001"),
    "clinic-002": SimpleNamespace(id=uuid4(), tenant_key="clinic-002"),
}
BODY = {"event_type": "booking_confirmation", "appointment_reference": "APT-260828-ABC123", "source": "voice"}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("MEDMIND_SERVICE_CREDENTIALS", CREDENTIALS)
    get_settings.cache_clear()
    FakeN8NWhatsAppClient.instances.clear()
    FakeN8NWhatsAppClient.should_fail = False
    monkeypatch.setattr(post_call_router, "N8NWhatsAppClient", FakeN8NWhatsAppClient)
    appointments = FakeAppointmentService()

    app = FastAPI()
    app.include_router(post_call_router.router, prefix="/api/v1")

    def provider_from_header(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
        return PROVIDERS[x_tenant_id]

    app.dependency_overrides[deps.get_current_provider] = provider_from_header
    app.dependency_overrides[deps.get_appointment_service] = lambda: appointments
    yield SimpleNamespace(client=TestClient(app), appointments=appointments)
    get_settings.cache_clear()


def _post(env, *, tenant="clinic-001", token=VOICE_TOKEN):
    headers = {"X-Tenant-ID": tenant}
    if token is not None:
        headers[SERVICE_TOKEN_HEADER] = token
    return env.client.post("/api/v1/post-call/booking-confirmation", headers=headers, json=BODY)


def _whatsapp_calls():
    return [call for client in FakeN8NWhatsAppClient.instances for call in client.calls]


def _nothing_triggered(env):
    return not env.appointments.calls and not _whatsapp_calls()


@pytest.mark.parametrize("token, code", [(None, "SERVICE_AUTH_REQUIRED"),
                                         ("wrong-token-0123456789abcdef0123456789", "SERVICE_AUTH_INVALID")])
def test_missing_or_invalid_token_is_401_and_sends_nothing(env, token, code):
    response = _post(env, token=token)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == code
    assert _nothing_triggered(env)


def test_unconfigured_credentials_fail_closed_and_send_nothing(env, monkeypatch):
    monkeypatch.delenv("MEDMIND_SERVICE_CREDENTIALS")
    get_settings.cache_clear()
    assert _post(env).status_code == 503
    assert _nothing_triggered(env)


def test_tenant_not_allowed_for_the_gateway_is_403_and_sends_nothing(env):
    response = _post(env, tenant="clinic-002")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SERVICE_TENANT_NOT_ALLOWED"
    assert _nothing_triggered(env)


def test_authorized_gateway_delivers_once_for_its_tenant(env):
    response = _post(env)
    assert response.status_code == 200
    body = response.json()
    assert body["appointment_reference"] == "APT-260828-ABC123" and body["prepared"] is True
    assert env.appointments.calls[0]["provider_id"] == PROVIDERS["clinic-001"].id
    calls = _whatsapp_calls()
    assert len(calls) == 1
    assert calls[0]["provider_id"] == PROVIDERS["clinic-001"].id


def test_voice_post_call_client_sends_service_token():
    import asyncio

    from voice_gateway.post_call_client import PostCallClient

    sent = {}

    class RecordingHttp:
        async def post(self, url, *, headers, json):
            sent.update(url=url, headers=dict(headers), json=json)
            return SimpleNamespace(
                raise_for_status=lambda: None, status_code=200,
                json=lambda: {"appointment_reference": "APT-260828-ABC123", "prepared": True,
                              "status": "accepted"},
            )

        async def aclose(self):
            return None

    client = PostCallClient(base_url="http://test", service_token=VOICE_TOKEN)
    client._client = RecordingHttp()
    asyncio.run(client.send_booking_confirmation(tenant_id="clinic-001", appointment_reference="APT-260828-ABC123"))
    assert sent["headers"] == {"X-Tenant-ID": "clinic-001", SERVICE_TOKEN_HEADER: VOICE_TOKEN}
