"""Caller authentication for the booking and patient routes the MCP server calls.

The MCP server authenticates to the backend with its own credential: the
``mcp_server`` entry of MEDMIND_SERVICE_CREDENTIALS (same format, explicit
tenant list, no wildcards). It is sent in ``X-MedMind-Service-Token``.

BOOKING_SERVICE_AUTH_MODE:

* ``audit`` (transitional, the default): a request WITHOUT the header is still
  accepted and logged as ``booking_service_auth_missing`` with the route
  template only. Such requests are not protected. Switch to ``enforce`` once
  the logs show none.
* ``enforce``: a missing header is rejected (401), or 503 when service
  credentials are not configured (fail closed).

In both modes a header that is present must hold a valid token of a booking
service that lists the tenant; it is checked before the tenant lookup.
Neither mode skips tenant resolution, patient identity checks or staff
authorization.

Appointment confirmation has no audit mode: it always needs either the
booking service credential or a staff bearer token (provider_admin or
receptionist of the X-Tenant-ID provider).
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials

from app.api.dependencies import (
    CurrentProvider,
    StaffAccessServiceDependency,
    get_current_staff,
    staff_bearer_scheme,
)
from app.core.config import Settings, get_settings
from app.security.service_auth import (
    SERVICE_TOKEN_HEADER,
    ServiceContext,
    authenticate_service_token,
    check_service_tenant,
)
from app.security.service_credentials import BOOKING_SERVICE_NAMES
from app.security.staff_context import StaffContext

logger = logging.getLogger("uvicorn.error")

# Only the MCP server's credential (BOOKING_SERVICE_NAMES) may call these
# routes; a voice or other gateway token is valid elsewhere but not here, and
# the MCP credential is refused on the gateway routes (service_auth.py).
CONFIRM_STAFF_ROLES = frozenset({"provider_admin", "receptionist"})

ServiceToken = Annotated[str | None, Header(alias=SERVICE_TOKEN_HEADER)]
StaffBearer = Annotated[
    HTTPAuthorizationCredentials | None,
    Depends(staff_bearer_scheme),
]


def _error(status_code: int, code: str, message: str, **kwargs) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
        **kwargs,
    )


def _route_label(request: Request) -> str:
    # The route template (e.g. /api/v1/patients/{patient_id}/profile), never
    # the concrete path, so no reference or patient id reaches the log.
    return getattr(request.scope.get("route"), "path", "unknown")


def _authenticate_booking_service(token: str, settings: Settings) -> ServiceContext:
    caller = authenticate_service_token(token, settings)

    if caller.name not in BOOKING_SERVICE_NAMES:
        logger.warning("booking_service_not_allowed service=%s", caller.name)
        raise _error(
            status.HTTP_403_FORBIDDEN,
            "SERVICE_NOT_ALLOWED",
            "This service is not allowed to call this route.",
        )

    return caller


def require_booking_service_credential(
    request: Request,
    token: ServiceToken = None,
) -> ServiceContext | None:
    """Token check only, before any tenant lookup. None = audit-mode pass."""
    settings = get_settings()

    # A present header (even empty) is always verified, in every mode.
    if token is not None:
        return _authenticate_booking_service(token, settings)

    if settings.booking_service_auth_mode == "enforce":
        # Always raises: 503 when not configured, otherwise 401.
        authenticate_service_token(None, settings)

    logger.warning(
        "booking_service_auth_missing mode=audit method=%s route=%s",
        request.method,
        _route_label(request),
    )

    return None


def require_booking_service(
    caller: Annotated[
        ServiceContext | None,
        Depends(require_booking_service_credential),
    ],
    provider: CurrentProvider,
) -> ServiceContext | None:
    """The verified booking service (allowed for this tenant), or None in audit mode."""
    if caller is not None:
        check_service_tenant(caller, provider)

    return caller


BookingService = Annotated[
    ServiceContext | None,
    Depends(require_booking_service),
]


def reject_staff_attribution(caller: ServiceContext | None, claimed: str) -> None:
    """Refuse a "staff" attribution from a booking-service route caller.

    These routes have no staff authentication: the caller is the booking
    service or, in audit mode, unauthenticated (None). Neither proves a staff
    identity, so neither may record an action as done by staff.
    """
    if claimed != "staff":
        return

    logger.warning(
        "staff_attribution_denied caller=%s",
        caller.name if caller is not None else "unauthenticated",
    )
    raise _error(
        status.HTTP_403_FORBIDDEN,
        "SERVICE_CANNOT_ACT_AS_STAFF",
        "A staff attribution needs a staff access token.",
    )


def require_confirm_credentials(
    token: ServiceToken = None,
    credentials: StaffBearer = None,
) -> ServiceContext | None:
    """Runs before the tenant lookup. None means a staff token to verify next."""
    if token is not None and credentials is not None:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            "MULTIPLE_CREDENTIALS",
            "Send either a service credential or a staff token, not both.",
        )

    if token is not None:
        return _authenticate_booking_service(token, get_settings())

    if credentials is None:
        raise _error(
            status.HTTP_401_UNAUTHORIZED,
            "AUTH_REQUIRED",
            "A trusted service credential or staff access token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return None


def require_confirm_caller(
    service_caller: Annotated[
        ServiceContext | None,
        Depends(require_confirm_credentials),
    ],
    provider: CurrentProvider,
    access: StaffAccessServiceDependency,
    credentials: StaffBearer = None,
) -> ServiceContext | StaffContext:
    if service_caller is not None:
        return check_service_tenant(service_caller, provider)

    # Same JWT, membership and provider-scope checks as every staff route.
    staff = get_current_staff(provider, access, credentials)

    if staff.role not in CONFIRM_STAFF_ROLES:
        raise _error(
            status.HTTP_403_FORBIDDEN,
            "STAFF_PERMISSION_DENIED",
            "This staff role is not allowed to perform this operation.",
        )

    return staff


ConfirmCaller = Annotated[
    ServiceContext | StaffContext,
    Depends(require_confirm_caller),
]
