"""Authentication + tenant authorization for the Asterisk media WebSocket.

Asterisk connects to ``/asterisk/media`` and, before any audio is used, sends a
``MEDIA_START`` event whose ``channel_variables`` the gateway already reads
(``MEDMIND_TENANT_ID``). The same mechanism carries a shared secret:

    channel variable  MEDMIND_MEDIA_TOKEN  == env VOICE_MEDIA_SHARED_SECRET

and the call's tenant must be listed in ``VOICE_ALLOWED_TENANT_IDS``. Anything
missing, malformed or not allowed fails closed: the gateway closes the socket
before creating a session, STT/TTS streams, or calling the MedMind backend.

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


def _shared_secret(env: Mapping[str, str]) -> str:
    secret = env.get(SECRET_ENV, "").strip()
    if len(secret) < MIN_SECRET_LENGTH:
        raise MediaAuthError("shared_secret_not_configured")
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
