"""No-connection configuration preflight.

    python -m app.core.preflight        (run from Backend/, like the services)

Reads the configuration exactly as the backend, the agent and the MCP server
would from this directory, and checks it WITHOUT creating a database engine,
opening a connection or calling any service:

- APP_ENV, DB_SERVER, DB_NAME and where DB_NAME comes from;
- the staging database guard (app/core/db_target.py);
- BOOKING_SERVICE_AUTH_MODE, MCP_AUTH_MODE (MCP and agent view),
  QWEN_PLANNER_WARMUP and MCP_URL;
- trusted services and their tenants (names only, never tokens);
- that the voice-gateway, Agent -> MCP and MCP -> Backend tokens are set,
  long enough, matched between sender and receiver (with the receivers' own
  rules, rotation included), and distinct;
- the gateway caller policy: /ai/*, post-call and diagnostic-attachment
  routes accept gateway services only (every configured service except the
  booking-only mcp_server), so the voice gateway must not send the
  mcp_server token;
- tenant alignment along the AI path: VOICE_ALLOWED_TENANT_IDS must be in the
  voice_gateway credential, and every gateway service's tenant (the tenants
  /ai/chat accepts) must be in the mcp_server credential when MCP sends its
  token.

Scope: everything is read from THIS process's environment and ./.env. The
backend reads the same when started here; the voice gateway reads
Backend/.env; the MCP server reads ./.env of the directory it starts in. A
component started with a different environment or .env is not verified.

Prints no password, key, token or full credential string. Exit code 0 when
the configuration is valid, 1 otherwise (warnings do not fail).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values, load_dotenv
from pydantic import ValidationError

ENV_FILE = Path(".env")  # the settings read .env from the current directory
MIN_TOKEN_LENGTH = 32  # same minimum as the backend and MCP checks
DEFAULT_RUN_BACKEND_PORT = 8004  # run_backend.py APP_PORT default


@dataclass
class Report:
    lines: list[str] = field(default_factory=list)
    failed: bool = False

    def info(self, label: str, detail: str) -> None:
        self.lines.append(f"  INFO  {label}: {detail}")

    def ok(self, label: str, detail: str = "ok") -> None:
        self.lines.append(f"  OK    {label}: {detail}")

    def warn(self, label: str, detail: str) -> None:
        self.lines.append(f"  WARN  {label}: {detail}")

    def fail(self, label: str, detail: str) -> None:
        self.failed = True
        self.lines.append(f"  FAIL  {label}: {detail}")


def _invalid_fields(error: ValidationError) -> str:
    # Field names only: pydantic messages can echo the rejected value.
    return ", ".join(sorted({str(item["loc"][0]) for item in error.errors() if item.get("loc")}))


def _value_source(name: str, process_keys: set[str], dotenv_keys: set[str], is_set: bool) -> str:
    in_process = name in process_keys
    in_dotenv = name in dotenv_keys
    if in_process:
        return "process environment" + (" (also in .env; process wins)" if in_dotenv else "")
    if in_dotenv:
        return ".env"
    return "unknown" if is_set else "default"


def _secret(value) -> str | None:
    if value is None:
        return None
    text = value.get_secret_value() if hasattr(value, "get_secret_value") else str(value)
    return text.strip() or None


DEFAULT_PORTS = {"http": 80, "https": 443}


def _parse_http_url(url: str) -> tuple[str, int] | None:
    """(scheme://host:port, port) for a valid http(s) URL, else None.

    Only scheme, host and port are ever shown: never a user:password part,
    path or query.
    """
    try:
        parts = urlsplit(url.strip())
        port = parts.port  # raises ValueError for a non-numeric/out-of-range port
    except ValueError:
        return None
    if parts.scheme not in DEFAULT_PORTS or not parts.hostname:
        return None
    port = port or DEFAULT_PORTS[parts.scheme]
    return f"{parts.scheme}://{parts.hostname}:{port}", port


def run(report: Report) -> None:
    from app.core.config import Settings, staging_selected
    from app.core.db_target import PRODUCTION_DB_NAME, UnsafeDatabaseTargetError, ensure_safe_database_target, is_staging
    from app.security.service_credentials import (
        BOOKING_SERVICE_NAMES,
        ServiceCredentialsConfigError,
        load_service_credentials,
    )
    from mcp_server.auth import _expected_tokens
    from mcp_server.config import MCPSettings
    from voice_gateway.media_auth import MediaAuthError, _allowed_tenants

    report.info(
        "scope",
        "this shell's environment and ./.env only; MCP, voice gateway or backend "
        "processes started with a different environment or .env are NOT verified",
    )

    # Sources first, before .env is applied below.
    process_keys = {key.upper() for key in os.environ}
    staging = staging_selected()  # from the process environment only

    if staging:
        # The backend loads no .env in staging (app/core/config.py
        # staging_selected); mirror that and do not read the file at all.
        dotenv_keys = set()
        report.info(
            ".env",
            "ignored: APP_ENV=staging in the process environment, so no .env is loaded "
            "(start the MCP server from a directory without .env)",
        )
    else:
        dotenv_keys = {key.upper() for key in (dotenv_values(ENV_FILE) if ENV_FILE.is_file() else {})}
        report.info(".env", f"{ENV_FILE.resolve()} ({'found' if ENV_FILE.is_file() else 'not found'})")

        # The running backend fills unset values from .env (run_backend.py) and the
        # agent keeps process values for the auth keys (medmind/env_precedence.py):
        # process environment first, .env for the rest. Mirror that.
        if ENV_FILE.is_file():
            load_dotenv(ENV_FILE, override=False)

    # ---------------------------------------------------------------- backend
    try:
        settings = Settings(_env_file=None) if staging else Settings()
    except ValidationError as error:
        report.fail("backend settings", f"invalid value for: {_invalid_fields(error)}")
        return

    report.info("APP_ENV", settings.app_env)
    report.info("DB_SERVER", settings.db_server)
    report.info("DB_NAME", settings.db_name)
    report.info(
        "DB_NAME source",
        _value_source("DB_NAME", process_keys, dotenv_keys, "db_name" in settings.model_fields_set),
    )

    try:
        ensure_safe_database_target(settings)
    except UnsafeDatabaseTargetError as error:
        report.fail("database guard", str(error))
    else:
        if is_staging(settings):
            report.ok("database guard", "explicit, non-production database for staging")
        else:
            report.info("database guard", f"not applied (APP_ENV={settings.app_env})")
            if settings.db_name.strip().casefold() == PRODUCTION_DB_NAME.casefold():
                report.warn("DB_NAME", f"is the production database {PRODUCTION_DB_NAME}")

    report.ok("BOOKING_SERVICE_AUTH_MODE", settings.booking_service_auth_mode)
    report.ok("QWEN_PLANNER_WARMUP", str(settings.qwen_planner_warmup).lower())
    if settings.booking_service_auth_mode == "audit":
        report.warn("BOOKING_SERVICE_AUTH_MODE", "audit: booking/patient requests without a token are served")

    try:
        credentials = load_service_credentials(settings)
    except ServiceCredentialsConfigError as error:
        credentials = None
        report.fail("MEDMIND_SERVICE_CREDENTIALS", str(error))  # names services, never tokens
    else:
        if credentials is None:
            report.warn("MEDMIND_SERVICE_CREDENTIALS", "not set: every trusted-service route answers 503")
        for name, credential in sorted((credentials or {}).items()):
            rotation = ", rotation token set" if credential.next_token else ""
            role = "booking-only" if name in BOOKING_SERVICE_NAMES else "gateway"
            report.ok(f"service {name}", f"{role}, tenants {sorted(credential.allowed_tenants)}{rotation}")

    # ---------------------------------------------------------------- MCP
    try:
        mcp = MCPSettings(_env_file=None) if staging else MCPSettings()
    except ValidationError as error:
        mcp = None
        report.fail("MCP settings", f"invalid value for: {_invalid_fields(error)}")
    else:
        report.ok("MCP_AUTH_MODE (MCP server)", mcp.auth_mode)
        backend_url = _parse_http_url(mcp.backend_base_url)
        app_port = (os.getenv("APP_PORT") or "").strip()
        if backend_url is None:
            report.fail("MCP_BACKEND_BASE_URL", "not a valid http(s) URL with a host and numeric port")
        elif app_port and not app_port.isdigit():
            report.fail("APP_PORT", "not a number")
        else:
            report.info("MCP_BACKEND_BASE_URL", backend_url[0])
            run_port = int(app_port) if app_port else DEFAULT_RUN_BACKEND_PORT
            if backend_url[1] != run_port:
                report.warn(
                    "MCP_BACKEND_BASE_URL",
                    f"port {backend_url[1]} differs from run_backend.py APP_PORT {run_port}; "
                    "set both to the port the backend actually uses",
                )

    # ---------------------------------------------------------------- agent
    try:
        from medmind.mcp_config import _mcp_auth_mode, _mcp_url
    except ImportError:
        report.fail("agent", "medmind is not importable (set PYTHONPATH=agent;.)")
        agent_mode = None
    else:
        try:
            agent_mode = _mcp_auth_mode()
            report.ok("MCP_AUTH_MODE (agent)", agent_mode)
        except RuntimeError as error:
            agent_mode = None
            report.fail("MCP_AUTH_MODE (agent)", str(error))
        try:
            mcp_url = _parse_http_url(_mcp_url())
        except RuntimeError as error:
            report.fail("MCP_URL (agent)", str(error))
        else:
            if mcp_url is None:
                report.fail("MCP_URL (agent)", "not a valid http(s) URL with a host and numeric port")
            else:
                report.ok("MCP_URL (agent)", mcp_url[0])

    if mcp is not None and agent_mode is not None and agent_mode != mcp.auth_mode:
        report.warn("MCP_AUTH_MODE", "the agent and the MCP server read different modes")

    # ---------------------------------------------------------------- tokens
    services = credentials or {}
    voice_backend = {t for c in [services.get("voice_gateway")] if c for t in (c.token, c.next_token) if t}
    mcp_backend = {t for c in [services.get("mcp_server")] if c for t in (c.token, c.next_token) if t}
    voice_sent = _secret(os.getenv("MEDMIND_SERVICE_TOKEN"))
    agent_sent = _secret(os.getenv("MCP_SERVER_TOKEN"))
    mcp_sent = _secret(mcp.backend_service_token) if mcp else None
    # Every inbound token configured on MCP (for the separation check), and the
    # ones MCP itself would accept: the same rules as mcp_server/auth.py
    # (minimum length for current and NEXT, blank NEXT ignored, never equal to
    # MCP_BACKEND_SERVICE_TOKEN).
    mcp_inbound = {t for t in (_secret(mcp.server_token), _secret(mcp.server_token_next)) if t} if mcp else set()
    mcp_accepted = set(_expected_tokens(mcp) or ()) if mcp and mcp_inbound else set()

    hops = [
        # /ai/chat has no audit mode: it always requires the gateway's token.
        ("voice gateway -> /ai/chat", "MEDMIND_SERVICE_TOKEN", voice_sent, "voice_gateway credential", voice_backend, True),
        (
            "Agent -> MCP", "MCP_SERVER_TOKEN (agent)", agent_sent, "MCP_SERVER_TOKEN (MCP)", mcp_accepted,
            bool(mcp and mcp.auth_mode == "enforce"),
        ),
        (
            "MCP -> backend", "MCP_BACKEND_SERVICE_TOKEN", mcp_sent, "mcp_server credential", mcp_backend,
            settings.booking_service_auth_mode == "enforce",
        ),
    ]
    booking_only_tokens = {
        t for name, c in services.items() if name in BOOKING_SERVICE_NAMES
        for t in (c.token, c.next_token) if t
    }
    for hop, sender_name, sent, receiver_name, accepted, enforced in hops:
        if hop.startswith("voice") and sent and sent in booking_only_tokens:
            report.fail(
                hop,
                "MEDMIND_SERVICE_TOKEN is a booking-only (mcp_server) credential; "
                "gateway routes refuse it with 403 SERVICE_NOT_ALLOWED",
            )
            continue
        if hop == "Agent -> MCP" and mcp_inbound and not mcp_accepted:
            report.fail(
                hop,
                "MCP would reject every token: MCP_SERVER_TOKEN and MCP_SERVER_TOKEN_NEXT must each be "
                f"at least {MIN_TOKEN_LENGTH} characters and differ from MCP_BACKEND_SERVICE_TOKEN",
            )
            continue
        if not sent or not accepted:
            missing = " and ".join(n for n, v in ((sender_name, sent), (receiver_name, accepted)) if not v)
            detail = f"not configured: {missing}"
            if hop.startswith("voice"):
                detail += " (/ai/chat always requires the voice gateway's token)"
            (report.fail if enforced else report.warn)(hop, detail)
            continue
        if len(sent) < MIN_TOKEN_LENGTH:
            report.fail(hop, f"{sender_name} is shorter than {MIN_TOKEN_LENGTH} characters")
        elif sent not in accepted:
            report.fail(hop, f"{sender_name} does not match {receiver_name}")
        else:
            report.ok(hop, "sender and receiver tokens match")

    groups = {
        "voice gateway": {t for t in (voice_sent, *voice_backend) if t},
        "Agent -> MCP": {t for t in (agent_sent, *mcp_inbound) if t},
        "MCP -> backend": {t for t in (mcp_sent, *mcp_backend) if t},
    }
    names = list(groups)
    shared = [
        f"{a} / {b}"
        for i, a in enumerate(names)
        for b in names[i + 1:]
        if groups[a] & groups[b]
    ]
    if shared:
        report.fail("token separation", "the same token is used by: " + "; ".join(shared))
    elif sum(1 for g in groups.values() if g) >= 2:
        report.ok("token separation", "configured tokens are distinct across hops")

    # ---------------------------------------------------------------- tenants
    # Voice: a call's tenant must be in VOICE_ALLOWED_TENANT_IDS
    # (voice_gateway/media_auth.py) and is sent to /ai/chat, which requires it
    # in the voice_gateway credential (require_service_for_tenant).
    try:
        voice_tenants = _allowed_tenants(os.environ)
    except MediaAuthError as error:
        voice_tenants = None
        report.fail("VOICE_ALLOWED_TENANT_IDS", f"{error.reason}: the voice gateway rejects every call")
    else:
        default_tenant = (os.getenv("VOICE_TENANT_ID") or "").strip()
        if default_tenant and default_tenant not in voice_tenants:
            report.warn(
                "VOICE_TENANT_ID",
                "not in VOICE_ALLOWED_TENANT_IDS: calls without a MEDMIND_TENANT_ID are rejected",
            )
    voice_credential = services.get("voice_gateway")
    if voice_tenants is not None and voice_credential is not None:
        outside = sorted(voice_tenants - voice_credential.allowed_tenants)
        if outside:
            report.fail(
                "voice tenants",
                f"{outside} are allowed by the voice gateway but not by the voice_gateway "
                "credential: their /ai/chat calls get 403 SERVICE_TENANT_NOT_ALLOWED",
            )
        else:
            report.ok("voice tenants", "VOICE_ALLOWED_TENANT_IDS are all in the voice_gateway credential")

    # AI bookings: /ai/chat accepts every gateway service (never mcp_server)
    # for its own tenants; the agent books through MCP with that tenant, and
    # the backend checks it against the mcp_server credential whenever MCP
    # sends its token.
    mcp_credential = services.get("mcp_server")
    if mcp_credential is not None and mcp_sent:
        ai_tenants = set().union(
            *(c.allowed_tenants for name, c in services.items() if name not in BOOKING_SERVICE_NAMES)
        )
        outside = sorted(ai_tenants - mcp_credential.allowed_tenants)
        if outside:
            report.fail(
                "AI booking tenants",
                f"{outside} are gateway tenants accepted on /ai/chat but not in the mcp_server credential: "
                "their AI bookings get 403 SERVICE_TENANT_NOT_ALLOWED",
            )
        else:
            report.ok("AI booking tenants", "every gateway (/ai/chat) tenant is in the mcp_server credential")


def main() -> int:
    report = Report()
    run(report)
    print("MedMind configuration preflight (no database connection)")
    print("\n".join(report.lines))
    print("RESULT:", "INVALID" if report.failed else "VALID")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
