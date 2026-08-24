import httpx
import asyncio
import json
import os

from datetime import (
    date,
    timedelta,
)

from mcp import ClientSession

from mcp.client.streamable_http import (
    streamable_http_client,
)


# ============================================================
# CONFIG
# ============================================================

MCP_URL = os.getenv(
    "MCP_HTTP_URL",
    "http://127.0.0.1:9000/mcp",
)
MCP_TEST_TENANT_ID = os.getenv(
    "MCP_TEST_TENANT_ID",
    "clinic-001",
)

DEFAULT_DOCTOR_ID = (
    "a2535a86-7d48-4a56-"
    "9149-d376c5e86197"
)


# ============================================================
# MCP RESULT HELPERS
# ============================================================

def _error_text(
    result,
) -> str:

    parts: list[str] = []

    for item in getattr(
        result,
        "content",
        [],
    ):
        text = getattr(
            item,
            "text",
            None,
        )

        if text:
            parts.append(
                text
            )

    return (
        "\n".join(parts)
        or
        "MCP tool returned an error."
    )


def extract_json(
    result,
):
    """
    Extract JSON from an MCP tool response.

    Handles:
    - structuredContent
    - text content containing JSON
    - MCP error results
    """

    if getattr(
        result,
        "isError",
        False,
    ):
        raise RuntimeError(
            "MCP tool failed:\n"
            + _error_text(
                result
            )
        )

    structured = getattr(
        result,
        "structuredContent",
        None,
    )

    if structured is not None:
        return structured

    objects = []

    for item in getattr(
        result,
        "content",
        [],
    ):

        text = getattr(
            item,
            "text",
            None,
        )

        if not text:
            continue

        try:
            parsed = json.loads(
                text
            )

        except json.JSONDecodeError:
            continue

        objects.append(
            parsed
        )

    if not objects:
        return {}

    if len(objects) == 1:
        return objects[0]

    return objects


def extract_items(
    payload,
) -> list:
    """
    Extract list from common Backend/MCP response
    shapes.
    """

    if isinstance(
        payload,
        list,
    ):
        return payload

    if not isinstance(
        payload,
        dict,
    ):
        return []

    for key in (
        "slots",
        "items",
        "data",
        "results",
        "result",
    ):

        value = payload.get(
            key
        )

        if isinstance(
            value,
            list,
        ):
            return value

        if isinstance(
            value,
            dict,
        ):
            nested = extract_items(
                value
            )

            if nested:
                return nested

    return []

# ============================================================
# TEST
# ============================================================

async def main() -> None:

    print(
        "Connecting to:",
        MCP_URL,
    )

    print(
        "Test tenant:",
        MCP_TEST_TENANT_ID,
    )

    # ========================================================
    # TENANT-SCOPED HTTP CLIENT
    # ========================================================

    async with httpx.AsyncClient(
        headers={
            "X-Tenant-ID":
                MCP_TEST_TENANT_ID,
        },
        follow_redirects=True,
        trust_env=False,
    ) as http_client:

        # ====================================================
        # MCP STREAMABLE HTTP
        # ====================================================

        async with streamable_http_client(
            MCP_URL,
            http_client=http_client,
        ) as (
            read,
            write,
            _,
        ):

            async with ClientSession(
                read,
                write,
            ) as session:

                # -----------------------------------------
                # Initialize
                # -----------------------------------------

                await session.initialize()

                print(
                    "MCP initialized ✅"
                )

                # -----------------------------------------
                # Verify tools
                # -----------------------------------------

                tools_result = (
                    await session.list_tools()
                )

                tool_names = {
                    tool.name
                    for tool
                    in tools_result.tools
                }

                # -----------------------------------------
                # Verify business tools
                # -----------------------------------------

                required_tools = {
                    "get_provider_info",
                    "list_doctors",
                    "list_services",
                    "list_available_slots",
                    "resolve_patient",
                    "search_patient_bookings",
                    "lookup_booking",
                    "lookup_patient",
                    "create_booking",
                    "cancel_booking",
                    "reschedule_booking",
                }

                missing = (
                    required_tools
                    - tool_names
                )

                if missing:

                    raise RuntimeError(
                        "Missing MCP tools: "
                        + ", ".join(
                            sorted(
                                missing
                            )
                        )
                    )

                # -----------------------------------------
                # Ensure debug tools stay removed
                # -----------------------------------------

                forbidden_debug_tools = {
                    "debug_runtime",
                    "debug_backend_health",
                    "debug_raw_health",
                }

                exposed_debug_tools = (
                    forbidden_debug_tools
                    & tool_names
                )

                if exposed_debug_tools:

                    raise RuntimeError(
                        "Debug MCP tools must not "
                        "be exposed: "
                        + ", ".join(
                            sorted(
                                exposed_debug_tools
                            )
                        )
                    )

                print(
                    "MCP business tools verified ✅"
                )

                # -----------------------------------------
                # Provider / tenant routing
                # -----------------------------------------

                provider_result = (
                    await session.call_tool(
                        "get_provider_info",
                        arguments={},
                    )
                )

                provider = (
                    extract_json(
                        provider_result
                    )
                )

                print(
                    "PROVIDER:",
                    provider,
                )

                if not isinstance(
                    provider,
                    dict,
                ):

                    raise RuntimeError(
                        "Provider response "
                        "is invalid."
                    )

                returned_tenant = (
                    provider.get(
                        "tenant_key"
                    )
                )

                if (
                    returned_tenant
                    !=
                    MCP_TEST_TENANT_ID
                ):

                    raise RuntimeError(
                        "Tenant routing mismatch: "
                        f"requested="
                        f"{MCP_TEST_TENANT_ID}, "
                        f"returned="
                        f"{returned_tenant}"
                    )

                print(
                    "Tenant routing verified ✅"
                )

                # -----------------------------------------
                # Slots
                # -----------------------------------------

                doctor_id = os.getenv(
                    "MCP_TEST_DOCTOR_ID",
                    DEFAULT_DOCTOR_ID,
                )

                test_date = (
                    date.today()
                    + timedelta(
                        days=1
                    )
                )

                slots_result = (
                    await session.call_tool(
                        "list_available_slots",
                        arguments={
                            "slot_date":
                                test_date.isoformat(),

                            "doctor_id":
                                doctor_id,

                            "limit":
                                100,
                        },
                    )
                )

                slots_payload = (
                    extract_json(
                        slots_result
                    )
                )

                slots = (
                    extract_items(
                        slots_payload
                    )
                )

                print(
                    "SLOTS COUNT:",
                    len(
                        slots
                    ),
                )

                print(
                    "STREAMABLE HTTP MCP "
                    "SMOKE TEST PASSED ✅"
                )


if __name__ == "__main__":

    asyncio.run(
        main()
    )
