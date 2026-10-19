"""Service-to-service authentication for trusted gateways (voice, WhatsApp, web BFF).

A gateway sends its shared token in ``X-MedMind-Service-Token``. Credentials are
configured as::

    MEDMIND_SERVICE_CREDENTIALS="name=token@tenant-a,tenant-b;name2=token2@tenant-c"

Each token identifies one named service AND the exact tenant IDs it may act
for. There is no wildcard: every tenant must be listed. Chat sessions are bound
to the service that created them. Tokens are never logged or echoed.

Fail closed: if credentials are missing or malformed (including a missing or
invalid tenant list), every protected request is rejected (503).
"""

from __future__ import annotations

import hmac
import logging
import re
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.api.dependencies import CurrentProvider
from app.core.config import Settings, get_settings

logger = logging.getLogger("uvicorn.error")

SERVICE_TOKEN_HEADER = "X-MedMind-Service-Token"
MIN_SERVICE_TOKEN_LENGTH = 32
_SERVICE_NAME = re.compile(r"^[a-z0-9_-]{1,64}$")
# Same rule as the X-Tenant-ID header (app/api/routers/medmind_ai.py).
_TENANT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class ServiceCredentialsConfigError(ValueError):
    """MEDMIND_SERVICE_CREDENTIALS is missing or malformed."""


@dataclass(frozen=True, slots=True)
class ServiceCredential:
    token: str
    allowed_tenants: frozenset[str]


@dataclass(frozen=True, slots=True)
class ServiceContext:
    """A verified trusted caller. Holds the service name and its tenants, never the token."""

    name: str
    allowed_tenants: frozenset[str]

    def may_act_for(self, tenant_id: str) -> bool:
        return tenant_id in self.allowed_tenants


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


def _configured_credentials(settings: Settings) -> dict[str, ServiceCredential] | None:
    if settings.medmind_service_credentials is None:
        return None
    try:
        return parse_service_credentials(settings.medmind_service_credentials.get_secret_value())
    except ServiceCredentialsConfigError as exc:
        logger.error("medmind_service_credentials_invalid reason=%s", exc)
        return None


def authenticate_service_token(token: str | None, settings: Settings) -> ServiceContext:
    credentials = _configured_credentials(settings)
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "SERVICE_AUTH_NOT_CONFIGURED",
                "message": "Trusted service authentication is not configured.",
            },
        )
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "SERVICE_AUTH_REQUIRED",
                "message": "A trusted service credential is required.",
            },
        )

    presented = token.encode("utf-8")
    matched: str | None = None
    # Compare against every credential so timing does not reveal which one matched.
    for name, credential in credentials.items():
        if hmac.compare_digest(presented, credential.token.encode("utf-8")) and matched is None:
            matched = name
    if matched is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "SERVICE_AUTH_INVALID",
                "message": "The trusted service credential is invalid.",
            },
        )
    return ServiceContext(name=matched, allowed_tenants=credentials[matched].allowed_tenants)


def require_trusted_service(
    token: Annotated[str | None, Header(alias=SERVICE_TOKEN_HEADER)] = None,
) -> ServiceContext:
    return authenticate_service_token(token, get_settings())


TrustedService = Annotated[ServiceContext, Depends(require_trusted_service)]


def require_service_for_tenant(
    caller: TrustedService,
    provider: CurrentProvider,
) -> ServiceContext:
    """The trusted service, but only if it is allowed to act for the resolved tenant.

    Tenant resolution itself (X-Tenant-ID -> provider) is unchanged; this only
    adds the per-service allow-list check on top of it.
    """
    if not caller.may_act_for(provider.tenant_key):
        logger.warning(
            "service_tenant_denied service=%s tenant_id=%s",
            caller.name,
            provider.tenant_key,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "SERVICE_TENANT_NOT_ALLOWED",
                "message": "This service is not allowed to act for this tenant.",
            },
        )
    return caller


AuthorizedService = Annotated[ServiceContext, Depends(require_service_for_tenant)]
