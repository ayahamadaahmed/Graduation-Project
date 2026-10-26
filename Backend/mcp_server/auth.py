"""Inbound authentication for MCP tool calls (Agent -> MCP).

The caller sends MCP_SERVER_TOKEN in ``X-MedMind-Service-Token``. Every tool
checks it through ``_require_request_tenant_id`` in ``mcp_server/server.py``.

MCP_AUTH_MODE:

* ``audit`` (transitional, the default): a call WITHOUT the header is still
  served and logged as ``mcp_service_auth_missing``. Such calls are not
  protected; switch to ``enforce`` once the logs show none.
* ``enforce``: a missing header is rejected, as is every call when
  MCP_SERVER_TOKEN is unset or too short (fail closed).

A header that is present is always compared (timing-safe) and rejected if
wrong, in both modes. Callers only ever see the generic unauthorized error;
the token is never logged.

Rotation overlap: MCP_SERVER_TOKEN_NEXT, when set, is accepted as well. Remove
it after promoting the new token; the old one is then rejected. An inbound
token equal to MCP_BACKEND_SERVICE_TOKEN is a configuration error, so one
credential can never pass both hops; it is treated as unconfigured (fail
closed).
"""

from __future__ import annotations

import hmac
import logging
from collections.abc import Mapping

from mcp_server.config import (
    MCPSettings,
    get_mcp_settings,
)


logger = logging.getLogger(
    "uvicorn.error"
)


SERVICE_TOKEN_HEADER = "X-MedMind-Service-Token"

# Same minimum as the backend's service tokens.
MIN_SERVICE_TOKEN_LENGTH = 32


class MCPUnauthorizedError(PermissionError):

    def __init__(
        self,
    ) -> None:

        super().__init__(
            "Unauthorized MCP request."
        )


def _expected_tokens(
    settings: MCPSettings,
) -> tuple[str, ...] | None:
    """Accepted inbound tokens, or None when unconfigured or misconfigured."""

    if settings.server_token is None:
        return None

    tokens = [
        settings.server_token
        .get_secret_value()
        .strip()
    ]

    next_token = (
        settings.server_token_next
        .get_secret_value()
        .strip()
        if settings.server_token_next
        is not None
        else ""
    )

    # An empty value means no rotation in progress.
    if next_token:

        tokens.append(
            next_token
        )

    if any(
        len(token) < MIN_SERVICE_TOKEN_LENGTH
        for token in tokens
    ):

        logger.error(
            "mcp_server_token_invalid "
            "reason=too_short_or_empty"
        )

        return None

    backend_token = (
        settings.backend_service_token
        .get_secret_value()
        .strip()
        if settings.backend_service_token
        is not None
        else ""
    )

    if backend_token and backend_token in tokens:

        logger.error(
            "mcp_server_token_invalid "
            "reason=same_as_backend_service_token"
        )

        return None

    # Current == next during a shared-.env switch
    # is one token, not two.
    return tuple(
        dict.fromkeys(tokens)
    )


def authorize_mcp_request(
    headers: Mapping[str, str],
    *,
    client_host: str | None = None,
    settings: MCPSettings | None = None,
) -> None:
    """Raise MCPUnauthorizedError unless this call may use the MCP tools."""

    settings = (
        settings
        or get_mcp_settings()
    )

    presented = headers.get(
        SERVICE_TOKEN_HEADER.lower()
    )

    expected = _expected_tokens(
        settings
    )

    if presented is not None:

        # Compare against every accepted token (and
        # even when unconfigured), so timing does not
        # reveal the configuration or which matched.
        matches = [
            hmac.compare_digest(
                presented.encode("utf-8"),
                candidate.encode("utf-8"),
            )
            for candidate in (expected or ("",))
        ]

        if expected is None or not any(matches):

            logger.warning(
                "mcp_service_auth_invalid "
                "client=%s",
                client_host,
            )

            raise MCPUnauthorizedError()

        if len(expected) > 1 and matches[1]:

            # Rotation check: the caller has switched
            # to the next token.
            logger.info(
                "mcp_service_auth_next_token_used "
                "client=%s",
                client_host,
            )

        return

    if settings.auth_mode == "enforce":

        logger.warning(
            "mcp_service_auth_required "
            "client=%s "
            "configured=%s",
            client_host,
            expected is not None,
        )

        raise MCPUnauthorizedError()

    logger.warning(
        "mcp_service_auth_missing "
        "mode=audit "
        "client=%s",
        client_host,
    )
