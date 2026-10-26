"""Auth-chain setting precedence across the backend, the agent and MCP
(agent/medmind/env_precedence.py).

Every value is fake, every .env file is a temporary file, and os.environ is
restored after each test. No network, no database.
"""

import inspect
import logging
import os

import pytest
from dotenv import load_dotenv
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.config import Settings
from app.security.service_auth import authenticate_service_token
from mcp_server.auth import MCPUnauthorizedError, authorize_mcp_request
from mcp_server.config import MCPSettings
from medmind.env_precedence import AUTH_CHAIN_ENV_KEYS, keep_process_auth_settings
from medmind.service import _mcp_request_headers

SHELL_AGENT_TOKEN = "shell-agent-to-mcp-fake-token-0123456789ab"
DOTENV_AGENT_TOKEN = "dotenv-agent-to-mcp-fake-token-0123456789a"
BACKEND_TOKEN = "fake-mcp-to-backend-token-0123456789abcdef"
TENANT = "clinic-001"
TOKEN_HEADER = "X-MedMind-Service-Token"


@pytest.fixture
def env(tmp_path):
    """A clean process environment for the auth keys plus a temporary .env writer."""
    saved = dict(os.environ)
    for key in (*AUTH_CHAIN_ENV_KEYS, "OPENAI_API_KEY"):
        os.environ.pop(key, None)
    dotenv_file = tmp_path / ".env"

    def write(**values):
        dotenv_file.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
        return str(dotenv_file)

    yield write
    os.environ.clear()
    os.environ.update(saved)


def _startup(dotenv_path):
    """What the backend lifespan and the agent do: guarded load_dotenv(override=True)."""
    with keep_process_auth_settings():
        load_dotenv(dotenv_path, override=True)


def _views(dotenv_path):
    """The token each component would use after startup."""
    backend = Settings(_env_file=dotenv_path)
    mcp = MCPSettings(_env_file=dotenv_path)
    return SimpleViews(
        agent_sends=_mcp_request_headers(TENANT).get(TOKEN_HEADER),
        backend_check=backend.mcp_server_token.get_secret_value() if backend.mcp_server_token else None,
        mcp_accepts=mcp.server_token.get_secret_value() if mcp.server_token else None,
        backend=backend,
        mcp=mcp,
    )


class SimpleViews:
    def __init__(self, **values):
        self.__dict__.update(values)


# ============================================================ 1-3: precedence


def test_a_value_only_in_the_process_environment_is_used_everywhere(env):
    path = env(OPENAI_API_KEY="fake-openai")
    os.environ["MCP_SERVER_TOKEN"] = SHELL_AGENT_TOKEN

    _startup(path)
    views = _views(path)

    assert views.agent_sends == views.backend_check == views.mcp_accepts == SHELL_AGENT_TOKEN


def test_a_value_only_in_dotenv_is_used_everywhere(env):
    path = env(MCP_SERVER_TOKEN=DOTENV_AGENT_TOKEN)

    _startup(path)
    views = _views(path)

    assert views.agent_sends == views.backend_check == views.mcp_accepts == DOTENV_AGENT_TOKEN


@pytest.mark.parametrize("key", AUTH_CHAIN_ENV_KEYS)
def test_on_conflict_the_process_environment_wins_for_every_auth_key(env, key):
    path = env(**{key: "value-from-dotenv"})
    os.environ[key] = "value-from-shell"

    _startup(path)

    assert os.environ[key] == "value-from-shell"


def test_on_conflict_backend_agent_and_mcp_agree_on_the_shell_token(env, caplog):
    caplog.set_level(logging.DEBUG)
    path = env(MCP_SERVER_TOKEN=DOTENV_AGENT_TOKEN, MCP_AUTH_MODE="enforce")
    os.environ["MCP_SERVER_TOKEN"] = SHELL_AGENT_TOKEN
    os.environ["MCP_AUTH_MODE"] = "audit"

    _startup(path)
    views = _views(path)

    assert views.agent_sends == views.backend_check == views.mcp_accepts == SHELL_AGENT_TOKEN
    assert views.mcp.auth_mode == "audit" and os.environ["MCP_AUTH_MODE"] == "audit"
    # The conflict is visible, by key name only.
    assert "env_precedence_conflict key=MCP_SERVER_TOKEN" in caplog.text
    assert "env_precedence_conflict key=MCP_AUTH_MODE" in caplog.text
    for secret in (SHELL_AGENT_TOKEN, DOTENV_AGENT_TOKEN):
        assert secret not in caplog.text


def test_unrelated_settings_keep_the_existing_dotenv_override(env):
    path = env(OPENAI_API_KEY="fake-openai-from-dotenv")
    os.environ["OPENAI_API_KEY"] = "fake-openai-from-shell"

    _startup(path)

    assert os.environ["OPENAI_API_KEY"] == "fake-openai-from-dotenv"


def test_a_repeated_startup_keeps_the_first_value(env):
    path = env(MCP_SERVER_TOKEN=DOTENV_AGENT_TOKEN)
    _startup(path)  # backend lifespan: fills the unset key from .env

    env(MCP_SERVER_TOKEN=SHELL_AGENT_TOKEN)  # .env edited while running
    _startup(path)  # agent create: same value as the backend read

    assert os.environ["MCP_SERVER_TOKEN"] == DOTENV_AGENT_TOKEN


def test_the_guard_wraps_both_override_loads():
    import app.main as backend_main
    import medmind.service as agent_service

    for module in (backend_main, agent_service):
        source = inspect.getsource(module)
        assert source.count("load_dotenv(") == 1
        guarded = source.split("with keep_process_auth_settings():", 1)[1]
        assert guarded.lstrip().startswith("load_dotenv(")


# ============================================================ 4: missing / malformed


def test_enforce_without_any_agent_token_still_fails_fast(env):
    path = env(MCP_AUTH_MODE="enforce")

    _startup(path)

    with pytest.raises(RuntimeError, match="MCP_SERVER_TOKEN"):
        _mcp_request_headers(TENANT)


def test_an_empty_shell_token_is_not_replaced_by_dotenv(env):
    # Shell wins even when empty: the agent treats it as missing and fails in enforce.
    path = env(MCP_SERVER_TOKEN=DOTENV_AGENT_TOKEN)
    os.environ["MCP_SERVER_TOKEN"] = ""
    os.environ["MCP_AUTH_MODE"] = "enforce"

    _startup(path)

    with pytest.raises(RuntimeError, match="MCP_SERVER_TOKEN"):
        _mcp_request_headers(TENANT)


def test_a_malformed_mode_in_dotenv_still_stops_settings_loading(env):
    path = env(BOOKING_SERVICE_AUTH_MODE="off")

    _startup(path)

    with pytest.raises(ValidationError):
        Settings(_env_file=path)


def test_a_too_short_dotenv_token_makes_mcp_reject_everything(env):
    path = env(MCP_SERVER_TOKEN="too-short", MCP_AUTH_MODE="enforce")

    _startup(path)
    views = _views(path)

    for token in (None, "too-short", SHELL_AGENT_TOKEN):
        headers = {"x-tenant-id": TENANT}
        if token is not None:
            headers["x-medmind-service-token"] = token
        with pytest.raises(MCPUnauthorizedError):
            authorize_mcp_request(headers, settings=views.mcp)


def test_malformed_backend_credentials_from_dotenv_fail_closed(env):
    path = env(MEDMIND_SERVICE_CREDENTIALS="mcp_server=short@clinic-001")

    _startup(path)

    with pytest.raises(HTTPException) as error:
        authenticate_service_token(BACKEND_TOKEN, Settings(_env_file=path))
    assert error.value.status_code == 503


# ============================================================ 5: distinct hop tokens


def test_the_two_hop_tokens_stay_distinct_after_loading(env):
    path = env(
        MCP_SERVER_TOKEN=DOTENV_AGENT_TOKEN,
        MCP_BACKEND_SERVICE_TOKEN=BACKEND_TOKEN,
        MEDMIND_SERVICE_CREDENTIALS=f"mcp_server={BACKEND_TOKEN}@{TENANT}",
    )

    _startup(path)
    views = _views(path)

    backend_hop = views.mcp.backend_service_token.get_secret_value()
    assert views.agent_sends == DOTENV_AGENT_TOKEN != backend_hop == BACKEND_TOKEN
    assert authenticate_service_token(backend_hop, views.backend).name == "mcp_server"
    with pytest.raises(HTTPException) as error:
        authenticate_service_token(views.agent_sends, views.backend)
    assert error.value.status_code == 401  # the agent token is not a backend credential


def test_a_dotenv_value_cannot_make_the_agent_reuse_the_backend_token(env):
    # Before the guard the agent would send the .env value (here equal to the
    # backend token) while the backend checked the shell value.
    path = env(
        MCP_SERVER_TOKEN=BACKEND_TOKEN,
        MEDMIND_SERVICE_CREDENTIALS=f"mcp_server={BACKEND_TOKEN}@{TENANT}",
    )
    os.environ["MCP_SERVER_TOKEN"] = SHELL_AGENT_TOKEN

    _startup(path)
    views = _views(path)

    assert views.agent_sends == views.backend_check == SHELL_AGENT_TOKEN
    assert authenticate_service_token(BACKEND_TOKEN, views.backend).name == "mcp_server"


def test_a_shared_token_is_still_detected_on_the_value_actually_sent(env):
    path = env(MEDMIND_SERVICE_CREDENTIALS=f"mcp_server={BACKEND_TOKEN}@{TENANT}")
    os.environ["MCP_SERVER_TOKEN"] = BACKEND_TOKEN  # misconfigured: same token for both hops

    _startup(path)
    views = _views(path)

    assert views.agent_sends == views.backend_check == BACKEND_TOKEN
    with pytest.raises(HTTPException) as error:
        authenticate_service_token(BACKEND_TOKEN, views.backend)
    assert error.value.status_code == 503  # fail closed


# ============================================================ dotenv load failure


def _all_protected(prefix):
    return {key: f"{prefix}-{key.lower()}-fake-value-0123456789abcdef" for key in AUTH_CHAIN_ENV_KEYS}


def test_a_real_load_dotenv_error_propagates_and_leaves_protected_keys_unchanged(env, tmp_path):
    shell = _all_protected("shell")
    os.environ.update(shell)
    broken = tmp_path / "broken.env"
    broken.write_bytes(b"MCP_SERVER_TOKEN=\xff\xfe not utf-8\n")

    with pytest.raises(UnicodeDecodeError):
        with keep_process_auth_settings():
            load_dotenv(str(broken), override=True, encoding="utf-8")

    assert {key: os.environ[key] for key in AUTH_CHAIN_ENV_KEYS} == shell


def test_a_failure_after_a_partial_load_restores_every_protected_key(env, caplog):
    caplog.set_level(logging.DEBUG)
    present = dict(list(_all_protected("shell").items())[:6])  # 6 of the 8 set before
    absent = [key for key in AUTH_CHAIN_ENV_KEYS if key not in present]
    os.environ.update(present)
    os.environ["OPENAI_API_KEY"] = "fake-openai-from-shell"
    path = env(
        **_all_protected("dotenv"),
        OPENAI_API_KEY="fake-openai-from-dotenv",
    )

    class SimulatedLoadFailure(Exception):
        pass

    with pytest.raises(SimulatedLoadFailure):
        with keep_process_auth_settings():
            load_dotenv(path, override=True)  # every key now has its .env value
            raise SimulatedLoadFailure()

    # Keys set before the load: back to their process values.
    assert {key: os.environ[key] for key in present} == present
    # Keys not set before: keep what .env loaded (".env fills unset keys").
    assert {key: os.environ[key] for key in absent} == {
        key: _all_protected("dotenv")[key] for key in absent
    }
    # Non-auth keys: unchanged dotenv behaviour.
    assert os.environ["OPENAI_API_KEY"] == "fake-openai-from-dotenv"
    for value in (*present.values(), *_all_protected("dotenv").values()):
        assert value not in caplog.text


# ============================================================ agent MCP_AUTH_MODE / MCP_URL


@pytest.mark.parametrize("raw, mode", [(None, "audit"), ("audit", "audit"), (" Enforce ", "enforce"), ("ENFORCE", "enforce")])
def test_the_agent_accepts_only_the_documented_modes(env, raw, mode):
    from medmind.service import _mcp_auth_mode

    if raw is not None:
        os.environ["MCP_AUTH_MODE"] = raw

    assert _mcp_auth_mode() == mode


@pytest.mark.parametrize("raw", ["", "   ", "off", "enforced", "audit,enforce", "true"])
@pytest.mark.parametrize("token", [None, SHELL_AGENT_TOKEN])
def test_an_invalid_agent_mode_is_a_configuration_error_not_audit(env, raw, token):
    os.environ["MCP_AUTH_MODE"] = raw
    if token is not None:
        os.environ["MCP_SERVER_TOKEN"] = token

    with pytest.raises(RuntimeError, match="MCP_AUTH_MODE must be 'audit' or 'enforce'") as error:
        _mcp_request_headers(TENANT)

    if raw.strip():
        assert raw not in str(error.value)  # the value is not echoed
    # The MCP server refuses the same values.
    with pytest.raises(ValidationError):
        MCPSettings(_env_file=None, auth_mode=raw)


def test_an_empty_shell_mode_is_not_replaced_by_dotenv_and_fails_clearly(env):
    path = env(MCP_AUTH_MODE="audit")
    os.environ["MCP_AUTH_MODE"] = ""

    _startup(path)

    with pytest.raises(RuntimeError, match="MCP_AUTH_MODE"):
        _mcp_request_headers(TENANT)


def test_the_agent_mcp_url_defaults_when_absent(env):
    from medmind.service import DEFAULT_MCP_URL, _mcp_url

    assert _mcp_url() == DEFAULT_MCP_URL == "http://127.0.0.1:9000/mcp"


def test_the_agent_mcp_url_uses_a_set_value(env):
    from medmind.service import _mcp_url

    os.environ["MCP_URL"] = " http://localhost:9000/mcp "

    assert _mcp_url() == "http://localhost:9000/mcp"


@pytest.mark.parametrize("raw", ["", "   ", "\t"])
def test_an_empty_mcp_url_is_a_configuration_error(env, raw):
    from medmind.service import _mcp_url

    os.environ["MCP_URL"] = raw

    with pytest.raises(RuntimeError, match="MCP_URL is set but empty"):
        _mcp_url()


def test_an_empty_shell_mcp_url_is_not_replaced_by_dotenv_and_fails_clearly(env):
    from medmind.service import _mcp_url

    path = env(MCP_URL="http://127.0.0.1:9000/mcp")
    os.environ["MCP_URL"] = ""

    _startup(path)

    with pytest.raises(RuntimeError, match="MCP_URL is set but empty"):
        _mcp_url()


def test_the_agent_reads_mcp_url_and_mode_only_through_the_validators():
    import medmind.mcp_config as mcp_config
    import medmind.service as agent_service
    from medmind.service import MedMindService

    # One read of each, in the light config module the agent re-exports.
    config_source = inspect.getsource(mcp_config)
    assert config_source.count('"MCP_URL"') == 1 and config_source.count('"MCP_AUTH_MODE"') == 1
    service_source = inspect.getsource(agent_service)
    assert '"MCP_URL"' not in service_source and '"MCP_AUTH_MODE"' not in service_source
    assert agent_service._mcp_url is mcp_config._mcp_url
    assert agent_service._mcp_request_headers is mcp_config._mcp_request_headers
    create = inspect.getsource(MedMindService.create)
    assert "_mcp_url()" in create and "_mcp_request_headers(" in create
