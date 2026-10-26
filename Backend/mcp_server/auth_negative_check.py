"""
Non-destructive MCP authentication check (Agent -> MCP hop).

Run against a STAGING MCP server after MCP_AUTH_MODE=enforce:

    python -m mcp_server.auth_negative_check

It opens an MCP session and calls the read-only get_provider_info tool:

1. without X-MedMind-Service-Token   -> must be refused in enforce mode
2. with a random, never-valid token  -> must be refused in every mode

Exit code 0 means both calls were refused. In audit mode check 1 is
expected to fail (the call is served).

Safety:
- Reads only MCP_URL and TENANT_ID from the process environment. It never
  loads .env (the other smoke scripts use load_dotenv(override=True), so they
  cannot send a request without the configured token).
- Never reads, sends or prints a real token; the wrong token is generated
  here and discarded.
- Prints only refused / served, never tool results.
- get_provider_info is read-only; nothing is written even if a call is
  served.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys

import httpx
from mcp.types import LATEST_PROTOCOL_VERSION

from mcp_server.auth import SERVICE_TOKEN_HEADER


UNAUTHORIZED_TEXT = "Unauthorized MCP request."

PROBE_TOOL = "get_provider_info"


def _json_rpc_result(
    response: httpx.Response,
    request_id: int,
) -> dict:
    """Read one JSON-RPC response from a JSON or SSE body."""

    response.raise_for_status()

    if response.headers.get("content-type", "").startswith(
        "application/json"
    ):
        candidates = [response.json()]

    else:
        candidates = [
            json.loads(line[len("data:"):])
            for line in response.text.splitlines()
            if line.startswith("data:")
        ]

    for message in candidates:

        if message.get("id") == request_id:
            return message

    raise RuntimeError(
        "No JSON-RPC response for the request."
    )


async def probe_tool_call(
    client: httpx.AsyncClient,
    *,
    url: str,
    tenant_id: str,
    token: str | None = None,
) -> bool:
    """
    Call PROBE_TOOL once; return True if the MCP
    server refused it as unauthorized.
    """

    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "X-Tenant-ID": tenant_id,
    }

    if token is not None:
        headers[SERVICE_TOKEN_HEADER] = token

    initialized = await client.post(
        url,
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "medmind-auth-negative-check",
                    "version": "1",
                },
            },
        },
    )

    init_result = _json_rpc_result(
        initialized,
        1,
    )["result"]

    session_headers = {
        **headers,
        "mcp-protocol-version":
            init_result["protocolVersion"],
    }

    session_id = initialized.headers.get(
        "mcp-session-id"
    )

    if session_id:
        session_headers["mcp-session-id"] = session_id

    try:

        await client.post(
            url,
            headers=session_headers,
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )

        called = await client.post(
            url,
            headers=session_headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": PROBE_TOOL,
                    "arguments": {},
                },
            },
        )

        message = _json_rpc_result(
            called,
            2,
        )

    finally:

        if session_id:
            await client.delete(
                url,
                headers=session_headers,
            )

    result = message.get("result") or {}

    texts = [
        item.get("text", "")
        for item in result.get("content", [])
        if isinstance(item, dict)
    ]

    return bool(
        result.get("isError")
        and any(
            UNAUTHORIZED_TEXT in text
            for text in texts
        )
    )


async def main() -> int:

    url = os.getenv(
        "MCP_URL",
        "http://127.0.0.1:9000/mcp",
    )

    tenant_id = os.getenv(
        "TENANT_ID",
        "clinic-001",
    )

    async with httpx.AsyncClient(
        timeout=15.0,
        trust_env=False,
    ) as client:

        missing = await probe_tool_call(
            client,
            url=url,
            tenant_id=tenant_id,
        )

        wrong = await probe_tool_call(
            client,
            url=url,
            tenant_id=tenant_id,
            token=secrets.token_urlsafe(48),
        )

    print(
        "missing token:",
        "refused" if missing else "SERVED (expected only in audit mode)",
    )

    print(
        "wrong token:",
        "refused" if wrong else "SERVED (defect)",
    )

    return 0 if missing and wrong else 1


if __name__ == "__main__":
    sys.exit(
        asyncio.run(
            main()
        )
    )
