"""Voice Gateway .env isolation in staging (voice_gateway/config.py).

With APP_ENV=staging in the PROCESS environment, load_environment() loads no
.env file, including Backend/.env, which voice_gateway.main and
voice_gateway.providers.hamsa_tts load at import time. Outside staging the
existing behavior (fill missing values, never override) is unchanged.

Every .env file here is a temporary file. The import tests run in a child
process that replaces load_dotenv with a counter and blocks outbound
networking before anything is imported, so no real .env is ever read.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

import voice_gateway.config as voice_config

BACKEND_ROOT = Path(__file__).resolve().parents[1]
FAKE_KEY = "VOICE_TEST_ONLY_DOTENV_VALUE"


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for key in ("APP_ENV", FAKE_KEY):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_env(directory, **values):
    path = directory / ".env"
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    return path


# ============================================================ staging_selected


@pytest.mark.parametrize("value, expected", [("staging", True), (" Staging ", True), ("STAGING", True),
                                             ("development", False), ("production", False), ("stage", False),
                                             ("", False), (None, False)])
def test_staging_is_selected_only_by_the_exact_process_value(clean_env, monkeypatch, value, expected):
    if value is not None:
        monkeypatch.setenv("APP_ENV", value)

    assert voice_config.staging_selected() is expected


def test_a_dotenv_file_cannot_select_staging(clean_env):
    _write_env(clean_env, APP_ENV="staging")

    assert voice_config.staging_selected() is False  # only the process environment counts


# ============================================================ load_environment


def test_staging_loads_nothing_from_a_dotenv_file(clean_env, monkeypatch):
    path = _write_env(clean_env, **{FAKE_KEY: "from-dotenv"})
    monkeypatch.setenv("APP_ENV", "staging")
    before = dict(os.environ)

    assert voice_config.load_environment(path) is False

    assert dict(os.environ) == before
    assert FAKE_KEY not in os.environ


def test_staging_never_calls_load_dotenv_for_the_default_file(clean_env, monkeypatch):
    calls = []
    monkeypatch.setattr(voice_config, "load_dotenv", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setenv("APP_ENV", "staging")

    assert voice_config.load_environment() is False
    assert calls == []


def test_outside_staging_a_given_file_is_still_loaded_without_override(clean_env, monkeypatch):
    # The fill-missing / never-override semantics are python-dotenv's
    # override=False; the contract here is that it is still requested.
    path = _write_env(clean_env, **{FAKE_KEY: "from-dotenv"})
    calls = []
    monkeypatch.setattr(voice_config, "load_dotenv", lambda **kwargs: calls.append(kwargs) or True)
    monkeypatch.setenv("APP_ENV", "production")

    assert voice_config.load_environment(path) is True
    assert calls == [{"dotenv_path": path, "override": False}]


def test_outside_staging_the_default_file_is_still_requested(clean_env, monkeypatch):
    calls = []
    monkeypatch.setattr(voice_config, "load_dotenv", lambda **kwargs: calls.append(kwargs) or False)

    voice_config.load_environment()

    assert calls == [{"dotenv_path": voice_config.ENV_FILE, "override": False}]


# ============================================================ import side effect

IMPORT_PROBE = """
import socket
import dotenv, dotenv.main

calls = []

def record(*args, **kwargs):
    calls.append(1)
    return False

def blocked(*args, **kwargs):
    raise OSError("network access blocked")

dotenv.load_dotenv = record
dotenv.main.load_dotenv = record
socket.getaddrinfo = blocked
socket.create_connection = blocked

import voice_gateway.main
import voice_gateway.providers.hamsa_tts

print("load_dotenv_calls=%d" % len(calls))
"""


def _import_in_child(tmp_path, app_env):
    env = {k: v for k, v in os.environ.items() if k not in ("APP_ENV", "PYTHONPATH")}
    env.update(PYTHONPATH=str(BACKEND_ROOT), PYTHONDONTWRITEBYTECODE="1")
    if app_env is not None:
        env["APP_ENV"] = app_env
    result = subprocess.run(
        [sys.executable, "-B", "-c", IMPORT_PROBE],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stderr.strip().splitlines()[-1:]
    line = [l for l in result.stdout.splitlines() if l.startswith("load_dotenv_calls=")][-1]
    return int(line.split("=")[1])


def test_importing_the_gateway_in_staging_loads_no_dotenv(tmp_path):
    assert _import_in_child(tmp_path, "staging") == 0


def test_importing_the_gateway_outside_staging_still_requests_dotenv(tmp_path):
    # Control: proves the probe sees the import-time load (blocked here).
    assert _import_in_child(tmp_path, None) >= 1
