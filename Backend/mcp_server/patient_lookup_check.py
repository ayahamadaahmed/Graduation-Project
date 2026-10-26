"""
Read-only MCP -> backend check: one patient lookup that cannot expose data.

Run against a STAGING MCP server (loopback only):

    MCP_URL=http://127.0.0.1:9000/mcp MCP_SERVER_TOKEN=... TENANT_ID=clinic-001 \\
        python -m mcp_server.patient_lookup_check

It calls only the read-only MCP tool `lookup_patient` (POST
/api/v1/patients/lookup on the backend) once, with the built-in
non-existent national ID below, and prints only "found: false" or
"found: true". Exit code 0 means the lookup completed and found nothing.

Safety (unlike scripts/smoke_mcp_patient_lookup.py):
- Refuses to run if TEST_EXISTING_NATIONAL_ID exists in the process
  environment at all, even empty.
- Never loads .env: MCP_URL, MCP_SERVER_TOKEN and TENANT_ID come only from
  the process environment, are all required, and are never printed.
- MCP_URL must be http(s) on a loopback host with no user:password part.
- Never prints the national ID, the response, any patient field, a URL or a
  token; failures print a fixed category only.
- Fails closed on any unexpected response shape.
- Calls no other tool: no booking, profile update or other write, and no
  /ai/chat.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from mcp.types import LATEST_PROTOCOL_VERSION

from mcp_server.auth import SERVICE_TOKEN_HEADER
from mcp_server.auth_negative_check import _json_rpc_result


# The documented non-existent test ID (scripts/smoke_mcp_patient_lookup.py).
NOT_FOUND_NATIONAL_ID = "29901010000001"

LOOKUP_TOOL = "lookup_patient"

FORBIDDEN_ENV = "TEST_EXISTING_NATIONAL_ID"

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

TENANT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# The backend's PatientLookupResponse keys.
RESPONSE_KEYS = frozenset({"found", "patient"})


class CheckRefused(Exception):
    """Configuration is not safe to run with. The message is a fixed category."""


class CheckFailed(Exception):
    """The lookup did not produce a trustworthy answer. Fixed category only."""


@dataclass(frozen=True)
class CheckConfig:
    url: str
    token: str
    tenant_id: str


def load_config(env: Mapping[str, str]) -> CheckConfig:
    """Validate the process environment; raise CheckRefused before any call."""

    if FORBIDDEN_ENV in env:
        raise CheckRefused(f"{FORBIDDEN_ENV} is set; unset it to run this check")

    url = (env.get("MCP_URL") or "").strip()
    token = (env.get("MCP_SERVER_TOKEN") or "").strip()
    tenant_id = (env.get("TENANT_ID") or "").strip()

    if not url or not token or not tenant_id:
        raise CheckRefused("MCP_URL, MCP_SERVER_TOKEN and TENANT_ID must all be set")

    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018  raises ValueError for a malformed port
    except ValueError:
        raise CheckRefused("MCP_URL is not a valid URL") from None

    if parts.scheme not in ("http", "https"):
        raise CheckRefused("MCP_URL must be http or https")

    if parts.username is not None or parts.password is not None:
        raise CheckRefused("MCP_URL must not contain credentials")

    if (parts.hostname or "").lower() not in LOOPBACK_HOSTS:
        raise CheckRefused("MCP_URL must point to a loopback host")

    if not TENANT_PATTERN.fullmatch(tenant_id):
        raise CheckRefused("TENANT_ID is not a valid tenant identifier")

    return CheckConfig(url=url, token=token, tenant_id=tenant_id)


def _lookup_payload(message: dict) -> dict:
    """The backend response carried by a tools/call result, or CheckFailed."""

    result = message.get("result")
    if not isinstance(result, dict) or result.get("isError"):
        raise CheckFailed("the lookup tool returned an error")

    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        payload = structured.get("result", structured)
    else:
        texts = [
            item.get("text")
            for item in result.get("content") or []
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        if len(texts) != 1 or not isinstance(texts[0], str):
            raise CheckFailed("unexpected tool response shape")
        try:
            payload = json.loads(texts[0])
        except ValueError:
            raise CheckFailed("unexpected tool response shape") from None

    if not isinstance(payload, dict) or set(payload) - RESPONSE_KEYS or "found" not in payload:
        raise CheckFailed("unexpected tool response shape")
    if not isinstance(payload["found"], bool):
        raise CheckFailed("unexpected tool response shape")

    return payload


async def lookup_found(client: httpx.AsyncClient, config: CheckConfig) -> bool:
    """One read-only lookup of the built-in non-existent ID; returns `found`."""

    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "X-Tenant-ID": config.tenant_id,
        SERVICE_TOKEN_HEADER: config.token,
    }

    try:
        initialized = await client.post(config.url, headers=headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": LATEST_PROTOCOL_VERSION, "capabilities": {},
                       "clientInfo": {"name": "medmind-patient-lookup-check", "version": "1"}},
        })
        init_result = _json_rpc_result(initialized, 1)["result"]
    except (httpx.HTTPError, RuntimeError, KeyError, TypeError, ValueError):
        raise CheckFailed("could not open an MCP session") from None

    session_headers = {**headers, "mcp-protocol-version": init_result.get("protocolVersion", "")}
    session_id = initialized.headers.get("mcp-session-id")
    if session_id:
        session_headers["mcp-session-id"] = session_id

    try:
        await client.post(config.url, headers=session_headers,
                          json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        called = await client.post(config.url, headers=session_headers, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": LOOKUP_TOOL,
                       "arguments": {"national_id": NOT_FOUND_NATIONAL_ID, "language": "ar"}},
        })
        message = _json_rpc_result(called, 2)
    except (httpx.HTTPError, RuntimeError, ValueError):
        raise CheckFailed("the lookup call failed") from None
    finally:
        if session_id:
            try:
                await client.delete(config.url, headers=session_headers)
            except httpx.HTTPError:
                pass

    return _lookup_payload(message)["found"]


async def run(env: Mapping[str, str], client: httpx.AsyncClient | None = None) -> tuple[int, str]:
    """(exit code, the single line to print). Never raises."""

    try:
        config = load_config(env)
    except CheckRefused as refused:
        return 2, f"REFUSED: {refused}"

    try:
        if client is None:
            async with httpx.AsyncClient(timeout=15.0, trust_env=False, follow_redirects=False) as own:
                found = await lookup_found(own, config)
        else:
            found = await lookup_found(client, config)
    except CheckFailed as failed:
        return 1, f"FAILED: {failed}"

    # The ID is built-in and non-existent: anything but "not found" is suspect.
    return (0 if not found else 1), f"found: {'true' if found else 'false'}"


def main() -> int:
    code, line = asyncio.run(run(os.environ))
    print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
