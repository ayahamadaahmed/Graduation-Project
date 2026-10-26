"""Asterisk media WebSocket authentication + tenant allow-list.

`authorize_media_start` is tested directly. voice_gateway.main cannot be imported
in this environment (audioop removed in Python 3.13, silero_vad not installed),
so the WebSocket wiring is checked structurally from its source. No network.
"""

import ast
from pathlib import Path

import pytest

from voice_gateway.media_auth import (
    MediaAuthError,
    auth_timeout_seconds,
    authorize_media_start,
)

# Test-only secret (not a real credential).
SECRET = "media-shared-secret-for-tests-0123456789abcdef"
ENV = {
    "VOICE_MEDIA_SHARED_SECRET": SECRET,
    "VOICE_ALLOWED_TENANT_IDS": "clinic-001,lab-001",
}


def _event(token=SECRET, tenant="clinic-001", **extra_vars):
    variables = dict(extra_vars)
    if token is not None:
        variables["MEDMIND_MEDIA_TOKEN"] = token
    if tenant is not None:
        variables["MEDMIND_TENANT_ID"] = tenant
    return {"event": "MEDIA_START", "format": "ulaw", "channel_variables": variables}


def _reason(event, env=ENV):
    with pytest.raises(MediaAuthError) as exc_info:
        authorize_media_start(event, env)
    return exc_info.value.reason


# ---------------------------------------------------------------- valid setup


def test_valid_token_and_allowed_tenant_from_asterisk():
    auth = authorize_media_start(_event(), ENV)
    assert (auth.tenant_id, auth.tenant_source) == ("clinic-001", "asterisk")


def test_environment_tenant_is_used_only_if_allow_listed():
    env = {**ENV, "VOICE_TENANT_ID": "lab-001"}
    auth = authorize_media_start(_event(tenant=None), env)
    assert (auth.tenant_id, auth.tenant_source) == ("lab-001", "environment")


# ---------------------------------------------------------------- authentication


def test_missing_token_is_rejected():
    assert _reason(_event(token=None)) == "missing_media_token"


def test_missing_channel_variables_is_rejected():
    assert _reason({"event": "MEDIA_START", "format": "ulaw"}) == "missing_media_token"


@pytest.mark.parametrize("token", ["wrong", SECRET[:-1], SECRET + "x", SECRET.upper()])
def test_invalid_token_is_rejected(token):
    assert _reason(_event(token=token)) == "invalid_media_token"


def test_rejection_reasons_never_contain_the_secret():
    for event in (_event(token="wrong"), _event(token=None), _event(tenant="clinic-999")):
        with pytest.raises(MediaAuthError) as exc_info:
            authorize_media_start(event, ENV)
        assert SECRET not in str(exc_info.value) and SECRET not in exc_info.value.reason


# ---------------------------------------------------------------- tenant restriction


def test_tenant_not_in_allow_list_is_rejected():
    assert _reason(_event(tenant="clinic-002")) == "tenant_not_allowed"


def test_missing_tenant_without_env_default_is_rejected():
    # The old hard-coded "clinic-001" fallback is gone: no tenant => fail closed.
    assert _reason(_event(tenant=None)) == "missing_tenant"


def test_env_default_tenant_outside_allow_list_is_rejected():
    env = {**ENV, "VOICE_TENANT_ID": "clinic-002"}
    assert _reason(_event(tenant=None), env) == "tenant_not_allowed"


# ---------------------------------------------------------------- fail-closed configuration


@pytest.mark.parametrize("env, reason", [
    ({"VOICE_ALLOWED_TENANT_IDS": "clinic-001"}, "shared_secret_not_configured"),
    ({**ENV, "VOICE_MEDIA_SHARED_SECRET": "too-short"}, "shared_secret_not_configured"),
    ({"VOICE_MEDIA_SHARED_SECRET": SECRET}, "allowed_tenants_not_configured"),
    ({**ENV, "VOICE_ALLOWED_TENANT_IDS": ""}, "allowed_tenants_not_configured"),
    ({**ENV, "VOICE_ALLOWED_TENANT_IDS": "clinic-001,,lab-001"}, "allowed_tenants_not_configured"),
    ({**ENV, "VOICE_ALLOWED_TENANT_IDS": "*"}, "allowed_tenants_invalid"),
    ({**ENV, "VOICE_ALLOWED_TENANT_IDS": "clinic-*"}, "allowed_tenants_invalid"),
    ({**ENV, "VOICE_ALLOWED_TENANT_IDS": "bad tenant"}, "allowed_tenants_invalid"),
])
def test_unconfigured_or_invalid_configuration_rejects_every_call(env, reason):
    assert _reason(_event(), env) == reason


@pytest.mark.parametrize("raw, expected", [(None, 10.0), ("5", 5.0), ("0", 10.0), ("-3", 10.0), ("x", 10.0)])
def test_auth_timeout_configuration(raw, expected):
    env = {} if raw is None else {"VOICE_MEDIA_AUTH_TIMEOUT_SECONDS": raw}
    assert auth_timeout_seconds(env) == expected


# ---------------------------------------------------------------- WebSocket wiring (structural)


def _asterisk_media_source():
    path = Path(__file__).resolve().parents[1] / "voice_gateway" / "main.py"
    text = path.read_text(encoding="utf-8-sig")
    node = next(n for n in ast.walk(ast.parse(text))
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "asterisk_media")
    return ast.get_source_segment(text, node)


def test_media_start_is_authorized_before_any_session_or_pipeline_is_created():
    src = _asterisk_media_source()
    start = src.index('== "MEDIA_START"')
    gate = src.index("authorize_media_start(", start)
    close = src.index("await websocket.close(", gate)
    for later in ("VoiceSession(", "StreamingVAD()", "consume_final_transcripts(", "DeepgramStreamingSTT("):
        assert gate < close < src.index(later, start), later


def test_unauthenticated_connections_time_out_and_audio_is_ignored_until_authorized():
    src = _asterisk_media_source()
    assert "if media_authorization is None:" in src
    assert "asyncio.wait_for(" in src and "media_auth_deadline" in src
    # Pre-auth audio is dropped (the log literal is split across two strings in main.py).
    assert '"audio_received_before_"' in src


def test_tenant_comes_only_from_the_authorization_without_hardcoded_fallback():
    src = _asterisk_media_source()
    assert '"clinic-001"' not in src and "legacy_default" not in src
    assert "media_authorization.tenant_id" in src
