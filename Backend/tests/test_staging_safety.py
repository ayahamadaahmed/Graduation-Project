"""Staging safety: database target guard, no-connection preflight and the
optional Qwen warm-up (app/core/db_target.py, app/core/preflight.py,
app/main.py).

Offline only. Database engine creation and every connection path are patched
to fail if reached; the Groq client is a fake. All values are fake.
"""

import inspect
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import sqlalchemy
import sqlalchemy.engine
from fastapi import FastAPI
from pydantic import ValidationError

from app.core import preflight
from app.core.config import Settings
from app.core.db_target import UnsafeDatabaseTargetError, ensure_safe_database_target

BACKEND_ROOT = Path(__file__).resolve().parents[1]

VOICE_TOKEN = "fake-voice-gateway-token-0123456789abcdef"
AGENT_TOKEN = "fake-agent-to-mcp-token-0123456789abcdef0"
MCP_BACKEND_TOKEN = "fake-mcp-to-backend-token-0123456789abcd"
DB_PASSWORD = "fake-db-password-not-real-0123"

PRESERVED = ("PATH", "SYSTEMROOT", "SystemRoot", "TEMP", "TMP", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE")


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """Empty configuration environment, cwd = an empty temp dir (no .env)."""
    saved = dict(os.environ)
    for key in list(os.environ):
        if key not in PRESERVED:
            del os.environ[key]
    monkeypatch.chdir(tmp_path)
    yield tmp_path
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture
def no_database(monkeypatch):
    """Any engine creation or connection attempt fails the test."""

    def refuse(*args, **kwargs):
        raise AssertionError("a database engine or connection was requested")

    monkeypatch.setattr(sqlalchemy, "create_engine", refuse)
    monkeypatch.setattr(sqlalchemy.engine, "create_engine", refuse)
    monkeypatch.setattr(sqlalchemy.engine.Engine, "connect", refuse)
    try:
        import pyodbc

        monkeypatch.setattr(pyodbc, "connect", refuse)
    except ImportError:  # pragma: no cover
        pass


def _staging_settings(**env):
    os.environ.update({"APP_ENV": "staging", **env})
    return Settings(_env_file=None)


def _valid_auth_env(**overrides):
    values = {
        "MEDMIND_SERVICE_CREDENTIALS": (
            f"voice_gateway={VOICE_TOKEN}@clinic-001;mcp_server={MCP_BACKEND_TOKEN}@clinic-001"
        ),
        "MEDMIND_SERVICE_TOKEN": VOICE_TOKEN,
        "VOICE_ALLOWED_TENANT_IDS": "clinic-001",
        "MCP_SERVER_TOKEN": AGENT_TOKEN,
        "MCP_BACKEND_SERVICE_TOKEN": MCP_BACKEND_TOKEN,
        "MCP_BACKEND_BASE_URL": "http://127.0.0.1:8001",
        "APP_PORT": "8001",
        "BOOKING_SERVICE_AUTH_MODE": "audit",
        "MCP_AUTH_MODE": "audit",
        "DB_PASSWORD": DB_PASSWORD,
    }
    values.update(overrides)
    return {k: v for k, v in values.items() if v is not None}


def _preflight(**env):
    os.environ.update(env)
    report = preflight.Report()
    preflight.run(report)
    return report, "\n".join(report.lines)


# ============================================================ A. database guard


def test_staging_without_an_explicit_db_name_is_refused(clean_env):
    settings = _staging_settings()

    assert settings.db_name == "MedMind_Booking_DB"  # the code default
    with pytest.raises(UnsafeDatabaseTargetError, match="DB_NAME to be set explicitly"):
        ensure_safe_database_target(settings)


@pytest.mark.parametrize("name", ["MedMind_Booking_DB", "medmind_booking_db", " MEDMIND_BOOKING_DB "])
def test_staging_refuses_the_production_database_even_when_explicit(clean_env, name):
    settings = _staging_settings(DB_NAME=name)

    assert "db_name" in settings.model_fields_set
    with pytest.raises(UnsafeDatabaseTargetError, match="production database"):
        ensure_safe_database_target(settings)


def test_staging_allows_the_explicit_audit_database_from_the_environment(clean_env):
    ensure_safe_database_target(_staging_settings(DB_NAME="MedMind_Audit_Final2"))


def test_staging_allows_the_explicit_audit_database_from_dotenv(clean_env):
    (clean_env / ".env").write_text("APP_ENV=staging\nDB_NAME=MedMind_Audit_Final2\n", encoding="utf-8")

    settings = Settings()  # reads ./.env like the backend

    assert "db_name" in settings.model_fields_set
    ensure_safe_database_target(settings)


@pytest.mark.parametrize("app_env", [" Staging ", "STAGING"])
def test_the_staging_value_is_matched_case_insensitively(clean_env, app_env):
    with pytest.raises(UnsafeDatabaseTargetError):
        ensure_safe_database_target(_staging_settings(APP_ENV=app_env))


@pytest.mark.parametrize("app_env", ["development", "production", "test", "stage", ""])
@pytest.mark.parametrize("db_name", [None, "MedMind_Booking_DB"])
def test_the_guard_does_nothing_outside_staging(clean_env, app_env, db_name):
    os.environ["APP_ENV"] = app_env
    if db_name:
        os.environ["DB_NAME"] = db_name

    ensure_safe_database_target(Settings(_env_file=None))


class _StartupReached(Exception):
    pass


@pytest.mark.asyncio
async def test_backend_startup_refuses_an_unsafe_staging_database_before_any_other_step(clean_env, monkeypatch):
    import app.main as backend_main

    called = []
    monkeypatch.setattr(backend_main, "database_settings", _staging_settings())
    monkeypatch.setattr(backend_main, "get_embedding_model", lambda: called.append("embedding"))
    monkeypatch.setattr(backend_main, "warm_db_pool", lambda: called.append("warm_db_pool"))
    monkeypatch.setattr(backend_main, "load_dotenv", lambda **kwargs: called.append("load_dotenv"))

    with pytest.raises(UnsafeDatabaseTargetError):
        async with backend_main.lifespan(FastAPI()):
            pass

    assert called == []  # no .env load, no model, no database connection


@pytest.mark.asyncio
async def test_backend_startup_continues_past_the_guard_for_the_audit_database(clean_env, monkeypatch):
    import app.main as backend_main

    called = []

    def stop_at_first_step():
        called.append("embedding")
        raise _StartupReached()

    monkeypatch.setattr(backend_main, "database_settings", _staging_settings(DB_NAME="MedMind_Audit_Final2"))
    monkeypatch.setattr(backend_main, "load_dotenv", lambda **kwargs: None)
    monkeypatch.setattr(backend_main, "get_embedding_model", stop_at_first_step)
    monkeypatch.setattr(backend_main, "warm_db_pool", lambda: called.append("warm_db_pool"))

    with pytest.raises(_StartupReached):
        async with backend_main.lifespan(FastAPI()):
            pass

    assert called == ["embedding"]  # passed the guard; stopped before warm_db_pool


def test_the_guard_runs_before_the_first_connection_in_startup():
    import app.main as backend_main

    source = inspect.getsource(backend_main.lifespan)
    assert source.index("ensure_safe_database_target(") < source.index("warm_db_pool()")
    # It checks the settings the engine was built from.
    from app.db import session

    assert backend_main.database_settings is session.settings


# ============================================================ B. preflight


def test_a_valid_staging_configuration_passes_without_printing_secrets(clean_env, no_database, capsys):
    os.environ.update(_valid_auth_env(APP_ENV="staging", DB_NAME="MedMind_Audit_Final2"))

    assert preflight.main() == 0

    output = capsys.readouterr().out
    assert "DB_NAME: MedMind_Audit_Final2" in output
    assert "DB_NAME source: process environment" in output
    assert "OK    database guard" in output
    assert "service mcp_server: booking-only, tenants ['clinic-001']" in output
    assert "service voice_gateway: gateway, tenants ['clinic-001']" in output
    for hop in ("voice gateway -> /ai/chat", "Agent -> MCP", "MCP -> backend"):
        assert f"OK    {hop}: sender and receiver tokens match" in output
    assert "OK    token separation" in output
    assert "RESULT: VALID" in output
    for secret in (VOICE_TOKEN, AGENT_TOKEN, MCP_BACKEND_TOKEN, DB_PASSWORD):
        assert secret not in output


@pytest.mark.parametrize(
    "process_value, dotenv_value, expected",
    [
        ("MedMind_Audit_Final2", None, "process environment"),
        (None, "MedMind_Audit_Final2", ".env"),
        ("MedMind_Audit_Final2", "Other_DB", "process environment (also in .env; process wins)"),
        (None, None, "default"),
    ],
)
def test_preflight_reports_where_db_name_comes_from(clean_env, no_database, process_value, dotenv_value, expected):
    if dotenv_value:
        (clean_env / ".env").write_text(f"DB_NAME={dotenv_value}\n", encoding="utf-8")
    if process_value:
        os.environ["DB_NAME"] = process_value

    _, output = _preflight()

    assert f"DB_NAME source: {expected}" in output
    assert f"DB_NAME: {process_value or dotenv_value or 'MedMind_Booking_DB'}" in output


def test_an_unidentifiable_source_is_reported_as_unknown():
    assert preflight._value_source("DB_NAME", set(), set(), is_set=True) == "unknown"
    assert preflight._value_source("DB_NAME", set(), set(), is_set=False) == "default"


@pytest.mark.parametrize("db_name", [None, "MedMind_Booking_DB"])
def test_preflight_fails_an_unsafe_staging_database(clean_env, no_database, db_name):
    env = _valid_auth_env(APP_ENV="staging", DB_NAME=db_name)

    report, output = _preflight(**env)

    assert report.failed
    assert "FAIL  database guard" in output


def test_preflight_warns_but_passes_production_name_outside_staging(clean_env, no_database):
    report, output = _preflight(**_valid_auth_env(APP_ENV="development", DB_NAME="MedMind_Booking_DB"))

    assert not report.failed
    assert "WARN  DB_NAME: is the production database" in output


@pytest.mark.parametrize(
    "key, field",
    [
        ("BOOKING_SERVICE_AUTH_MODE", "booking_service_auth_mode"),
        ("QWEN_PLANNER_WARMUP", "qwen_planner_warmup"),
    ],
)
def test_preflight_fails_an_invalid_backend_value_without_echoing_it(clean_env, no_database, key, field):
    leaked = "looks-like-a-secret-0123456789abcdef"
    report, output = _preflight(**_valid_auth_env(**{key: leaked}))

    assert report.failed
    assert f"invalid value for: {field}" in output
    assert leaked not in output


def test_preflight_fails_an_invalid_mcp_auth_mode_for_mcp_and_agent(clean_env, no_database):
    report, output = _preflight(**_valid_auth_env(MCP_AUTH_MODE="enforced"))

    assert report.failed
    assert "FAIL  MCP settings: invalid value for: auth_mode" in output
    assert "FAIL  MCP_AUTH_MODE (agent)" in output
    assert "enforced" not in output


def test_preflight_fails_an_empty_mcp_url(clean_env, no_database):
    report, output = _preflight(**_valid_auth_env(MCP_URL="  "))

    assert report.failed
    assert "FAIL  MCP_URL (agent): MCP_URL is set but empty." in output


def test_preflight_fails_a_sender_receiver_mismatch(clean_env, no_database):
    report, output = _preflight(
        **_valid_auth_env(MCP_BACKEND_SERVICE_TOKEN="fake-other-backend-token-0123456789abcdef")
    )

    assert report.failed
    assert "FAIL  MCP -> backend: MCP_BACKEND_SERVICE_TOKEN does not match mcp_server credential" in output


@pytest.mark.parametrize(
    "overrides, expected",
    [
        # Agent -> MCP token reused as the MCP -> backend token.
        ({"MCP_SERVER_TOKEN": MCP_BACKEND_TOKEN}, "FAIL  MEDMIND_SERVICE_CREDENTIALS"),
        # Voice token reused for Agent -> MCP.
        ({"MCP_SERVER_TOKEN": VOICE_TOKEN}, "FAIL  MEDMIND_SERVICE_CREDENTIALS"),
        # MCP inbound token equal to its backend token (MCP side only).
        (
            {
                "MEDMIND_SERVICE_CREDENTIALS": f"voice_gateway={VOICE_TOKEN}@clinic-001",
                "MCP_SERVER_TOKEN": MCP_BACKEND_TOKEN,
            },
            "FAIL  token separation",
        ),
    ],
)
def test_preflight_fails_a_token_shared_between_hops(clean_env, no_database, overrides, expected):
    report, output = _preflight(**_valid_auth_env(**overrides))

    assert report.failed
    assert expected in output
    for secret in (VOICE_TOKEN, AGENT_TOKEN, MCP_BACKEND_TOKEN):
        assert secret not in output


def test_preflight_fails_a_short_sender_token(clean_env, no_database):
    report, output = _preflight(**_valid_auth_env(MEDMIND_SERVICE_TOKEN="short-token"))

    assert report.failed
    assert "MEDMIND_SERVICE_TOKEN is shorter than 32 characters" in output
    assert "short-token" not in output


def test_missing_mcp_hop_tokens_warn_in_audit_mode(clean_env, no_database):
    report, output = _preflight(**_valid_auth_env(MCP_SERVER_TOKEN=None, MCP_BACKEND_SERVICE_TOKEN=None))

    assert not report.failed
    assert "WARN  Agent -> MCP: not configured: MCP_SERVER_TOKEN (agent) and MCP_SERVER_TOKEN (MCP)" in output
    assert "WARN  MCP -> backend: not configured: MCP_BACKEND_SERVICE_TOKEN" in output


def test_missing_tokens_fail_in_enforce_mode(clean_env, no_database):
    report, output = _preflight(
        **_valid_auth_env(
            MCP_SERVER_TOKEN=None,
            MCP_BACKEND_SERVICE_TOKEN=None,
            MCP_AUTH_MODE="enforce",
            BOOKING_SERVICE_AUTH_MODE="enforce",
        )
    )

    assert report.failed
    assert "FAIL  Agent -> MCP: not configured" in output
    assert "FAIL  MCP -> backend: not configured" in output


def test_malformed_credentials_fail_by_service_name_only(clean_env, no_database):
    report, output = _preflight(**_valid_auth_env(MEDMIND_SERVICE_CREDENTIALS=f"mcp_server={MCP_BACKEND_TOKEN}"))

    assert report.failed
    assert "FAIL  MEDMIND_SERVICE_CREDENTIALS: Service 'mcp_server' must list its allowed tenants" in output
    assert MCP_BACKEND_TOKEN not in output


def test_a_port_mismatch_is_reported(clean_env, no_database):
    report, output = _preflight(**_valid_auth_env(APP_PORT=None))

    assert not report.failed
    assert "WARN  MCP_BACKEND_BASE_URL: port 8001 differs from run_backend.py APP_PORT 8004" in output


def test_preflight_never_imports_the_engine_module():
    # A fresh interpreter: only what the preflight itself imports is loaded.
    env = {k: v for k, v in os.environ.items() if k in PRESERVED}
    env.update(PYTHONPATH=f"{BACKEND_ROOT / 'agent'}{os.pathsep}{BACKEND_ROOT}", APP_ENV="staging")
    code = (
        "import sys, app.core.preflight as p; code = p.main(); "
        "print('ENGINE_MODULE_LOADED', 'app.db.session' in sys.modules); "
        "print('SQLALCHEMY_LOADED', 'sqlalchemy' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=BACKEND_ROOT / "tests",  # no .env here
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert "ENGINE_MODULE_LOADED False" in result.stdout
    assert "SQLALCHEMY_LOADED False" in result.stdout
    assert "FAIL  database guard" in result.stdout  # staging without DB_NAME


# ============================================================ C. Qwen warm-up


@pytest.mark.parametrize("raw, expected", [(None, True), ("true", True), (" FALSE ", False), ("True", True)])
def test_qwen_warmup_setting_accepts_only_true_or_false(clean_env, raw, expected):
    if raw is not None:
        os.environ["QWEN_PLANNER_WARMUP"] = raw

    assert Settings(_env_file=None).qwen_planner_warmup is expected


@pytest.mark.parametrize("raw", ["", "  ", "1", "0", "yes", "no", "on", "off", "truee"])
def test_an_invalid_qwen_warmup_value_fails_clearly(clean_env, raw):
    os.environ["QWEN_PLANNER_WARMUP"] = raw

    with pytest.raises(ValidationError, match="must be 'true' or 'false'"):
        Settings(_env_file=None)


def _fake_planner(monkeypatch):
    from medmind.understanding.qwen_tool_planner import QwenToolPlanner

    planner = QwenToolPlanner(api_key="fake-groq-key-not-real")
    models_list = AsyncMock(return_value=[])
    monkeypatch.setattr(planner.client.models, "list", models_list)
    return planner, models_list


@pytest.mark.asyncio
async def test_disabled_warmup_never_calls_the_provider(monkeypatch, caplog):
    from app.main import warm_qwen_planner

    caplog.set_level("INFO")
    planner, models_list = _fake_planner(monkeypatch)
    client = planner.client

    await warm_qwen_planner(planner, enabled=False)

    models_list.assert_not_called()
    assert planner.client is client  # the planner itself is untouched
    assert "qwen_planner_warmup status=disabled" in caplog.text


@pytest.mark.asyncio
async def test_enabled_warmup_keeps_the_existing_behaviour(monkeypatch):
    from app.main import warm_qwen_planner

    planner, models_list = _fake_planner(monkeypatch)

    await warm_qwen_planner(planner, enabled=True)

    models_list.assert_awaited_once()
    assert planner._last_warmup_at is not None  # the planner's own warmup ran


def test_startup_uses_the_setting_for_the_warmup():
    import app.main as backend_main

    source = inspect.getsource(backend_main.lifespan)
    assert "await qwen_planner.warmup()" not in source
    assert "enabled=settings.qwen_planner_warmup" in source
