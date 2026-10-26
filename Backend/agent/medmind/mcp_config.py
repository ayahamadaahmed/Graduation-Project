"""
Agent -> MCP connection settings: MCP_URL,
MCP_AUTH_MODE and the MCP_SERVER_TOKEN header.

Kept free of heavy imports so the no-connection
preflight (app/core/preflight.py) can apply exactly
the rules the agent uses (medmind/service.py
re-exports these names).
"""

from __future__ import annotations

import os


MCP_SERVICE_TOKEN_HEADER = "X-MedMind-Service-Token"

DEFAULT_MCP_URL = "http://127.0.0.1:9000/mcp"

MCP_AUTH_MODES = frozenset(
    {
        "audit",
        "enforce",
    }
)


def _mcp_auth_mode() -> str:
    """
    MCP_AUTH_MODE as the MCP server reads it:
    trimmed, case-insensitive, "audit" when
    absent. Any other value (empty included) is
    a configuration error, never a silent audit.
    """

    raw = os.getenv(
        "MCP_AUTH_MODE"
    )

    if raw is None:
        return "audit"

    mode = raw.strip().lower()

    if mode not in MCP_AUTH_MODES:

        # The value is not echoed.
        raise RuntimeError(
            "MCP_AUTH_MODE must be 'audit' "
            "or 'enforce'."
        )

    return mode


def _mcp_url() -> str:
    """
    MCP_URL, or the default when absent. A value
    that is set but empty is a configuration
    error, not a connection to ''.
    """

    raw = os.getenv(
        "MCP_URL"
    )

    if raw is None:
        return DEFAULT_MCP_URL

    url = raw.strip()

    if not url:

        raise RuntimeError(
            "MCP_URL is set but empty."
        )

    return url


def _mcp_request_headers(
    tenant_id: str,
) -> dict[str, str]:
    """
    Headers for every Agent -> MCP request.

    MCP_SERVER_TOKEN is the MCP server's inbound
    credential (separate from the MCP -> Backend
    one). With MCP_AUTH_MODE=enforce a missing
    token fails here, before any MCP call. The
    token is never logged.
    """

    mode = _mcp_auth_mode()

    headers = {
        "X-Tenant-ID":
            tenant_id,
    }

    token = (
        os.getenv(
            "MCP_SERVER_TOKEN",
            "",
        )
        .strip()
    )

    if token:

        headers[
            MCP_SERVICE_TOKEN_HEADER
        ] = token

    elif mode == "enforce":

        raise RuntimeError(
            "MCP_SERVER_TOKEN is missing "
            "while MCP_AUTH_MODE=enforce."
        )

    return headers
