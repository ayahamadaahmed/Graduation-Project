"""Behavioural tests for authentication on the real /asterisk/media endpoint.

The FastAPI app runs in-process through Starlette's TestClient (no sockets,
no network). Every provider the endpoint would create after authentication
(Hamsa STT, Deepgram STT, VAD, the MedMind/TTS consumer) is replaced by a
recorder, so the tests prove that nothing is created or started before
MEDIA_START is authorized. Synthetic secret, tenants and call IDs only.

Not covered here (needs a real Asterisk): whether Asterisk actually puts
MEDMIND_MEDIA_TOKEN into MEDIA_START.channel_variables.

Post-call processing runs only for an authenticated call, with the tenant
verified by authorize_media_start(). Rejected or unauthenticated connections
never create a post-call client (regression tests for the former cleanup
UnboundLocalError on tenant_id are below).
"""

import json
import logging
import threading
import time

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import voice_gateway.main as voice_main

SECRET = "synthetic-media-secret-0123456789abcdef"  # >= 32 characters
WRONG_SECRET = "synthetic-wrong-secret-0123456789abcdef"
TENANT = "test-tenant"
OTHER_TENANT = "other-tenant"
POLICY_VIOLATION = 1008


class _Done:
    """Awaitable that resolves to None; returned by every recorder method."""

    def __await__(self):
        return iter(())


class Recorder:
    """Stands in for a provider object; records construction and calls."""

    def __init__(self, kind, created, *args, **kwargs):
        self.kind = kind
        self.calls = []
        created.append(self)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def method(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return _Done()

        return method


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setenv("VOICE_MEDIA_SHARED_SECRET", SECRET)
    monkeypatch.setenv("VOICE_ALLOWED_TENANT_IDS", TENANT)
    monkeypatch.delenv("VOICE_TENANT_ID", raising=False)
    monkeypatch.setenv("VOICE_MEDIA_AUTH_TIMEOUT_SECONDS", "5")

    created = []
    consumers = []
    started = threading.Event()

    def factory(kind):
        return lambda *args, **kwargs: Recorder(kind, created, *args, **kwargs)

    monkeypatch.setattr(voice_main, "HamsaSTT", factory("hamsa_stt"))
    monkeypatch.setattr(voice_main, "DeepgramStreamingSTT", factory("deepgram_stt"))
    monkeypatch.setattr(voice_main, "StreamingVAD", factory("vad"))
    monkeypatch.setattr(voice_main, "PostCallClient", factory("post_call"))
    monkeypatch.setattr(voice_main, "MedMindClient", factory("medmind"))
    monkeypatch.setattr(voice_main, "create_tts_provider", lambda: ("fake", Recorder("tts", created)))

    armed = {}

    async def fake_consumer(queue, **kwargs):
        consumers.append(kwargs)
        # Arm a post-call booking event the way the real consumer does.
        kwargs["conversation_state"].update(armed)
        started.set()
        await voice_main.asyncio.Event().wait()  # runs until the call ends

    monkeypatch.setattr(voice_main, "consume_final_transcripts", fake_consumer)

    class Gateway:
        def __init__(self):
            self.created = created
            self.consumers = consumers
            self.started = started
            self.armed = armed
            self.client = TestClient(voice_main.app)

        def connect(self):
            return self.client.websocket_connect("/asterisk/media", subprotocols=["media"])

        def kinds(self):
            return sorted(r.kind for r in self.created if r.kind in PIPELINE)

        def run(self, interact):
            """Open a connection and interact. Server-side errors propagate."""
            self.server_error = None
            with self.connect() as ws:
                interact(ws)

        def post_call_clients(self):
            return [r for r in self.created if r.kind == "post_call"]

    return Gateway()


def media_start(*, token=SECRET, tenant=TENANT, variables=None, **overrides):
    if variables is None:
        variables = {}
        if token is not None:
            variables["MEDMIND_MEDIA_TOKEN"] = token
        if tenant is not None:
            variables["MEDMIND_TENANT_ID"] = tenant
    event = {
        "event": "MEDIA_START",
        "connection_id": "synthetic-connection",
        "channel_id": "synthetic-channel",
        "channel": "PJSIP/synthetic-0001",
        # The Hamsa primary pipeline accepts only slin24 from Asterisk.
        "format": "slin24",
        "optimal_frame_size": 960,
        "ptime": 20,
        "channel_variables": variables,
    }
    event.update(overrides)
    return json.dumps(event)


def expect_policy_close(ws):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        ws.receive_text()
    assert exc_info.value.code == POLICY_VIOLATION


# Nothing here may exist for a connection that never authenticated,
# including the post-call client (no verified tenant to send for).
PIPELINE = {"hamsa_stt", "deepgram_stt", "vad", "medmind", "tts", "post_call"}


def assert_nothing_started(gateway):
    assert [r.kind for r in gateway.created if r.kind in PIPELINE] == []
    assert gateway.consumers == []


def assert_secret_not_logged(caplog):
    for secret in (SECRET, WRONG_SECRET):
        assert secret not in caplog.text


def rejection_reasons(caplog):
    return [
        r.getMessage().split("reason=")[1].split()[0]
        for r in caplog.records
        if r.getMessage().startswith("media_auth_rejected")
    ]


# ============================================================
# Rejected before any provider exists
# ============================================================


def rejected(gateway, send):
    """Run ``send(ws)``, then expect a 1008 close."""

    def interact(ws):
        send(ws)
        expect_policy_close(ws)

    gateway.run(interact)


@pytest.mark.parametrize(
    "event_kwargs, reason",
    [
        ({"token": None}, "missing_media_token"),
        ({"token": ""}, "missing_media_token"),
        ({"token": WRONG_SECRET}, "invalid_media_token"),
        ({"token": SECRET[:-1]}, "invalid_media_token"),
        ({"tenant": OTHER_TENANT}, "tenant_not_allowed"),
        ({"tenant": None}, "missing_tenant"),
        ({"tenant": "   "}, "missing_tenant"),
        ({"variables": {}}, "missing_media_token"),
        ({"variables": ["MEDMIND_MEDIA_TOKEN", SECRET]}, "missing_media_token"),
        ({"variables": f"MEDMIND_MEDIA_TOKEN={SECRET}"}, "missing_media_token"),
        ({"channel_variables": None}, "missing_media_token"),
    ],
    ids=[
        "missing-token", "empty-token", "wrong-token", "truncated-token",
        "tenant-not-allowed", "missing-tenant", "blank-tenant",
        "empty-channel-variables", "channel-variables-list",
        "channel-variables-string", "channel-variables-null",
    ],
)
def test_bad_media_start_is_closed_with_1008_and_starts_nothing(gateway, caplog, event_kwargs, reason):
    caplog.set_level(logging.DEBUG)
    rejected(gateway, lambda ws: ws.send_text(media_start(**event_kwargs)))

    assert rejection_reasons(caplog) == [reason]
    assert_nothing_started(gateway)
    assert_secret_not_logged(caplog)


def test_missing_channel_variables_key_is_rejected(gateway, caplog):
    caplog.set_level(logging.DEBUG)
    event = json.loads(media_start())
    del event["channel_variables"]
    rejected(gateway, lambda ws: ws.send_text(json.dumps(event)))

    assert rejection_reasons(caplog) == ["missing_media_token"]
    assert_nothing_started(gateway)


@pytest.mark.parametrize(
    "unset, reason",
    [
        ("VOICE_MEDIA_SHARED_SECRET", "shared_secret_not_configured"),
        ("VOICE_ALLOWED_TENANT_IDS", "allowed_tenants_not_configured"),
    ],
)
def test_unconfigured_gateway_rejects_even_a_correct_token(gateway, monkeypatch, caplog, unset, reason):
    caplog.set_level(logging.DEBUG)
    monkeypatch.delenv(unset)
    rejected(gateway, lambda ws: ws.send_text(media_start()))

    assert rejection_reasons(caplog) == [reason]
    assert_nothing_started(gateway)


def test_env_default_tenant_must_also_be_allow_listed(gateway, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("VOICE_TENANT_ID", OTHER_TENANT)
    rejected(gateway, lambda ws: ws.send_text(media_start(tenant=None)))

    assert rejection_reasons(caplog) == ["tenant_not_allowed"]
    assert_nothing_started(gateway)


def test_authentication_timeout_closes_an_idle_connection(gateway, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("VOICE_MEDIA_AUTH_TIMEOUT_SECONDS", "0.3")
    started = time.monotonic()
    rejected(gateway, lambda ws: None)
    assert time.monotonic() - started < 5

    assert rejection_reasons(caplog) == ["auth_timeout"]
    assert_nothing_started(gateway)


def test_audio_and_other_events_before_media_start_do_not_extend_the_deadline(gateway, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("VOICE_MEDIA_AUTH_TIMEOUT_SECONDS", "0.5")

    def send(ws):
        for _ in range(5):
            ws.send_bytes(b"\xff" * 160)
            ws.send_text("not json")
            ws.send_text(json.dumps({"event": "MEDIA_BUFFERING_COMPLETED", "correlation_id": "x"}))
            time.sleep(0.05)

    rejected(gateway, send)

    assert rejection_reasons(caplog) == ["auth_timeout"]
    assert any(r.getMessage().startswith("audio_received_before_media_pipeline_ready") for r in caplog.records)
    assert_nothing_started(gateway)


def test_client_closing_before_media_start_starts_nothing(gateway, caplog):
    caplog.set_level(logging.DEBUG)

    def interact(ws):
        ws.send_bytes(b"\xff" * 160)
        ws.close()

    gateway.run(interact)
    time.sleep(0.2)

    assert rejection_reasons(caplog) == []
    assert_nothing_started(gateway)


@pytest.mark.parametrize(
    "payload",
    ["[]", f'["MEDIA_START", "{SECRET}"]', "42", '"MEDIA_START"', "null", "true"],
    ids=["empty-array", "array", "number", "string", "null", "boolean"],
)
def test_non_object_json_before_media_start_is_closed_with_1008_and_starts_nothing(gateway, caplog, payload):
    # Regression: a JSON value that is not an object used to raise
    # AttributeError in the handler (an unhandled exception, no 1008 close).
    caplog.set_level(logging.DEBUG)
    rejected(gateway, lambda ws: ws.send_text(payload))

    assert rejection_reasons(caplog) == ["non_object_control_message"]
    assert_nothing_started(gateway)
    assert gateway.post_call_clients() == []
    assert not any(r.getMessage().startswith("asterisk_websocket_error") for r in caplog.records)
    assert_secret_not_logged(caplog)


def test_non_object_json_after_authentication_closes_the_call_with_1008(gateway, caplog):
    caplog.set_level(logging.DEBUG)

    def interact(ws):
        ws.send_text(media_start())
        assert gateway.started.wait(5), "pipeline did not start"
        ws.send_text("[]")
        expect_policy_close(ws)

    gateway.run(interact)

    assert rejection_reasons(caplog) == []
    rejected_controls = [
        r.getMessage() for r in caplog.records if r.getMessage().startswith("asterisk_control_rejected")
    ]
    assert rejected_controls == [
        "asterisk_control_rejected reason=non_object_control_message channel_id=synthetic-channel"
    ]
    assert not any(r.getMessage().startswith("asterisk_websocket_error") for r in caplog.records)
    # Normal cleanup of an authenticated call still runs.
    assert len(gateway.post_call_clients()) == 1
    assert closes(gateway) == ["close"]
    assert_secret_not_logged(caplog)


@pytest.mark.parametrize(
    "send, reason",
    [
        (lambda ws: ws.send_text(media_start(token=WRONG_SECRET)), "invalid_media_token"),
        (lambda ws: ws.send_text(media_start(token=None)), "missing_media_token"),
        (lambda ws: ws.send_text(media_start(tenant=OTHER_TENANT)), "tenant_not_allowed"),
    ],
    ids=["wrong-token", "missing-token", "tenant-not-allowed"],
)
def test_rejected_connection_cleanup_completes(gateway, caplog, send, reason):
    # Regression: cleanup used to read tenant_id (assigned only after
    # authentication) and raised UnboundLocalError after the 1008 close.
    caplog.set_level(logging.DEBUG)
    with gateway.connect() as ws:  # a server-side error would raise here
        send(ws)
        expect_policy_close(ws)

    assert rejection_reasons(caplog) == [reason]
    assert gateway.post_call_clients() == []  # no dispatch without a verified tenant
    assert_nothing_started(gateway)
    assert not any(r.getMessage().startswith("asterisk_websocket_error") for r in caplog.records)
    assert_secret_not_logged(caplog)


# ============================================================
# Post-call processing (authenticated calls only)
# ============================================================

REFERENCE = "APT-SYNTHETIC-0001"


def arm_booking(gateway):
    gateway.armed.update({
        voice_main.POST_CALL_EVENT_KEY: voice_main.POST_CALL_BOOKING_CONFIRMED,
        voice_main.POST_CALL_APPOINTMENT_REFERENCE_KEY: REFERENCE,
    })


def sent_confirmations(gateway):
    return [
        kwargs
        for client in gateway.post_call_clients()
        for name, _, kwargs in client.calls
        if name == "send_booking_confirmation"
    ]


def closes(gateway):
    return [name for client in gateway.post_call_clients() for name, _, _ in client.calls if name == "close"]


@pytest.mark.parametrize("tenant_source", ["asterisk", "environment"])
def test_authenticated_call_dispatches_the_armed_booking_once_with_the_verified_tenant(
    gateway, monkeypatch, caplog, tenant_source
):
    caplog.set_level(logging.DEBUG)
    arm_booking(gateway)
    if tenant_source == "environment":
        monkeypatch.setenv("VOICE_TENANT_ID", TENANT)

    def interact(ws):
        ws.send_text(media_start(tenant=TENANT if tenant_source == "asterisk" else None))
        assert gateway.started.wait(5), "pipeline did not start"
        ws.close()

    gateway.run(interact)

    assert sent_confirmations(gateway) == [{"tenant_id": TENANT, "appointment_reference": REFERENCE}]
    assert len(gateway.post_call_clients()) == 1
    assert closes(gateway) == ["close"]


def test_authenticated_call_without_an_armed_event_sends_nothing(gateway, caplog):
    caplog.set_level(logging.DEBUG)

    def interact(ws):
        ws.send_text(media_start())
        assert gateway.started.wait(5), "pipeline did not start"
        ws.close()

    gateway.run(interact)

    assert len(gateway.post_call_clients()) == 1
    assert sent_confirmations(gateway) == []
    assert closes(gateway) == ["close"]


def test_failed_reauthentication_cannot_switch_the_post_call_tenant(gateway, monkeypatch, caplog):
    # A second MEDIA_START that fails authentication closes the call; the
    # booking made under the first, verified tenant keeps that tenant and the
    # unverified tenant from the rejected event is never used.
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("VOICE_ALLOWED_TENANT_IDS", f"{TENANT},{OTHER_TENANT}")
    arm_booking(gateway)

    def interact(ws):
        ws.send_text(media_start())
        assert gateway.started.wait(5), "pipeline did not start"
        ws.send_text(media_start(token=WRONG_SECRET, tenant=OTHER_TENANT))
        expect_policy_close(ws)

    gateway.run(interact)

    assert rejection_reasons(caplog) == ["invalid_media_token"]
    assert sent_confirmations(gateway) == [{"tenant_id": TENANT, "appointment_reference": REFERENCE}]
    assert_secret_not_logged(caplog)


def test_authenticated_call_failing_during_setup_still_cleans_up(gateway, caplog):
    # Authenticated, but MEDIA_START is malformed after the auth check, so the
    # handler raises before the pipeline exists. Cleanup must complete and the
    # original error must propagate unchanged (not an UnboundLocalError).
    caplog.set_level(logging.DEBUG)

    def interact(ws):
        ws.send_text(media_start(optimal_frame_size="not-a-number"))
        ws.receive_text()

    with pytest.raises(ValueError):
        gateway.run(interact)

    assert rejection_reasons(caplog) == []
    assert [r.kind for r in gateway.created if r.kind != "post_call"] == []
    assert sent_confirmations(gateway) == []
    assert closes(gateway) == ["close"]


# ============================================================
# Accepted
# ============================================================


def test_valid_media_start_creates_the_pipeline_only_after_authorization(gateway, caplog):
    caplog.set_level(logging.DEBUG)
    early_audio = b"\xfe" * 160

    def interact(ws):
        ws.send_bytes(early_audio)  # before MEDIA_START: dropped
        time.sleep(0.1)
        assert_nothing_started(gateway)

        ws.send_text(media_start())
        assert gateway.started.wait(5), "pipeline did not start"

        assert gateway.kinds() == ["deepgram_stt", "hamsa_stt", "vad"]
        assert gateway.consumers[0]["tenant_id"] == TENANT
        assert gateway.consumers[0]["channel_id"] == "synthetic-channel"
        ws.close()

    gateway.run(interact)

    assert gateway.server_error is None
    # The pre-authentication audio never reached a provider.
    for recorder in gateway.created:
        for _, args, kwargs in recorder.calls:
            assert early_audio not in (*args, *kwargs.values())
    assert any(r.getMessage().startswith("audio_received_before_media_pipeline_ready") for r in caplog.records)
    assert rejection_reasons(caplog) == []
    selected = [r.getMessage() for r in caplog.records if r.getMessage().startswith("voice_tenant_selected")]
    assert selected == [f"voice_tenant_selected channel_id=synthetic-channel tenant_id={TENANT} source=asterisk"]
    assert_secret_not_logged(caplog)


def test_env_default_tenant_is_used_when_asterisk_sends_none(gateway, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("VOICE_TENANT_ID", TENANT)

    def interact(ws):
        ws.send_text(media_start(tenant=None))
        assert gateway.started.wait(5), "pipeline did not start"
        assert gateway.consumers[0]["tenant_id"] == TENANT
        ws.close()

    gateway.run(interact)

    assert gateway.server_error is None
    selected = [r.getMessage() for r in caplog.records if r.getMessage().startswith("voice_tenant_selected")]
    assert selected == [f"voice_tenant_selected channel_id=synthetic-channel tenant_id={TENANT} source=environment"]
