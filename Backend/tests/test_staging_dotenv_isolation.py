"""Staging .env isolation: with APP_ENV=staging in the PROCESS environment the
backend, the agent and the preflight load no .env file.

Offline only. Every .env here is a temporary file with fake values; the real
Backend/.env is never read (the default-path loaders are replaced by
recorders). No startup, HTTP, SQL, AI or model initialization.
"""

import asyncio
import importlib
import os

import dotenv
import pytest
from fastapi import FastAPI

import run_backend
from app.core import preflight
from app.core.config import Settings, get_settings, staging_selected
from app.core.db_target import UnsafeDatabaseTargetError, ensure_safe_database_target
from tests.test_staging_safety import (  # noqa: F401  clean_env, no_database are fixtures
    _preflight,
    _valid_auth_env,
    clean_env,
    no_database,
)

FAKE_WEBHOOK = "https://fake-n8n.example.invalid/webhook/test-only"


@pytest.fixture
def fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _write_env(directory, **values):
    path = directory / ".env"
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    return path


# ============================================================ staging_selected


@pytest.mark.parametrize("value, expected", [("staging", True), (" Staging ", True), ("STAGING", True),
                                             ("development", False), ("production", False), ("stage", False),
                                             ("", False), (None, False)])
def test_staging_is_selected_only_by_the_exact_process_value(clean_env, value, expected):
    if value is not None:
        os.environ["APP_ENV"] = value

    assert staging_selected() is expected


def test_a_dotenv_file_cannot_select_staging(clean_env):
    _write_env(clean_env, APP_ENV="staging")

    assert staging_selected() is False  # only the process environment counts


# ============================================================ run_backend.py


def test_runner_loads_nothing_in_staging(clean_env):
    path = _write_env(clean_env, N8N_WHATSAPP_WEBHOOK_URL=FAKE_WEBHOOK, JWT_SECRET_KEY="dotenv-fake-jwt")
    os.environ["APP_ENV"] = "staging"
    os.environ["JWT_SECRET_KEY"] = "process-fake-jwt"
    before = dict(os.environ)

    assert run_backend.load_local_env(path) is False

    assert dict(os.environ) == before  # nothing populated, nothing overridden
    assert "N8N_WHATSAPP_WEBHOOK_URL" not in os.environ


def test_runner_still_fills_missing_values_outside_staging(clean_env):
    path = _write_env(clean_env, N8N_WHATSAPP_WEBHOOK_URL=FAKE_WEBHOOK, JWT_SECRET_KEY="dotenv-fake-jwt")
    os.environ["JWT_SECRET_KEY"] = "process-fake-jwt"

    assert run_backend.load_local_env(path) is True

    assert os.environ["N8N_WHATSAPP_WEBHOOK_URL"] == FAKE_WEBHOOK  # filled (previous behaviour)
    assert os.environ["JWT_SECRET_KEY"] == "process-fake-jwt"  # never overridden (no override)


def test_importing_the_runner_never_loads_dotenv(clean_env):
    calls = []
    original = dotenv.load_dotenv
    dotenv.load_dotenv = lambda *a, **k: calls.append((a, k)) or True
    try:
        importlib.reload(run_backend)  # executes the module, but not as __main__
    finally:
        dotenv.load_dotenv = original
        importlib.reload(run_backend)

    assert calls == []


# ============================================================ app/main.py startup


class _StartupReached(Exception):
    pass


def _run_startup_until_models(monkeypatch, *, staging):
    import app.main as backend_main

    calls = []
    if staging:
        os.environ["APP_ENV"] = "staging"
        db = Settings(_env_file=None, app_env="staging", db_name="MedMind_Audit_Final2")
    else:
        db = Settings(_env_file=None, app_env="development")
    monkeypatch.setattr(backend_main, "database_settings", db)
    monkeypatch.setattr(backend_main, "load_dotenv", lambda **kwargs: calls.append(kwargs))

    def stop():
        raise _StartupReached()

    monkeypatch.setattr(backend_main, "get_embedding_model", stop)

    async def go():
        async with backend_main.lifespan(FastAPI()):
            pass

    with pytest.raises(_StartupReached):
        asyncio.run(go())
    return calls


def test_startup_does_not_load_dotenv_in_staging(clean_env, monkeypatch):
    assert _run_startup_until_models(monkeypatch, staging=True) == []


def test_startup_still_loads_dotenv_with_override_outside_staging(clean_env, monkeypatch):
    assert _run_startup_until_models(monkeypatch, staging=False) == [{"override": True}]


# ============================================================ app/core/config.py


def test_settings_ignore_dotenv_in_staging(clean_env, fresh_settings):
    _write_env(clean_env, JWT_SECRET_KEY="dotenv-fake-jwt", QWEN_PLANNER_WARMUP="true",
               DB_NAME="FromDotenvDB", BOOKING_SERVICE_AUTH_MODE="enforce")
    os.environ.update(APP_ENV="staging", QWEN_PLANNER_WARMUP="false", DB_NAME="MedMind_Audit_Final2")

    settings = get_settings()

    assert settings.jwt_secret_key is None  # .env value ignored
    assert settings.qwen_planner_warmup is False  # process value respected
    assert settings.db_name == "MedMind_Audit_Final2"
    assert settings.booking_service_auth_mode == "audit"  # .env "enforce" ignored


def test_settings_use_explicit_process_values_in_staging(clean_env, fresh_settings):
    _write_env(clean_env, JWT_SECRET_KEY="dotenv-fake-jwt")
    os.environ.update(APP_ENV="staging", JWT_SECRET_KEY="process-fake-jwt")

    assert get_settings().jwt_secret_key.get_secret_value() == "process-fake-jwt"


def test_settings_still_fill_missing_values_from_dotenv_outside_staging(clean_env, fresh_settings):
    _write_env(clean_env, JWT_SECRET_KEY="dotenv-fake-jwt", QWEN_PLANNER_WARMUP="false")

    settings = get_settings()

    assert settings.jwt_secret_key.get_secret_value() == "dotenv-fake-jwt"
    assert settings.qwen_planner_warmup is False


def test_a_staging_db_name_only_in_dotenv_is_not_explicit(clean_env, fresh_settings):
    # In staging DB_NAME must come from the process environment.
    _write_env(clean_env, DB_NAME="MedMind_Audit_Final2")
    os.environ["APP_ENV"] = "staging"

    with pytest.raises(UnsafeDatabaseTargetError, match="explicitly"):
        ensure_safe_database_target(get_settings())


# ============================================================ agent/medmind/service.py


def _agent_create_dotenv_calls(monkeypatch):
    import medmind.service as agent_service

    calls = []
    monkeypatch.setattr(agent_service, "load_dotenv", lambda **kwargs: calls.append(kwargs))
    # Without an OpenAI key, create() stops right after the .env step: no
    # model, MCP client or network is ever constructed.
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is missing"):
        asyncio.run(agent_service.MedMindService.create(tenant_id="clinic-001"))
    return calls


def test_agent_does_not_load_dotenv_in_staging(clean_env, monkeypatch):
    os.environ["APP_ENV"] = " STAGING "

    assert _agent_create_dotenv_calls(monkeypatch) == []


def test_agent_still_loads_dotenv_outside_staging(clean_env, monkeypatch):
    assert _agent_create_dotenv_calls(monkeypatch) == [{"override": True}]


# ============================================================ preflight


def test_preflight_ignores_dotenv_in_staging_and_says_so(clean_env, no_database, monkeypatch):
    _write_env(clean_env, DB_NAME="MedMind_Booking_DB", MCP_SERVER_TOKEN="dotenv-fake-token-0123456789abcdef0123",
               N8N_WHATSAPP_WEBHOOK_URL=FAKE_WEBHOOK)

    def must_not_read(*args, **kwargs):
        raise AssertionError(".env must not be read in staging")

    monkeypatch.setattr(preflight, "dotenv_values", must_not_read)
    monkeypatch.setattr(preflight, "load_dotenv", must_not_read)

    report, output = _preflight(**_valid_auth_env(APP_ENV="staging", DB_NAME="MedMind_Audit_Final2"))

    assert not report.failed
    assert ("INFO  .env: ignored: APP_ENV=staging in the process environment, so no .env is loaded "
            "(start the MCP server from a directory without .env)") in output
    assert "DB_NAME: MedMind_Audit_Final2" in output
    assert "DB_NAME source: process environment" in output
    assert "N8N_WHATSAPP_WEBHOOK_URL" not in os.environ
    for secret in ("dotenv-fake-token-0123456789abcdef0123", FAKE_WEBHOOK):
        assert secret not in output


def test_preflight_still_reads_dotenv_outside_staging(clean_env, no_database):
    _write_env(clean_env, DB_NAME="FromDotenvDB")

    _, output = _preflight(**_valid_auth_env(DB_NAME=None))

    assert "DB_NAME: FromDotenvDB" in output
    assert "DB_NAME source: .env" in output
