"""Regression tests for the staging-safety review findings (F1-F6).

Offline only: fake values, temporary working directories, engine creation
and every connection path patched to fail if reached.
"""

import os
from pathlib import Path

import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.core.db_target import (
    EXAMPLE_PLACEHOLDER_DB_NAME,
    UnsafeDatabaseTargetError,
    ensure_safe_database_target,
)
from mcp_server.auth import MCPUnauthorizedError, authorize_mcp_request
from mcp_server.config import MCPSettings
from tests.test_staging_safety import (  # noqa: F401  fixtures
    AGENT_TOKEN,
    MCP_BACKEND_TOKEN,
    VOICE_TOKEN,
    _preflight,
    _valid_auth_env,
    clean_env,
    no_database,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
NEXT_AGENT_TOKEN = "fake-agent-to-mcp-next-token-0123456789ab"


def _staging(db_name):
    os.environ["APP_ENV"] = "staging"
    os.environ["DB_NAME"] = db_name
    return Settings(_env_file=None)


# ============================================================ A. guard (F1-F3)

REFUSED = {
    "": "non-empty",
    "   ": "non-empty",
    "\t": "non-empty",
    EXAMPLE_PLACEHOLDER_DB_NAME: "placeholder",
    " <SET-THE-APPROVED-DATABASE-NAME> ": "placeholder",
    "MedMind_Audit_Final2;DATABASE=MedMind_Booking_DB": "';', '=', '{' or '}'",
    "Audit;Final": "';', '=', '{' or '}'",
    "Audit=Final": "';', '=', '{' or '}'",
    "{MedMind_Audit_Final2}": "';', '=', '{' or '}'",
    "Audit}": "';', '=', '{' or '}'",
    "MeDmInD_BoOkInG_Db": "production database",
    " medmind_booking_db ": "production database",
}


@pytest.mark.parametrize("db_name, reason", REFUSED.items())
def test_staging_refuses_unsafe_db_names_without_echoing_them(clean_env, db_name, reason):
    with pytest.raises(UnsafeDatabaseTargetError) as error:
        ensure_safe_database_target(_staging(db_name))

    assert reason in str(error.value)
    if db_name.strip() and "booking" not in db_name.casefold():
        assert db_name.strip() not in str(error.value)


def test_staging_refuses_a_missing_db_name(clean_env):
    os.environ["APP_ENV"] = "staging"

    with pytest.raises(UnsafeDatabaseTargetError, match="explicitly"):
        ensure_safe_database_target(Settings(_env_file=None))


@pytest.mark.parametrize("db_name", ["MedMind_Audit_Final2", "  MedMind_Audit_Final2  ", "Other_Test_DB"])
def test_staging_accepts_an_explicit_safe_name(clean_env, db_name):
    ensure_safe_database_target(_staging(db_name))


@pytest.mark.parametrize("db_name", list(REFUSED) + ["MedMind_Booking_DB"])
@pytest.mark.parametrize("app_env", ["development", "production", ""])
def test_outside_staging_nothing_changes(clean_env, app_env, db_name):
    os.environ["APP_ENV"] = app_env
    os.environ["DB_NAME"] = db_name

    ensure_safe_database_target(Settings(_env_file=None))


def test_the_placeholder_matches_env_example():
    lines = (BACKEND_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()

    assert f"DB_NAME={EXAMPLE_PLACEHOLDER_DB_NAME}" in lines


@pytest.mark.asyncio
@pytest.mark.parametrize("db_name", ["", "   ", EXAMPLE_PLACEHOLDER_DB_NAME, "Audit;DATABASE=MedMind_Booking_DB"])
async def test_startup_stops_before_any_step_for_these_names(clean_env, monkeypatch, db_name):
    import app.main as backend_main

    called = []
    monkeypatch.setattr(backend_main, "database_settings", _staging(db_name))
    monkeypatch.setattr(backend_main, "load_dotenv", lambda **kwargs: called.append("load_dotenv"))
    monkeypatch.setattr(backend_main, "get_embedding_model", lambda: called.append("embedding"))
    monkeypatch.setattr(backend_main, "warm_db_pool", lambda: called.append("warm_db_pool"))

    with pytest.raises(UnsafeDatabaseTargetError):
        async with backend_main.lifespan(FastAPI()):
            pass

    assert called == []


@pytest.mark.parametrize("db_name", ["", EXAMPLE_PLACEHOLDER_DB_NAME, "a;b"])
def test_preflight_fails_these_names_in_staging(clean_env, no_database, db_name):
    report, output = _preflight(**_valid_auth_env(APP_ENV="staging", DB_NAME=db_name))

    assert report.failed
    assert "FAIL  database guard" in output


# ============================================================ B. MCP token rules (F4)


@pytest.mark.parametrize("next_value", ["short", "x" * 31, MCP_BACKEND_TOKEN])
def test_an_invalid_mcp_next_token_is_never_ok(clean_env, no_database, next_value):
    env = _valid_auth_env(MCP_SERVER_TOKEN_NEXT=next_value)

    report, output = _preflight(**env)

    # The MCP server itself rejects the agent's (valid, matching) token here...
    with pytest.raises(MCPUnauthorizedError):
        authorize_mcp_request({"x-medmind-service-token": AGENT_TOKEN}, settings=MCPSettings(_env_file=None))
    # ...so the preflight must not call that hop OK.
    assert report.failed
    assert "FAIL  Agent -> MCP: MCP would reject every token" in output
    assert "OK    Agent -> MCP" not in output
    for secret in (AGENT_TOKEN, MCP_BACKEND_TOKEN, next_value):
        if len(secret) >= 8:
            assert secret not in output


@pytest.mark.parametrize("next_value", ["", "   "])
def test_a_blank_mcp_next_token_means_no_rotation(clean_env, no_database, next_value):
    report, output = _preflight(**_valid_auth_env(MCP_SERVER_TOKEN_NEXT=next_value))

    assert not report.failed
    assert "OK    Agent -> MCP: sender and receiver tokens match" in output


def test_an_agent_using_a_valid_next_token_is_ok(clean_env, no_database):
    report, output = _preflight(**_valid_auth_env(MCP_SERVER_TOKEN_NEXT=NEXT_AGENT_TOKEN))
    assert "OK    Agent -> MCP" in output

    os.environ["MCP_SERVER_TOKEN"] = NEXT_AGENT_TOKEN  # agent switched; MCP current is still the old one
    os.environ["MCP_SERVER_TOKEN_NEXT"] = NEXT_AGENT_TOKEN
    report, output = _preflight()

    assert "OK    Agent -> MCP" in output
    assert NEXT_AGENT_TOKEN not in output


def test_the_mcp_inbound_token_equal_to_its_backend_token_fails(clean_env, no_database):
    report, output = _preflight(
        **_valid_auth_env(
            MEDMIND_SERVICE_CREDENTIALS=f"voice_gateway={VOICE_TOKEN}@clinic-001",
            MCP_SERVER_TOKEN=MCP_BACKEND_TOKEN,
        )
    )

    assert report.failed
    assert "FAIL  Agent -> MCP: MCP would reject every token" in output
    assert "FAIL  token separation" in output


# ============================================================ B. URLs (F5)

BAD_URLS = [
    "http://127.0.0.1:notaport/mcp",
    "http://127.0.0.1:99999/mcp",
    "ftp://127.0.0.1:9000/mcp",
    "http://:9000/mcp",
    "not a url",
]


@pytest.mark.parametrize("url", BAD_URLS)
def test_a_malformed_mcp_url_is_a_fail_line_not_a_crash(clean_env, no_database, url):
    report, output = _preflight(**_valid_auth_env(MCP_URL=url))

    assert report.failed
    assert "FAIL  MCP_URL (agent): not a valid http(s) URL" in output


@pytest.mark.parametrize("url", BAD_URLS)
def test_a_malformed_backend_base_url_is_a_fail_line_not_a_crash(clean_env, no_database, url):
    report, output = _preflight(**_valid_auth_env(MCP_BACKEND_BASE_URL=url))

    assert report.failed
    assert "FAIL  MCP_BACKEND_BASE_URL: not a valid http(s) URL" in output


def test_a_non_numeric_app_port_fails(clean_env, no_database):
    report, output = _preflight(**_valid_auth_env(APP_PORT="eighty"))

    assert report.failed
    assert "FAIL  APP_PORT: not a number" in output


def test_url_credentials_and_paths_are_never_printed(clean_env, no_database):
    report, output = _preflight(
        **_valid_auth_env(
            MCP_URL="http://fakeuser:fake-url-password@127.0.0.1:9000/mcp?key=fake-query-secret",
            MCP_BACKEND_BASE_URL="http://fakeuser:fake-url-password@127.0.0.1:8001",
        )
    )

    assert not report.failed
    assert "MCP_URL (agent): http://127.0.0.1:9000" in output
    for secret in ("fakeuser", "fake-url-password", "fake-query-secret"):
        assert secret not in output


def test_default_ports_are_inferred(clean_env, no_database):
    report, output = _preflight(**_valid_auth_env(MCP_BACKEND_BASE_URL="http://127.0.0.1", APP_PORT="80"))

    assert "MCP_BACKEND_BASE_URL: http://127.0.0.1:80" in output
    assert "differs from run_backend.py APP_PORT" not in output


# ============================================================ C. voice + tenants (F6)


@pytest.mark.parametrize("mode", ["audit", "enforce"])
def test_a_missing_voice_token_always_fails(clean_env, no_database, mode):
    report, output = _preflight(
        **_valid_auth_env(MEDMIND_SERVICE_TOKEN=None, BOOKING_SERVICE_AUTH_MODE=mode, MCP_AUTH_MODE=mode)
    )

    assert report.failed
    assert (
        "FAIL  voice gateway -> /ai/chat: not configured: MEDMIND_SERVICE_TOKEN "
        "(/ai/chat always requires the voice gateway's token)"
    ) in output


def test_ai_chat_really_has_no_audit_mode():
    # The FAIL above rests on this route contract.
    from app.api.routers import medmind_ai

    route = next(r for r in medmind_ai.router.routes if r.path == "/ai/chat")
    names = [d.call.__name__ for d in route.dependant.dependencies]
    assert names[0] == "require_gateway_service"  # token (always required) + gateway identity


def test_a_missing_voice_gateway_credential_fails(clean_env, no_database):
    report, output = _preflight(
        **_valid_auth_env(MEDMIND_SERVICE_CREDENTIALS=f"mcp_server={MCP_BACKEND_TOKEN}@clinic-001")
    )

    assert report.failed
    assert "FAIL  voice gateway -> /ai/chat: not configured: voice_gateway credential" in output


@pytest.mark.parametrize(
    "value, reason",
    [(None, "allowed_tenants_not_configured"), ("", "allowed_tenants_not_configured"),
     ("clinic-001,", "allowed_tenants_not_configured"), ("*", "allowed_tenants_invalid")],
)
def test_voice_tenant_list_uses_the_voice_gateways_own_rules(clean_env, no_database, value, reason):
    report, output = _preflight(**_valid_auth_env(VOICE_ALLOWED_TENANT_IDS=value))

    assert report.failed
    assert f"FAIL  VOICE_ALLOWED_TENANT_IDS: {reason}: the voice gateway rejects every call" in output


def test_voice_tenants_outside_the_voice_gateway_credential_fail(clean_env, no_database):
    report, output = _preflight(**_valid_auth_env(VOICE_ALLOWED_TENANT_IDS="clinic-001,clinic-002"))

    assert report.failed
    assert "FAIL  voice tenants: ['clinic-002'] are allowed by the voice gateway" in output


def test_a_default_voice_tenant_outside_the_list_warns(clean_env, no_database):
    report, output = _preflight(**_valid_auth_env(VOICE_TENANT_ID="clinic-009"))

    assert not report.failed
    assert "WARN  VOICE_TENANT_ID: not in VOICE_ALLOWED_TENANT_IDS" in output


def test_ai_tenants_missing_from_the_mcp_credential_fail(clean_env, no_database):
    report, output = _preflight(
        **_valid_auth_env(
            MEDMIND_SERVICE_CREDENTIALS=(
                f"voice_gateway={VOICE_TOKEN}@clinic-001,clinic-002;mcp_server={MCP_BACKEND_TOKEN}@clinic-001"
            ),
            VOICE_ALLOWED_TENANT_IDS="clinic-001,clinic-002",
        )
    )

    assert report.failed
    assert "FAIL  AI booking tenants: ['clinic-002'] are gateway tenants accepted on /ai/chat" in output


def test_aligned_tenants_pass(clean_env, no_database):
    report, output = _preflight(
        **_valid_auth_env(
            MEDMIND_SERVICE_CREDENTIALS=(
                f"voice_gateway={VOICE_TOKEN}@clinic-001,clinic-002;"
                f"mcp_server={MCP_BACKEND_TOKEN}@clinic-001,clinic-002,clinic-003"
            ),
            VOICE_ALLOWED_TENANT_IDS="clinic-001,clinic-002",
        )
    )

    assert not report.failed
    assert "OK    voice tenants" in output
    assert "OK    AI booking tenants" in output


def test_ai_tenant_check_is_skipped_when_mcp_sends_no_token(clean_env, no_database):
    report, output = _preflight(
        **_valid_auth_env(
            MEDMIND_SERVICE_CREDENTIALS=(
                f"voice_gateway={VOICE_TOKEN}@clinic-001,clinic-002;mcp_server={MCP_BACKEND_TOKEN}@clinic-001"
            ),
            VOICE_ALLOWED_TENANT_IDS="clinic-001,clinic-002",
            MCP_BACKEND_SERVICE_TOKEN=None,
        )
    )

    assert "AI booking tenants" not in output  # audit mode, no token sent: no tenant check at the backend
    assert not report.failed


def test_the_report_states_its_scope(clean_env, no_database):
    _, output = _preflight(**_valid_auth_env())

    assert "INFO  scope: this shell's environment and ./.env only" in output
    assert "are NOT verified" in output


# ============================================================ D. QWEN_PLANNER_WARMUP precedence


def test_a_shell_false_is_not_undone_by_dotenv_true(clean_env):
    (clean_env / ".env").write_text("QWEN_PLANNER_WARMUP=true\n", encoding="utf-8")
    os.environ["QWEN_PLANNER_WARMUP"] = "false"

    assert Settings().qwen_planner_warmup is False


def test_dotenv_alone_sets_qwen_warmup(clean_env):
    (clean_env / ".env").write_text("QWEN_PLANNER_WARMUP=false\n", encoding="utf-8")

    assert Settings().qwen_planner_warmup is False


def test_preflight_reports_the_effective_qwen_warmup(clean_env, no_database):
    (clean_env / ".env").write_text("QWEN_PLANNER_WARMUP=true\n", encoding="utf-8")

    _, output = _preflight(**_valid_auth_env(QWEN_PLANNER_WARMUP="false"))

    assert "OK    QWEN_PLANNER_WARMUP: false" in output
