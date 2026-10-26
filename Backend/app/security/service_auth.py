"""Service-to-service authentication for trusted gateways (voice, WhatsApp, web BFF).

A gateway sends its shared token in ``X-MedMind-Service-Token``. Credentials are
configured as::

    MEDMIND_SERVICE_CREDENTIALS="name=token@tenant-a,tenant-b;name2=token2@tenant-c"

Each token identifies one named service AND the exact tenant IDs it may act
for. There is no wildcard: every tenant must be listed. Chat sessions are bound
to the service that created them. Tokens are never logged or echoed.

Fail closed: if credentials are missing or malformed (including a missing or
invalid tenant list), every protected request is rejected (503).

Rotation overlap: MEDMIND_SERVICE_CREDENTIALS_NEXT (same format) may add ONE
extra token for a service already listed, with exactly the same tenant list.
While it is set, that service is accepted with either token, under the same
identity and tenants. Remove it (after promoting the new token) to end the
overlap; the removed token is then rejected like any unknown one. A NEXT entry
for an unknown service, with different tenants, or reusing another service's
token is a configuration error (fail closed). No service token may equal the
Agent -> MCP token (MCP_SERVER_TOKEN / MCP_SERVER_TOKEN_NEXT), so one
credential can never pass both hops.
"""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.api.dependencies import CurrentProvider
from app.core.config import Settings, get_settings
from app.security.service_credentials import (  # noqa: F401  re-exported
    BOOKING_SERVICE_NAMES,
    MIN_SERVICE_TOKEN_LENGTH,
    ServiceCredential,
    ServiceCredentialsConfigError,
    load_service_credentials,
    merge_rotation_credentials,
    parse_service_credentials,
)

logger = logging.getLogger("uvicorn.error")

SERVICE_TOKEN_HEADER = "X-MedMind-Service-Token"


@dataclass(frozen=True, slots=True)
class ServiceContext:
    """A verified trusted caller. Holds the service name and its tenants, never the token."""

    name: str
    allowed_tenants: frozenset[str]

    def may_act_for(self, tenant_id: str) -> bool:
        return tenant_id in self.allowed_tenants


def _configured_credentials(settings: Settings) -> dict[str, ServiceCredential] | None:
    try:
        return load_service_credentials(settings)
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
    matched_next = False
    # Compare against every token (current and rotation) so timing does not
    # reveal which one matched. Tokens are unique, so at most one matches.
    for name, credential in credentials.items():
        for candidate, is_next in ((credential.token, False), (credential.next_token, True)):
            if candidate is None:
                continue
            if hmac.compare_digest(presented, candidate.encode("utf-8")) and matched is None:
                matched, matched_next = name, is_next
    if matched is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "SERVICE_AUTH_INVALID",
                "message": "The trusted service credential is invalid.",
            },
        )
    if matched_next:
        # Rotation check: shows the sender has switched to the next token.
        logger.info("service_auth_next_token_used service=%s", matched)
    return ServiceContext(name=matched, allowed_tenants=credentials[matched].allowed_tenants)


def require_trusted_service(
    token: Annotated[str | None, Header(alias=SERVICE_TOKEN_HEADER)] = None,
) -> ServiceContext:
    return authenticate_service_token(token, get_settings())


TrustedService = Annotated[ServiceContext, Depends(require_trusted_service)]


def require_gateway_service(caller: TrustedService) -> ServiceContext:
    """A trusted gateway: any configured service except the booking-only ones.

    The gateway routes (/ai/*, post-call, diagnostic attachments) use this as
    their first dependency, so a booking-only identity (mcp_server) is refused
    right after the token check and before any tenant lookup.
    """
    if caller.name in BOOKING_SERVICE_NAMES:
        logger.warning("gateway_service_not_allowed service=%s", caller.name)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "SERVICE_NOT_ALLOWED",
                "message": "This service is not allowed to call this route.",
            },
        )
    return caller


GatewayService = Annotated[ServiceContext, Depends(require_gateway_service)]


def check_service_tenant(caller: ServiceContext, provider) -> ServiceContext:
    """The caller, if it is allowed to act for the resolved tenant (else 403).

    Tenant resolution itself (X-Tenant-ID -> provider) is unchanged; this only
    adds the per-service allow-list check on top of it. Shared by the gateway
    routes and the booking guard (app/security/booking_auth.py).
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


def require_service_for_tenant(
    caller: GatewayService,
    provider: CurrentProvider,
) -> ServiceContext:
    """A trusted gateway (never a booking-only identity) allowed for the tenant."""
    return check_service_tenant(caller, provider)


AuthorizedService = Annotated[ServiceContext, Depends(require_service_for_tenant)]
