"""Parsing and validation of trusted-service credentials.

Pure configuration code: it imports no FastAPI dependencies and creates no
database engine, so the no-connection preflight (app/core/preflight.py) can
use exactly the rules app/security/service_auth.py enforces. Error messages
name services, never token values.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import Settings

MIN_SERVICE_TOKEN_LENGTH = 32
# Booking-only identities: accepted on the booking/patient routes the MCP
# server calls (app/security/booking_auth.py) and refused on every gateway
# route (/ai/*, post-call, diagnostic attachments).
BOOKING_SERVICE_NAMES = frozenset({"mcp_server"})
_SERVICE_NAME = re.compile(r"^[a-z0-9_-]{1,64}$")
# Same rule as the X-Tenant-ID header (app/api/routers/medmind_ai.py).
_TENANT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class ServiceCredentialsConfigError(ValueError):
    """MEDMIND_SERVICE_CREDENTIALS is missing or malformed."""


@dataclass(frozen=True, slots=True)
class ServiceCredential:
    token: str
    allowed_tenants: frozenset[str]
    # Second accepted token during a rotation overlap (same identity, same tenants).
    next_token: str | None = None


def _parse_tenants(name: str, raw: str) -> frozenset[str]:
    tenants = [t.strip() for t in raw.split(",")]
    if not tenants or any(not t for t in tenants):
        raise ServiceCredentialsConfigError(f"Service '{name}' has an empty tenant in its tenant list.")
    for tenant in tenants:
        if tenant == "*" or "*" in tenant:
            raise ServiceCredentialsConfigError(f"Service '{name}': wildcard tenants are not allowed.")
        if not _TENANT_ID.fullmatch(tenant):
            raise ServiceCredentialsConfigError(f"Service '{name}' has an invalid tenant ID.")
    return frozenset(tenants)


def parse_service_credentials(raw: str) -> dict[str, ServiceCredential]:
    """Parse ``name=token@t1,t2;name2=token2@t3`` into {name: ServiceCredential}.

    Error messages name the service but never contain token values.
    """
    credentials: dict[str, ServiceCredential] = {}
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        name, separator, value = entry.partition("=")
        name = name.strip()
        if not separator or not _SERVICE_NAME.match(name):
            raise ServiceCredentialsConfigError("Invalid service name in MEDMIND_SERVICE_CREDENTIALS.")
        token, at, tenants = value.strip().rpartition("@")
        if not at:
            raise ServiceCredentialsConfigError(
                f"Service '{name}' must list its allowed tenants as token@tenant-a,tenant-b."
            )
        token = token.strip()
        if len(token) < MIN_SERVICE_TOKEN_LENGTH:
            raise ServiceCredentialsConfigError(
                f"Service token for '{name}' must be at least {MIN_SERVICE_TOKEN_LENGTH} characters."
            )
        if name in credentials:
            raise ServiceCredentialsConfigError(f"Duplicate service name '{name}'.")
        if any(c.token == token for c in credentials.values()):
            raise ServiceCredentialsConfigError("Each service must have its own token.")
        credentials[name] = ServiceCredential(token=token, allowed_tenants=_parse_tenants(name, tenants))
    if not credentials:
        raise ServiceCredentialsConfigError("MEDMIND_SERVICE_CREDENTIALS is empty.")
    return credentials


def merge_rotation_credentials(
    current: dict[str, ServiceCredential],
    next_raw: str,
) -> dict[str, ServiceCredential]:
    """Add MEDMIND_SERVICE_CREDENTIALS_NEXT tokens to services already in ``current``."""
    merged = dict(current)
    for name, rotation in parse_service_credentials(next_raw).items():
        credential = current.get(name)
        if credential is None:
            raise ServiceCredentialsConfigError(
                f"MEDMIND_SERVICE_CREDENTIALS_NEXT lists unknown service '{name}'."
            )
        if rotation.allowed_tenants != credential.allowed_tenants:
            raise ServiceCredentialsConfigError(
                f"Service '{name}': the next token must list exactly the same tenants."
            )
        if rotation.token == credential.token:
            continue  # same token, nothing to add
        if any(
            rotation.token in (other.token, other.next_token)
            for other_name, other in current.items()
            if other_name != name
        ):
            raise ServiceCredentialsConfigError("Each service must have its own token.")
        merged[name] = ServiceCredential(
            token=credential.token,
            allowed_tenants=credential.allowed_tenants,
            next_token=rotation.token,
        )
    return merged


def _agent_mcp_tokens(settings: Settings) -> set[str]:
    return {
        secret.get_secret_value().strip()
        for secret in (settings.mcp_server_token, settings.mcp_server_token_next)
        if secret is not None and secret.get_secret_value().strip()
    }


def load_service_credentials(settings: Settings) -> dict[str, ServiceCredential] | None:
    """The effective credentials (current + rotation), None when unset.

    Raises ServiceCredentialsConfigError when they are malformed, when a
    rotation entry is invalid, or when a service token equals the Agent -> MCP
    token (one credential must never pass both hops).
    """
    if settings.medmind_service_credentials is None:
        return None
    credentials = parse_service_credentials(settings.medmind_service_credentials.get_secret_value())
    rotation = settings.medmind_service_credentials_next
    # An empty value means no rotation in progress.
    if rotation is not None and rotation.get_secret_value().strip():
        credentials = merge_rotation_credentials(credentials, rotation.get_secret_value())
    agent_tokens = _agent_mcp_tokens(settings)
    if any(
        token in agent_tokens
        for credential in credentials.values()
        for token in (credential.token, credential.next_token)
        if token
    ):
        raise ServiceCredentialsConfigError(
            "A service token equals the Agent -> MCP token (MCP_SERVER_TOKEN); "
            "each hop needs its own credential."
        )
    return credentials
