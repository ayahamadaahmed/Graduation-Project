"""Authentication + tenant authorization for the Asterisk media WebSocket.

Asterisk connects to ``/asterisk/media`` and, before any audio is used, sends a
``MEDIA_START`` event whose ``channel_variables`` the gateway already reads
(``MEDMIND_TENANT_ID``). The same mechanism carries a shared secret:

    channel variable  MEDMIND_MEDIA_TOKEN  == env VOICE_MEDIA_SHARED_SECRET

and the call's tenant must be listed in ``VOICE_ALLOWED_TENANT_IDS``. Anything
missing, malformed or not allowed fails closed: the gateway closes the socket
before creating a session, STT/TTS streams, or calling the MedMind backend.

The media secret is its own credential: if it equals any service-hop token in
the process environment (the gateway's MEDMIND_SERVICE_TOKEN, the MCP tokens,
or a token inside MEDMIND_SERVICE_CREDENTIALS[_NEXT]), the gateway counts as
misconfigured and rejects every call, like an unset secret.

Secrets are compared in constant time and never logged.
"""

from __future__ import annotations

import hmac
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

SECRET_ENV = "VOICE_MEDIA_SHARED_SECRET"
ALLOWED_TENANTS_ENV = "VOICE_ALLOWED_TENANT_IDS"
DEFAULT_TENANT_ENV = "VOICE_TENANT_ID"
AUTH_TIMEOUT_ENV = "VOICE_MEDIA_AUTH_TIMEOUT_SECONDS"

TOKEN_VARIABLE = "MEDMIND_MEDIA_TOKEN"
TENANT_VARIABLE = "MEDMIND_TENANT_ID"

# Service-hop credentials the media secret must never equal.
SERVICE_TOKEN_ENVS = (
    "MEDMIND_SERVICE_TOKEN",
    "MCP_SERVER_TOKEN",
    "MCP_SERVER_TOKEN_NEXT",
    "MCP_BACKEND_SERVICE_TOKEN",
)
# Same "name=token@tenants;..." format as the backend.
SERVICE_CREDENTIAL_ENVS = (
    "MEDMIND_SERVICE_CREDENTIALS",
    "MEDMIND_SERVICE_CREDENTIALS_NEXT",
)

MIN_SECRET_LENGTH = 32
DEFAULT_AUTH_TIMEOUT_SECONDS = 10.0
# Same rule as the backend's X-Tenant-ID validation.
_TENANT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# WebSocket close code for a policy violation (RFC 6455).
POLICY_VIOLATION_CLOSE_CODE = 1008


class MediaAuthError(Exception):
    """Media connection rejected. ``reason`` is safe to log (no secrets)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class MediaAuthorization:
    tenant_id: str
    tenant_source: str  # "asterisk" (channel variable) or "environment"


def _allowed_tenants(env: Mapping[str, str]) -> frozenset[str]:
    raw = env.get(ALLOWED_TENANTS_ENV, "")
    tenants = [t.strip() for t in raw.split(",")]
    if not raw.strip() or any(not t for t in tenants):
        raise MediaAuthError("allowed_tenants_not_configured")
    for tenant in tenants:
        if "*" in tenant or not _TENANT_ID.fullmatch(tenant):
            raise MediaAuthError("allowed_tenants_invalid")
    return frozenset(tenants)


def _service_tokens(env: Mapping[str, str]) -> list[str]:
    tokens = [env.get(name, "").strip() for name in SERVICE_TOKEN_ENVS]
    for name in SERVICE_CREDENTIAL_ENVS:
        for entry in env.get(name, "").split(";"):
            _, separator, value = entry.partition("=")
            if not separator:
                continue
            token, at, _ = value.strip().rpartition("@")
            tokens.append((token if at else value).strip())
    return [token for token in tokens if token]


def _shared_secret(env: Mapping[str, str]) -> str:
    secret = env.get(SECRET_ENV, "").strip()
    if len(secret) < MIN_SECRET_LENGTH:
        raise MediaAuthError("shared_secret_not_configured")
    # Compare against every token so timing does not reveal which one matched.
    reused = [
        hmac.compare_digest(secret.encode("utf-8"), token.encode("utf-8"))
        for token in _service_tokens(env)
    ]
    if any(reused):
        raise MediaAuthError("shared_secret_reuses_service_token")
    return secret


def auth_timeout_seconds(env: Mapping[str, str] | None = None) -> float:
    env = os.environ if env is None else env
    try:
        value = float(env.get(AUTH_TIMEOUT_ENV, DEFAULT_AUTH_TIMEOUT_SECONDS))
    except ValueError:
        return DEFAULT_AUTH_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_AUTH_TIMEOUT_SECONDS


def authorize_media_start(
    event: Mapping[str, object],
    env: Mapping[str, str] | None = None,
) -> MediaAuthorization:
    """Authenticate a MEDIA_START event and choose its tenant, or raise MediaAuthError."""
    env = os.environ if env is None else env

    # Configuration first: unconfigured gateways reject every call.
    secret = _shared_secret(env)
    allowed = _allowed_tenants(env)

    variables = event.get("channel_variables")
    if not isinstance(variables, Mapping):
        variables = {}

    presented = variables.get(TOKEN_VARIABLE)
    if not isinstance(presented, str) or not presented:
        raise MediaAuthError("missing_media_token")
    if not hmac.compare_digest(presented.encode("utf-8"), secret.encode("utf-8")):
        raise MediaAuthError("invalid_media_token")

    raw_tenant = variables.get(TENANT_VARIABLE)
    tenant = str(raw_tenant).strip() if raw_tenant is not None else ""
    source = "asterisk"
    if not tenant:
        tenant = env.get(DEFAULT_TENANT_ENV, "").strip()
        source = "environment"
    if not tenant:
        raise MediaAuthError("missing_tenant")
    if tenant not in allowed:
        raise MediaAuthError("tenant_not_allowed")

    return MediaAuthorization(tenant_id=tenant, tenant_source=source)
