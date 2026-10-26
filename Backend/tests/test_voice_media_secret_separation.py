"""The media shared secret is its own credential (voice_gateway/media_auth.py).

If VOICE_MEDIA_SHARED_SECRET equals a service-hop token in the process
environment, the gateway is misconfigured and rejects every call (fail
closed, like an unset secret), even when the caller presents that value.
Synthetic test-only values; no network, no database.
"""

import logging

import pytest

from tests.test_voice_media_websocket_auth import (  # noqa: F401  gateway is a fixture
    SECRET,
    TENANT,
    assert_nothing_started,
    assert_secret_not_logged,
    gateway,
    media_start,
    rejected,
    rejection_reasons,
)
from voice_gateway.media_auth import MediaAuthError, authorize_media_start

OTHER_TOKEN = "synthetic-other-service-token-0123456789ab"
EVENT = {
    "event": "MEDIA_START",
    "channel_variables": {"MEDMIND_MEDIA_TOKEN": SECRET, "MEDMIND_TENANT_ID": TENANT},
}


def _env(**extra):
    return {"VOICE_MEDIA_SHARED_SECRET": SECRET, "VOICE_ALLOWED_TENANT_IDS": TENANT, **extra}


REUSED = [
    {"MEDMIND_SERVICE_TOKEN": SECRET},
    {"MCP_SERVER_TOKEN": SECRET},
    {"MCP_SERVER_TOKEN_NEXT": SECRET},
    {"MCP_BACKEND_SERVICE_TOKEN": SECRET},
    {"MEDMIND_SERVICE_TOKEN": f"  {SECRET}  "},  # compared trimmed, like the secret
    {"MEDMIND_SERVICE_CREDENTIALS": f"voice_gateway={SECRET}@{TENANT}"},
    {"MEDMIND_SERVICE_CREDENTIALS": f"voice_gateway={OTHER_TOKEN}@{TENANT};mcp_server={SECRET}@{TENANT}"},
    {"MEDMIND_SERVICE_CREDENTIALS_NEXT": f"voice_gateway={SECRET}@{TENANT}"},
]
REUSED_IDS = [
    "medmind-service-token", "mcp-server-token", "mcp-server-token-next", "mcp-backend-token",
    "service-token-with-spaces", "credentials", "credentials-second-entry", "credentials-next",
]


@pytest.mark.parametrize("extra", REUSED, ids=REUSED_IDS)
def test_a_media_secret_equal_to_a_service_token_rejects_every_call(extra):
    with pytest.raises(MediaAuthError) as error:
        authorize_media_start(EVENT, _env(**extra))

    assert error.value.reason == "shared_secret_reuses_service_token"
    assert SECRET not in str(error.value)


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"MEDMIND_SERVICE_TOKEN": OTHER_TOKEN},
        {"MCP_SERVER_TOKEN": OTHER_TOKEN, "MCP_BACKEND_SERVICE_TOKEN": OTHER_TOKEN + "x"},
        {"MEDMIND_SERVICE_CREDENTIALS": f"voice_gateway={OTHER_TOKEN}@{TENANT}"},
        {"MEDMIND_SERVICE_TOKEN": SECRET[:-1]},  # similar is not equal
        {"MEDMIND_SERVICE_TOKEN": ""},
    ],
    ids=["no-service-tokens", "distinct-service-token", "distinct-mcp-tokens", "distinct-credentials",
         "prefix-of-secret", "empty-service-token"],
)
def test_a_distinct_media_secret_is_accepted(extra):
    authorization = authorize_media_start(EVENT, _env(**extra))

    assert authorization.tenant_id == TENANT


def test_reuse_is_checked_before_the_presented_token():
    # Even a wrong presented token reports the configuration problem first.
    event = {"channel_variables": {"MEDMIND_MEDIA_TOKEN": "wrong", "MEDMIND_TENANT_ID": TENANT}}

    with pytest.raises(MediaAuthError) as error:
        authorize_media_start(event, _env(MEDMIND_SERVICE_TOKEN=SECRET))

    assert error.value.reason == "shared_secret_reuses_service_token"


def test_the_endpoint_rejects_a_reused_secret_with_1008_and_starts_nothing(gateway, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("MEDMIND_SERVICE_TOKEN", SECRET)

    rejected(gateway, lambda ws: ws.send_text(media_start()))

    assert rejection_reasons(caplog) == ["shared_secret_reuses_service_token"]
    assert_nothing_started(gateway)
    assert gateway.post_call_clients() == []
    assert_secret_not_logged(caplog)


def test_the_endpoint_accepts_a_distinct_service_token(gateway, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("MEDMIND_SERVICE_TOKEN", OTHER_TOKEN)

    def interact(ws):
        ws.send_text(media_start())
        assert gateway.started.wait(5), "pipeline did not start"
        ws.close()

    gateway.run(interact)

    assert rejection_reasons(caplog) == []
    assert gateway.consumers[0]["tenant_id"] == TENANT
    assert_secret_not_logged(caplog)
