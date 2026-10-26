"""Provider messages, provider errors, exception messages and credential-bearing
URLs never reach the Voice Gateway logs, at any level.

Synthetic data and fake API keys only; fake sockets and clients only.
No network, no credentials, no providers.
"""

import ast
import asyncio
import io
import json
import logging
import os
import subprocess
import sys
import threading
import traceback
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest
import websockets
from starlette.testclient import TestClient
from websockets.protocol import State

import voice_gateway.main as voice_main
import voice_gateway.providers.hamsa_stt as hamsa_stt_module
from voice_gateway.log_safety import (
    OMITTED,
    SafeExceptionFilter,
    describe_error,
    describe_message,
    exception_fields,
    install_log_safety,
    safe_code,
)
from voice_gateway.medmind_client import session_fingerprint
from voice_gateway.providers.deepgram_stt import DeepgramStreamingSTT
from voice_gateway.providers.hamsa_stt import HamsaSTT

# Synthetic test data (not real people, identifiers or keys).
PATIENT_NAME = "زمردة قنديل"
LATIN_NAME = "Zumurruda"
NATIONAL_ID = "29001011234567"
PHONE = "01098765432"
FAKE_HAMSA_KEY = "fake-hamsa-key-0123456789abcdef"
FAKE_DEEPGRAM_KEY = "fake-deepgram-key-0123456789abcdef"

SENSITIVE = [
    PATIENT_NAME,
    *PATIENT_NAME.split(),
    LATIN_NAME,
    NATIONAL_ID,
    PHONE,
    FAKE_HAMSA_KEY,
    FAKE_DEEPGRAM_KEY,
]

SENSITIVE_MESSAGE = (
    f"failed for {PATIENT_NAME} {LATIN_NAME} id={NATIONAL_ID} "
    f"phone={PHONE} url=wss://example.invalid/ws?api_key={FAKE_HAMSA_KEY}"
)

VOICE_LOGGERS = [
    "medmind.voice_gateway",
    "medmind.voice_gateway.deepgram",
    "medmind.voice_gateway.hamsa",
    "medmind.voice_gateway.hamsa_tts",
    "medmind.voice_gateway.elevenlabs_tts",
    "medmind.voice_gateway.medmind_client",
    "medmind.voice_gateway.post_call",
]


# Same format string as logging.basicConfig in voice_gateway/main.py
# (checked by test_production_log_format_matches_main).
PRODUCTION_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

_formatted = io.StringIO()


@pytest.fixture(autouse=True)
def formatted_output():
    """A real StreamHandler with the production format on the root logger.

    Every assertion below also checks this final formatted text, which
    includes formatted tracebacks exactly as a deployed handler writes them.
    """
    global _formatted
    _formatted = io.StringIO()
    handler = logging.StreamHandler(_formatted)
    handler.setFormatter(logging.Formatter(PRODUCTION_FORMAT))
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield _formatted
    finally:
        root.removeHandler(handler)


def logged_text(caplog):
    """Everything a handler could write: final formatted output, message,
    raw args and traceback text."""
    parts = [_formatted.getvalue(), caplog.text]
    for record in caplog.records:
        parts.append(record.getMessage())
        parts.append(repr(record.args))
        if record.exc_text:
            parts.append(record.exc_text)
    return "\n".join(parts)


def assert_nothing_sensitive(caplog):
    if caplog.records:
        # The formatted handler really saw the records (not a vacuous pass).
        assert _formatted.getvalue(), "formatted handler captured nothing"
    text = logged_text(caplog)
    for value in SENSITIVE:
        assert value not in text, value


# ============================================================
# Helpers in voice_gateway.log_safety
# ============================================================


def test_safe_code_keeps_codes_and_drops_free_text_and_identifiers():
    assert safe_code(401) == "401"
    assert safe_code("1008") == "1008"
    assert safe_code("UNAUTHORIZED") == "UNAUTHORIZED"
    assert safe_code("RATE_LIMITED") == "RATE_LIMITED"
    for unsafe in (NATIONAL_ID, int(NATIONAL_ID), PHONE, PATIENT_NAME, LATIN_NAME,
                   SENSITIVE_MESSAGE, FAKE_HAMSA_KEY, "rate_limited", "ERR_123456",
                   "AB1", "zumurruda_qandil", True, None, -1, 100000):
        assert safe_code(unsafe) == "none", unsafe


def test_describe_message_never_includes_values():
    described = [
        describe_message({"type": "interim", "text": PATIENT_NAME, "id": NATIONAL_ID}),
        describe_message(int(NATIONAL_ID)),
        describe_message(NATIONAL_ID),
        describe_message([PHONE, PATIENT_NAME]),
        describe_message({PATIENT_NAME: PHONE}),
    ]
    joined = "\n".join(described)
    for value in SENSITIVE:
        assert value not in joined
    assert described[0] == "kind=object type=none fields=id,text,type"
    assert described[1] == "kind=int chars=14"


def test_describe_error_keeps_type_and_code_only():
    error = RuntimeError(SENSITIVE_MESSAGE)
    error.status_code = 401
    assert describe_error(error) == "error_type=RuntimeError error_code=401"
    assert describe_error(ValueError(SENSITIVE_MESSAGE)) == "error_type=ValueError error_code=none"


@pytest.mark.parametrize("name", VOICE_LOGGERS)
def test_every_voice_gateway_logger_has_the_safe_exception_filter(name):
    assert any(isinstance(f, SafeExceptionFilter) for f in logging.getLogger(name).filters)


def test_exception_tracebacks_keep_location_but_drop_messages(caplog):
    logger = install_log_safety(logging.getLogger("medmind.voice_gateway.test_log_safety"))
    caplog.set_level(logging.DEBUG)

    def inner():
        raise KeyError(SENSITIVE_MESSAGE)

    def outer():
        try:
            inner()
        except KeyError as exc:
            raise RuntimeError(SENSITIVE_MESSAGE) from exc

    try:
        outer()
    except RuntimeError:
        logger.exception("synthetic_failure")

    assert_nothing_sensitive(caplog)
    record = caplog.records[-1]
    assert "builtins.KeyError: " + OMITTED in record.exc_text
    assert "builtins.RuntimeError: " + OMITTED in record.exc_text
    assert "in inner" in record.exc_text and "in outer" in record.exc_text


# ============================================================
# Hamsa STT
# ============================================================


class FakeHamsaSocket:
    """Scripted Hamsa socket: returns each response once, in order."""

    state = State.OPEN

    def __init__(self, responses):
        self.responses = list(responses)

    async def send(self, data):
        return None

    async def recv(self):
        return self.responses.pop(0)

    async def close(self):
        return None


@pytest.fixture
def hamsa(monkeypatch):
    monkeypatch.setenv("HAMSA_API_KEY", FAKE_HAMSA_KEY)
    monkeypatch.setenv("STT_BENCHMARK_LOG_TRANSCRIPTS", "true")
    return HamsaSTT(sample_rate=24000, language="ar", model="s3")


@pytest.mark.asyncio
async def test_hamsa_non_object_unknown_and_error_messages_are_described_not_logged(hamsa, caplog):
    caplog.set_level(logging.DEBUG)
    hamsa._websocket = FakeHamsaSocket([
        NATIONAL_ID,  # bare digits parse as a JSON number (non-object branch)
        json.dumps({"type": "interim", "hypothesis": f"{PATIENT_NAME} {PHONE}"}),
        json.dumps({"type": "error", "message": SENSITIVE_MESSAGE, "code": "UNAUTHORIZED"}),
    ])

    result = await hamsa.transcribe(b"\x00\x00" * 160, sensitive=True)

    assert result == ""  # the error message still ends the request, as before
    assert_nothing_sensitive(caplog)
    messages = [r.getMessage() for r in caplog.records]
    assert "hamsa_message kind=int chars=14" in messages
    assert "hamsa_message kind=object type=none fields=hypothesis,type" in messages
    assert (
        "hamsa_error kind=object type=none fields=code,message,type error_code=UNAUTHORIZED"
        in messages
    )


@pytest.mark.parametrize("sensitive", [False, True])
def test_hamsa_benchmark_mode_logs_metadata_only(hamsa, caplog, sensitive):
    caplog.set_level(logging.DEBUG)
    transcript = NATIONAL_ID if sensitive else f"اسمي {PATIENT_NAME} ورقمي {PHONE}"

    hamsa._log_transcript(
        transcript=transcript,
        elapsed_ms=12.5,
        pcm_audio=b"\x00\x00" * 10,
        sensitive=sensitive,
        source="plain",
    )

    assert_nothing_sensitive(caplog)
    assert any(r.getMessage().startswith("hamsa_benchmark_final ") for r in caplog.records)


@pytest.mark.asyncio
async def test_hamsa_connect_error_quoting_the_url_is_withheld(hamsa, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)

    async def failing_connect(uri, **kwargs):
        assert FAKE_HAMSA_KEY in uri  # the key is in the query string
        raise websockets.exceptions.InvalidURI(uri, "synthetic failure")

    monkeypatch.setattr(hamsa_stt_module.websockets, "connect", failing_connect)

    with pytest.raises(RuntimeError) as exc_info:
        await hamsa.start()

    error = exc_info.value
    assert FAKE_HAMSA_KEY not in str(error)
    assert error.__cause__ is None and error.__suppress_context__
    assert "InvalidURI" in str(error)

    # Logged the way main.py would log it: still nothing sensitive.
    try:
        raise error
    except RuntimeError:
        logging.getLogger("medmind.voice_gateway").exception("synthetic_start_failed")
    assert_nothing_sensitive(caplog)


@pytest.mark.asyncio
async def test_hamsa_connect_errors_without_the_key_are_unchanged(hamsa, monkeypatch):
    async def failing_connect(uri, **kwargs):
        raise OSError("synthetic network failure")

    monkeypatch.setattr(hamsa_stt_module.websockets, "connect", failing_connect)

    with pytest.raises(OSError, match="synthetic network failure"):
        await hamsa.start()


def test_websockets_client_debug_handshake_line_is_not_logged(caplog):
    caplog.set_level(logging.DEBUG)
    assert logging.getLogger("websockets.client").level == logging.WARNING

    logging.getLogger("websockets.client").debug(
        "> GET %s HTTP/1.1", f"/v1/realtime/ws?api_key={FAKE_HAMSA_KEY}"
    )

    assert_nothing_sensitive(caplog)


# ============================================================
# Deepgram STT
# ============================================================


@pytest.fixture
def deepgram(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", FAKE_DEEPGRAM_KEY)
    monkeypatch.setenv("STT_BENCHMARK_LOG_TRANSCRIPTS", "true")
    received = []
    stt = DeepgramStreamingSTT(
        encoding="linear16",
        sample_rate=24000,
        on_transcript=lambda text, final: received.append((text, final)),
    )
    stt.received = received
    return stt


@pytest.mark.parametrize("transcript", [
    NATIONAL_ID,
    PHONE,
    f"اسمي {PATIENT_NAME} ورقمي {PHONE}",
])
def test_deepgram_benchmark_mode_logs_metadata_only(deepgram, caplog, transcript):
    caplog.set_level(logging.DEBUG)
    assert deepgram._benchmark_log_transcripts is True

    deepgram._final_parts = [transcript]
    deepgram._flush_final_transcript(reason="test")

    assert deepgram.received == [(transcript, True)]  # still delivered unchanged
    assert_nothing_sensitive(caplog)
    assert any(r.getMessage().startswith("deepgram_benchmark_final ") for r in caplog.records)


def test_deepgram_error_text_is_never_logged(deepgram, caplog):
    caplog.set_level(logging.DEBUG)

    class SyntheticDeepgramError(Exception):
        status_code = 401

    deepgram._handle_error(SyntheticDeepgramError(SENSITIVE_MESSAGE))
    deepgram._handle_error(SimpleNamespace(message=SENSITIVE_MESSAGE, code=1011))

    assert_nothing_sensitive(caplog)
    messages = [r.getMessage() for r in caplog.records]
    assert "deepgram_connection_error error_type=SyntheticDeepgramError error_code=401" in messages
    assert "deepgram_connection_error error_type=SimpleNamespace error_code=1011" in messages


# ============================================================
# main.py transcript consumer
# ============================================================


class FailingMedMind:
    def __init__(self):
        self.messages = []

    async def warmup(self, **kwargs):
        return None

    async def start_session(self, **kwargs):
        return "mms_test_session"

    async def chat(self, *, message, **kwargs):
        self.messages.append(message)
        raise RuntimeError(f"backend echoed: {message} {SENSITIVE_MESSAGE}")

    async def end_session(self, **kwargs):
        return None

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_consumer_exception_messages_quoting_caller_speech_are_not_logged(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    medmind = FailingMedMind()
    monkeypatch.setattr(voice_main, "MedMindClient", lambda: medmind)
    monkeypatch.setattr(voice_main, "create_tts_provider", lambda: ("fake", object()))

    queue = asyncio.Queue()
    await queue.put(f"اسمي {PATIENT_NAME} ورقمي {PHONE}")
    task = asyncio.create_task(
        voice_main.consume_final_transcripts(
            queue,
            websocket=None,
            channel_id="test-channel",
            tenant_id="test-tenant",
            audio_format="ulaw",
            conversation_state={"stage": "new"},
            media_send_lock=asyncio.Lock(),
        )
    )
    for _ in range(500):
        if medmind.messages and any(
            r.getMessage().startswith("voice_medmind_request_failed") for r in caplog.records
        ):
            break
        await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    failure = [r for r in caplog.records if r.getMessage().startswith("voice_medmind_request_failed")]
    assert len(failure) == 1
    line = failure[0].getMessage()
    # Explicit safe diagnostics: class, code, source location, stage and a
    # session fingerprint; no traceback, no message, no raw session id.
    assert failure[0].exc_info is None and failure[0].exc_text is None
    assert "error_type=RuntimeError error_code=none error_origin=test_voice_log_safety.py:" in line
    assert "stage=new" in line
    assert f"session={session_fingerprint('mms_test_session')}" in line
    assert "mms_test_session" not in logged_text(caplog)
    assert "Traceback" not in _formatted.getvalue()
    assert_nothing_sensitive(caplog)


# ============================================================
# Structural guard
# ============================================================

RAW_NAMES = {"exc", "exception", "error", "err", "e", "transcript", "text", "reply",
             "body", "message", "uri", "url"}


def test_no_voice_gateway_logger_call_passes_a_raw_value():
    root = Path(__file__).resolve().parents[1] / "voice_gateway"
    offending = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_bytes())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "logger"
            ):
                for arg in node.args[1:]:
                    if isinstance(arg, ast.Name) and arg.id in RAW_NAMES:
                        offending.append(f"{path.relative_to(root)}:{node.lineno}:{arg.id}")
    assert offending == []


def _logger_calls(tree):
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logger"
            and node.func.attr in {"debug", "info", "warning", "error", "exception", "critical", "log"}
        ):
            yield node


# Reviewed exceptions to the rule below: (event, variable) pairs whose
# f-string argument formats only that numeric timing ("12.34" or "none").
NUMERIC_FSTRING_ARGUMENTS = {
    ("hamsa_tts_stream_completed", "first_network_ms"),
    ("hamsa_tts_stream_completed", "first_output_ms"),
}


def _is_reviewed_numeric_fstring(event, arg):
    names = {n.id for n in ast.walk(arg) if isinstance(n, ast.Name)}
    calls = [n for n in ast.walk(arg) if isinstance(n, ast.Call)]
    return (
        len(names) == 1
        and not calls
        and (event, next(iter(names))) in NUMERIC_FSTRING_ARGUMENTS
    )


def test_no_logger_message_is_built_from_runtime_values():
    # The filter never touches record.msg / record.args, so the message must
    # be a literal and no argument may stringify a value (str/repr/format).
    # Arguments wrapped in bool()/len() are safe: they log a flag or a count.
    root = Path(__file__).resolve().parents[1] / "voice_gateway"
    offending = []
    for path in sorted(root.rglob("*.py")):
        for node in _logger_calls(ast.parse(path.read_bytes())):
            where = f"{path.relative_to(root)}:{node.lineno}"
            if node.args and not isinstance(node.args[0], ast.Constant):
                offending.append(f"{where}:non-literal message")
                continue
            event = node.args[0].value.split()[0] if node.args else ""
            for arg in node.args[1:]:
                if isinstance(arg, ast.Call) and getattr(arg.func, "id", None) in {"bool", "len"}:
                    continue
                if _is_reviewed_numeric_fstring(event, arg):
                    continue
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.JoinedStr):
                        offending.append(f"{where}:f-string argument")
                    if isinstance(sub, ast.Call) and (
                        getattr(sub.func, "id", None) in {"str", "repr", "format"}
                        or getattr(sub.func, "attr", None) == "format"
                    ):
                        offending.append(f"{where}:{ast.unparse(sub)[:40]}")
    assert offending == []


# Transcript-processing and provider code paths: explicit safe logging only.
EXPLICIT_MODULES = [
    "providers/hamsa_stt.py",
    "providers/deepgram_stt.py",
    "providers/hamsa_tts.py",
    "providers/elevenlabs_tts.py",
    "medmind_client.py",
]
EXPLICIT_MAIN_FUNCTIONS = {
    "consume_final_transcripts",
    "log_transcript_consumer_result",
    "start_deepgram_shadow",
    "finalize_deepgram_shadow_turn",
    "track_hamsa_drain_task",
    "hamsa_worker",
}
# Sites directly in asterisk_media (or its shutdown code) that handle
# provider- or transcript-sourced exceptions.
EXPLICIT_MAIN_EVENTS = {
    "deepgram_shadow_audio_failed",
    "voice_barge_in_failed",
    "barge_in_guard_shutdown_error",
    "digit_retry_timer_shutdown_error",
    "turn_finalize_grace_shutdown_error",
    "deepgram_fallback_shutdown_error",
    "hamsa_primary_shutdown_error",
}


def _attaches_traceback(node):
    return node.func.attr == "exception" or any(k.arg in {"exc_info", "stack_info"} for k in node.keywords)


def test_transcript_and_provider_paths_never_attach_tracebacks():
    root = Path(__file__).resolve().parents[1] / "voice_gateway"
    offending = []
    for name in EXPLICIT_MODULES:
        for node in _logger_calls(ast.parse((root / name).read_bytes())):
            if _attaches_traceback(node):
                offending.append(f"{name}:{node.lineno}")

    def visit(node, chain):
        for child in ast.iter_child_nodes(node):
            sub = chain + [child.name] if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else chain
            if (
                isinstance(child, ast.Call)
                and child in calls
                and set(sub) & EXPLICIT_MAIN_FUNCTIONS
                and _attaches_traceback(child)
            ):
                offending.append(f"main.py:{child.lineno}")
            visit(child, sub)

    main_tree = ast.parse((root / "main.py").read_bytes())
    calls = set(_logger_calls(main_tree))
    visit(main_tree, [])
    seen_events = set()
    for node in calls:
        event = node.args[0].value.split()[0]
        if event in EXPLICIT_MAIN_EVENTS:
            seen_events.add(event)
            passes_fields = any(
                isinstance(a, ast.Call) and getattr(a.func, "id", None) == "exception_fields"
                for a in node.args
            )
            if _attaches_traceback(node) or not passes_fields:
                offending.append(f"main.py:{node.lineno}:{event}")
    assert seen_events == EXPLICIT_MAIN_EVENTS
    assert offending == []


def test_every_logger_defined_in_voice_gateway_installs_the_filter():
    # Filters are not inherited by child loggers, so each module must install it.
    root = Path(__file__).resolve().parents[1] / "voice_gateway"
    names = []
    for path in sorted(root.rglob("*.py")):
        source = path.read_bytes()
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "attr", None) == "getLogger"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value.startswith("medmind.")
            ):
                names.append(node.args[0].value)
                assert b"install_log_safety(logger)" in source, path
    assert sorted(names) == sorted(VOICE_LOGGERS)


def test_production_log_format_matches_main():
    tree = ast.parse((Path(__file__).resolve().parents[1] / "voice_gateway" / "main.py").read_bytes())
    formats = [
        kw.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "basicConfig"
        for kw in node.keywords
        if kw.arg == "format"
    ]
    assert formats == [PRODUCTION_FORMAT]


# ============================================================
# Actual behavior and limits of SafeExceptionFilter
# ============================================================


def test_exception_fields_report_class_code_and_location_only():
    def failing():
        error = RuntimeError(SENSITIVE_MESSAGE)
        error.status_code = 503
        raise error

    try:
        failing()
    except RuntimeError:
        fields = exception_fields()

    assert fields.startswith("error_type=RuntimeError error_code=503 error_origin=test_voice_log_safety.py:")
    assert "<test_voice_log_safety.py:" in fields  # innermost frame first, then its caller
    for value in SENSITIVE:
        assert value not in fields
    assert exception_fields() == "error_type=none"  # outside an except block


def test_filter_cleans_exception_info_but_not_message_arguments(caplog):
    # Documents the limit: arguments pass through unchanged, which is why the
    # structural tests above forbid raw values as arguments.
    logger = install_log_safety(logging.getLogger("medmind.voice_gateway.test_filter_args"))
    caplog.set_level(logging.DEBUG)
    marker = "synthetic-argument-value-0001"

    try:
        raise ValueError(SENSITIVE_MESSAGE)
    except ValueError:
        logger.exception("synthetic_failure value=%s", marker)

    output = _formatted.getvalue()
    assert f"synthetic_failure value={marker}" in output
    assert "builtins.ValueError: " + OMITTED in output
    assert_nothing_sensitive(caplog)


@pytest.mark.parametrize(
    "name",
    ["medmind.voice_gateway.unfiltered_child", "gunicorn.error", "asyncio"],
)
def test_filter_does_not_cover_child_or_third_party_loggers(caplog, name):
    # Documents the limit: only loggers that call install_log_safety are
    # filtered (the Voice Gateway loggers and uvicorn.error). A child of a
    # filtered logger, asyncio's unhandled-task logger and other servers'
    # loggers (e.g. Gunicorn) are not.
    caplog.set_level(logging.DEBUG)
    try:
        raise ValueError(f"unfiltered {PHONE}")
    except ValueError:
        logging.getLogger(name).exception("third_party_style_failure")

    assert f"unfiltered {PHONE}" in _formatted.getvalue()


@pytest.mark.asyncio
async def test_hamsa_request_failure_logs_safe_fields_without_traceback(hamsa, caplog):
    caplog.set_level(logging.DEBUG)

    class ExplodingSocket(FakeHamsaSocket):
        async def recv(self):
            raise RuntimeError(SENSITIVE_MESSAGE)

    hamsa._websocket = ExplodingSocket([])
    result = await hamsa.transcribe(b"\x00\x00" * 160, sensitive=True)

    assert result == ""  # unchanged: failed request returns an empty transcript
    failures = [r for r in caplog.records if r.getMessage().startswith("hamsa_persistent_request_failed")]
    assert len(failures) == 1
    assert failures[0].exc_info is None and failures[0].exc_text is None
    assert "error_type=RuntimeError" in failures[0].getMessage()
    assert "error_origin=test_voice_log_safety.py:" in failures[0].getMessage()
    assert "Traceback" not in _formatted.getvalue()
    assert_nothing_sensitive(caplog)


def test_deepgram_close_failures_log_safe_fields_without_traceback(deepgram, caplog):
    caplog.set_level(logging.DEBUG)

    class ExplodingConnection:
        async def send_close_stream(self):
            raise RuntimeError(SENSITIVE_MESSAGE)

    class ExplodingContext:
        async def __aexit__(self, *args):
            raise RuntimeError(SENSITIVE_MESSAGE)

    deepgram._connection = ExplodingConnection()
    deepgram._context = ExplodingContext()
    asyncio.run(deepgram.close())

    messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("deepgram_close_stream_error error_type=RuntimeError") for m in messages)
    assert any(m.startswith("deepgram_context_close_error error_type=RuntimeError") for m in messages)
    assert "Traceback" not in _formatted.getvalue()
    assert_nothing_sensitive(caplog)


# ============================================================
# exception_fields: fail-safe, safe codes, deprecations, causes
# ============================================================


class _RaisingProperty(Exception):
    @property
    def status_code(self):
        raise RuntimeError(f"property failed {FAKE_HAMSA_KEY}")


class _DeprecatedProperty(Exception):
    @property
    def code(self):
        raise DeprecationWarning(f"deprecated {NATIONAL_ID}")


class _UnprintableException(Exception):
    def __str__(self):
        raise RuntimeError("str failed")


@pytest.mark.parametrize(
    "exc",
    [_RaisingProperty(SENSITIVE_MESSAGE), _DeprecatedProperty(SENSITIVE_MESSAGE), _UnprintableException()],
    ids=["property-raises", "property-raises-deprecation", "unprintable"],
)
def test_exception_fields_never_raise(exc):
    try:
        raise exc
    except Exception:
        fields = exception_fields()

    assert fields.startswith(f"error_type={type(exc).__name__} error_code=none error_origin=")
    for value in SENSITIVE:
        assert value not in fields


@pytest.mark.parametrize(
    "code",
    [FAKE_HAMSA_KEY, "zumurruda_qandil", "AHMED", "UNAUTHORIZED", int(NATIONAL_ID), NATIONAL_ID, PHONE, "401", 100000, -1, True],
)
def test_exception_attribute_codes_must_be_small_integers(code):
    error = RuntimeError(SENSITIVE_MESSAGE)
    error.code = code
    assert describe_error(error) == f"error_type=RuntimeError error_code=none"


def test_exception_attribute_integer_codes_are_kept():
    error = RuntimeError(SENSITIVE_MESSAGE)
    error.code = 4001
    assert describe_error(error) == "error_type=RuntimeError error_code=4001"


def test_provider_codes_accept_only_short_uppercase_tokens_or_small_numbers():
    accepted = {"UNAUTHORIZED": "UNAUTHORIZED", "RATE_LIMITED": "RATE_LIMITED", "401": "401", 1011: "1011"}
    for value, expected in accepted.items():
        assert safe_code(value) == expected
    for value in (FAKE_HAMSA_KEY, PATIENT_NAME, LATIN_NAME, NATIONAL_ID, PHONE, "ERR_2900101",
                  "Unauthorized", "rate_limited", "A" * 33, int(NATIONAL_ID)):
        assert safe_code(value) == "none", value
    # Known limit: an all-uppercase Latin word is accepted as a provider code.
    assert safe_code("AHMED") == "AHMED"


def test_connection_closed_code_comes_from_the_close_frame_without_deprecation():
    from websockets.exceptions import ConnectionClosed
    from websockets.frames import Close

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        closed = ConnectionClosed(Close(1011, f"reason {SENSITIVE_MESSAGE}"), None)
        no_frame = ConnectionClosed(None, None)
        assert describe_error(closed) == "error_type=ConnectionClosed error_code=1011"
        assert describe_error(no_frame) == "error_type=ConnectionClosed error_code=none"
        try:
            raise closed
        except ConnectionClosed:
            fields = exception_fields()
    assert "error_code=1011" in fields
    assert FAKE_HAMSA_KEY not in fields and NATIONAL_ID not in fields


def test_exception_fields_report_the_cause_class_only():
    try:
        try:
            raise KeyError(SENSITIVE_MESSAGE)
        except KeyError as inner:
            raise RuntimeError(SENSITIVE_MESSAGE) from inner
    except RuntimeError:
        explicit = exception_fields()

    try:
        try:
            raise ValueError(SENSITIVE_MESSAGE)
        except ValueError:
            raise OSError(SENSITIVE_MESSAGE)
    except OSError:
        implicit = exception_fields()

    try:
        try:
            raise ValueError(SENSITIVE_MESSAGE)
        except ValueError:
            raise OSError(SENSITIVE_MESSAGE) from None
    except OSError:
        suppressed = exception_fields()

    assert explicit.endswith(" cause_type=KeyError")
    assert implicit.endswith(" cause_type=ValueError")
    assert "cause_type" not in suppressed
    for fields in (explicit, implicit, suppressed):
        for value in SENSITIVE:
            assert value not in fields


def test_filter_never_raises_on_malformed_exception_info(caplog):
    logger = install_log_safety(logging.getLogger("medmind.voice_gateway.test_malformed"))
    caplog.set_level(logging.DEBUG)

    logger.error("synthetic_malformed", exc_info=(ValueError, SENSITIVE_MESSAGE, None))

    assert "synthetic_malformed" in _formatted.getvalue()
    assert_nothing_sensitive(caplog)


# ============================================================
# Hamsa URL/key protection: exception groups, notes, context
# ============================================================


def _group_with_key():
    return ExceptionGroup("connect failed", [OSError(f"wss://host/ws?api_key={FAKE_HAMSA_KEY}")])


def _notes_with_key():
    error = OSError("connect failed")
    error.add_note(f"uri=wss://host/ws?api_key={FAKE_HAMSA_KEY}")
    return error


def _context_with_key():
    try:
        raise ValueError(f"api_key={FAKE_HAMSA_KEY}")
    except ValueError:
        try:
            raise OSError("connect failed")
        except OSError as error:
            return error


@pytest.mark.asyncio
@pytest.mark.parametrize("make_error", [_group_with_key, _notes_with_key, _context_with_key],
                         ids=["exception-group", "notes", "implicit-context"])
async def test_hamsa_connect_errors_hiding_the_key_anywhere_are_withheld(hamsa, monkeypatch, caplog, make_error):
    caplog.set_level(logging.DEBUG)

    async def failing_connect(uri, **kwargs):
        raise make_error()

    monkeypatch.setattr(hamsa_stt_module.websockets, "connect", failing_connect)

    with pytest.raises(RuntimeError) as exc_info:
        await hamsa.start()

    error = exc_info.value
    assert error.__cause__ is None and error.__suppress_context__
    assert FAKE_HAMSA_KEY not in "".join(traceback.format_exception(error))


# ============================================================
# The six converted lifecycle sites (behavior where reachable offline)
# ============================================================

MEDIA_SECRET = "synthetic-media-secret-0123456789abcdef"


class _Done:
    def __await__(self):
        return iter(())


class _Fake:
    """Provider stand-in; close() raises a sensitive synthetic error."""

    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *args, **kwargs: _Done()

    async def close(self):
        raise RuntimeError(SENSITIVE_MESSAGE)


@pytest.fixture
def media_gateway(monkeypatch):
    monkeypatch.setenv("VOICE_MEDIA_SHARED_SECRET", MEDIA_SECRET)
    monkeypatch.setenv("VOICE_ALLOWED_TENANT_IDS", "test-tenant")
    monkeypatch.delenv("VOICE_TENANT_ID", raising=False)
    started = threading.Event()

    async def fake_consumer(queue, **kwargs):
        started.set()
        await asyncio.Event().wait()

    for name in ("HamsaSTT", "DeepgramStreamingSTT", "StreamingVAD", "PostCallClient", "MedMindClient"):
        monkeypatch.setattr(voice_main, name, _Fake)
    monkeypatch.setattr(voice_main, "create_tts_provider", lambda: ("fake", _Fake()))
    monkeypatch.setattr(voice_main, "consume_final_transcripts", fake_consumer)
    return SimpleNamespace(client=TestClient(voice_main.app), started=started)


def _media_start(**overrides):
    event = {
        "event": "MEDIA_START",
        "connection_id": "synthetic-connection",
        "channel_id": "synthetic-channel",
        "channel": "PJSIP/synthetic-0001",
        "format": "slin24",
        "optimal_frame_size": 960,
        "ptime": 20,
        "channel_variables": {"MEDMIND_MEDIA_TOKEN": MEDIA_SECRET, "MEDMIND_TENANT_ID": "test-tenant"},
    }
    event.update(overrides)
    return json.dumps(event)


def test_provider_shutdown_failures_log_safe_fields_in_formatted_output(media_gateway, caplog):
    caplog.set_level(logging.DEBUG)
    with media_gateway.client.websocket_connect("/asterisk/media", subprotocols=["media"]) as ws:
        ws.send_text(_media_start())
        assert media_gateway.started.wait(5), "pipeline did not start"
        ws.close()

    output = _formatted.getvalue()
    for event in ("deepgram_fallback_shutdown_error", "hamsa_primary_shutdown_error"):
        lines = [line for line in output.splitlines() if f"| {event} " in line]
        assert len(lines) == 1, event
        assert "error_type=RuntimeError error_code=none error_origin=test_voice_log_safety.py:" in lines[0]
        assert "stage=new" in lines[0]
    assert "Traceback" not in output
    assert MEDIA_SECRET not in output
    assert_nothing_sensitive(caplog)


# ============================================================
# ASGI server path (asterisk_websocket_error re-raises)
# ============================================================


def _escape_through_the_endpoint(media_gateway):
    """Send a MEDIA_START whose optimal_frame_size makes int() raise with a
    synthetic national ID in its message; return the exception that leaves
    the endpoint (what the ASGI server would receive)."""

    with pytest.raises(Exception) as exc_info:
        with media_gateway.client.websocket_connect("/asterisk/media", subprotocols=["media"]) as ws:
            ws.send_text(_media_start(optimal_frame_size=f"x{NATIONAL_ID}"))
            ws.receive_text()
    return exc_info.value


def test_gateway_logs_stay_safe_when_an_exception_escapes_the_endpoint(media_gateway, caplog):
    caplog.set_level(logging.DEBUG)
    escaped = _escape_through_the_endpoint(media_gateway)

    output = _formatted.getvalue()
    assert "asterisk_websocket_error" in output
    assert "builtins.ValueError: " + OMITTED in output
    assert_nothing_sensitive(caplog)
    # The exception that reaches the ASGI server still carries the text.
    assert NATIONAL_ID in "".join(traceback.format_exception(escaped))


UVICORN_ERROR = "uvicorn.error"


def _uvicorn_style_exception_log():
    """Raise and log exactly the way uvicorn does for an escaping ASGI error
    (uvicorn/protocols/websockets/websockets_impl.py:252)."""

    def asgi_application():
        raise RuntimeError(
            f"handler failed id={NATIONAL_ID} url=wss://host/ws?api_key={FAKE_HAMSA_KEY}"
        )

    try:
        asgi_application()
    except Exception as exc:
        logging.getLogger(UVICORN_ERROR).exception("Exception in ASGI application\n")
        return exc


def test_uvicorn_error_logger_has_the_filter():
    assert any(isinstance(f, SafeExceptionFilter) for f in logging.getLogger(UVICORN_ERROR).filters)


def test_uvicorn_exception_log_omits_messages_but_keeps_types_and_locations(caplog):
    caplog.set_level(logging.DEBUG)
    _uvicorn_style_exception_log()

    output = _formatted.getvalue()
    assert "Exception in ASGI application" in output
    assert "builtins.RuntimeError: " + OMITTED in output
    assert 'test_voice_log_safety.py", line ' in output and "in asgi_application" in output
    assert_nothing_sensitive(caplog)


def test_uvicorn_logging_leaves_the_exception_and_other_records_untouched(caplog):
    caplog.set_level(logging.DEBUG)
    uvicorn_logger = logging.getLogger(UVICORN_ERROR)
    before = (uvicorn_logger.level, uvicorn_logger.propagate, list(uvicorn_logger.handlers))

    exc = _uvicorn_style_exception_log()
    uvicorn_logger.error("Invalid HTTP request received.")
    uvicorn_logger.error("ASGI callable should return None, but returned '%s'.", "synthetic-result")

    # The exception object itself is not modified: only the log record is.
    assert NATIONAL_ID in str(exc) and FAKE_HAMSA_KEY in str(exc)
    assert exc.__traceback__ is not None
    # Nothing is suppressed, and plain error messages keep their text and arguments.
    records = [r for r in caplog.records if r.name == UVICORN_ERROR]
    assert len(records) == 3
    output = _formatted.getvalue()
    assert "Invalid HTTP request received." in output
    assert "ASGI callable should return None, but returned 'synthetic-result'." in output
    assert (uvicorn_logger.level, uvicorn_logger.propagate, list(uvicorn_logger.handlers)) == before


def test_exception_escaping_the_endpoint_is_safe_in_the_uvicorn_log(media_gateway, caplog):
    caplog.set_level(logging.DEBUG)
    escaped = _escape_through_the_endpoint(media_gateway)

    # Propagation is unchanged: the exception still leaves the endpoint with its text.
    assert NATIONAL_ID in "".join(traceback.format_exception(escaped))

    try:
        raise escaped
    except Exception:
        logging.getLogger(UVICORN_ERROR).exception("Exception in ASGI application\n")

    output = _formatted.getvalue()
    assert "builtins.ValueError: " + OMITTED in output
    assert 'main.py", line ' in output
    assert NATIONAL_ID not in output
    assert_nothing_sensitive(caplog)


# Runs in a separate interpreter so uvicorn's real logging configuration
# (dictConfig of uvicorn.config.LOGGING_CONFIG, handler on stderr) is applied
# exactly as in a deployment, without starting a server or opening a socket.
_DEPLOYMENT_SCRIPT = r"""
import logging, sys
sys.path.insert(0, ".")
order = sys.argv[1]
import uvicorn
if order == "uvicorn-cli":
    # uvicorn voice_gateway.main:app : Config() configures logging, load() imports the app.
    config = uvicorn.Config("voice_gateway.main:app")
    config.load()
else:
    # app imported first, then uvicorn.run(app): logging configured afterwards.
    import voice_gateway.main as app_module
    config = uvicorn.Config(app_module.app)
    config.load()
try:
    raise RuntimeError("handler failed id=%s url=wss://host/ws?api_key=%s" % (sys.argv[2], sys.argv[3]))
except RuntimeError:
    logging.getLogger("uvicorn.error").exception("Exception in ASGI application\n")
logging.getLogger("uvicorn.error").error("plain uvicorn error stays visible")
"""


@pytest.mark.parametrize("order", ["uvicorn-cli", "app-imported-first"])
def test_filter_survives_uvicorn_logging_configuration(order):
    backend = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if not k.endswith(("_API_KEY", "_TOKEN", "_SECRET", "_CREDENTIALS"))}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-B", "-c", _DEPLOYMENT_SCRIPT, order, NATIONAL_ID, FAKE_HAMSA_KEY],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output[-2000:]
    assert "Exception in ASGI application" in output
    assert "builtins.RuntimeError: " + OMITTED in output
    assert "plain uvicorn error stays visible" in output
    assert NATIONAL_ID not in output
    assert FAKE_HAMSA_KEY not in output
