import asyncio
import json
import os

from datetime import (
    date,
    timedelta,
)

from uuid import (
    uuid4,
)

from mcp import (
    ClientSession,
)

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


DEFAULT_DOCTOR_ID = (
    "a2535a86-7d48-4a56-"
    "9149-d376c5e86197"
)


DEFAULT_SERVICE_ID = (
    "c549dca9-1247-51ef-"
    "bc27-424eb3c50f4c"
)


# ============================================================
# MCP RESPONSE HELPERS
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
    Extract JSON from MCP CallToolResult.
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

    # -----------------------------------------
    # Structured MCP response
    # -----------------------------------------

    structured = getattr(
        result,
        "structuredContent",
        None,
    )

    if structured is not None:
        return structured

    # -----------------------------------------
    # Text JSON
    # -----------------------------------------

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
    Extract a list from possible response wrappers.
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


def first_object(
    payload,
):
    """
    Extract the first useful object from a response.
    """

    if isinstance(
        payload,
        dict,
    ):

        result = payload.get(
            "result"
        )

        if isinstance(
            result,
            dict,
        ):
            return result

        return payload

    if isinstance(
        payload,
        list,
    ):

        for item in payload:

            try:
                obj = first_object(
                    item
                )

            except RuntimeError:
                continue

            if isinstance(
                obj,
                dict,
            ):
                return obj

    raise RuntimeError(
        "Expected a JSON object "
        "from MCP tool."
    )


def appointment_reference(
    payload,
) -> str:
    """
    Extract appointment_reference from create response.
    """

    obj = first_object(
        payload
    )

    value = obj.get(
        "appointment_reference"
    )

    if not value:
        raise RuntimeError(
            "create_booking did not "
            "return appointment_reference."
        )

    return str(
        value
    )


def field(
    payload,
    name: str,
):
    """
    Read one field from an MCP response.
    """

    obj = first_object(
        payload
    )

    return obj.get(
        name
    )


# ============================================================
# FIND AVAILABLE SLOT
# ============================================================

async def find_slot(
    session: ClientSession,
):
    """
    Find one available slot for the test.

    Searches the next 14 days.
    """

    doctor_id = os.getenv(
        "MCP_TEST_DOCTOR_ID",
        DEFAULT_DOCTOR_ID,
    )

    for offset in range(
        1,
        15,
    ):

        slot_date = (
            date.today()
            + timedelta(
                days=offset
            )
        )

        print(
            "Requesting slots for",
            slot_date.isoformat(),
        )

        result = (
            await session.call_tool(
                "list_available_slots",
                arguments={
                    "slot_date": (
                        slot_date.isoformat()
                    ),

                    "doctor_id": (
                        doctor_id
                    ),

                    "limit": 100,
                },
            )
        )

        payload = extract_json(
            result
        )

        slots = extract_items(
            payload
        )

        print(
            "Slots returned:",
            len(
                slots
            ),
        )

        for slot in slots:

            if not isinstance(
                slot,
                dict,
            ):
                continue

            slot_id = (
                slot.get(
                    "id"
                )
                or
                slot.get(
                    "slot_id"
                )
            )

            status = str(
                slot.get(
                    "status",
                    "available",
                )
            ).lower()

            if (
                slot_id
                and
                status == "available"
            ):

                return {
                    "slot_id": str(
                        slot_id
                    ),

                    "date": (
                        slot_date.isoformat()
                    ),
                }

    raise RuntimeError(
        "No available test slot was "
        "found during the next 14 days."
    )


# ============================================================
# MAIN E2E TEST
# ============================================================

async def main() -> None:

    # -----------------------------------------
    # Test patient
    # -----------------------------------------

    national_id = os.getenv(
        "MCP_TEST_NATIONAL_ID"
    )

    if not national_id:
        raise RuntimeError(
            "Set MCP_TEST_NATIONAL_ID "
            "before running this test."
        )

    # -----------------------------------------
    # Service
    # -----------------------------------------

    service_id = os.getenv(
        "MCP_TEST_SERVICE_ID",
        DEFAULT_SERVICE_ID,
    )

    # -----------------------------------------
    # Unique run
    # -----------------------------------------

    run_id = uuid4().hex

    create_key = (
        f"mcp-create-{run_id}"
    )

    cancel_key = (
        f"mcp-cancel-{run_id}"
    )

    session_reference = (
        f"mcp-test-{run_id}"
    )

    print(
        "Connecting to:",
        MCP_URL,
    )

    # ========================================================
    # CONNECT MCP
    # ========================================================

    async with streamable_http_client(
        MCP_URL
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

            # =================================================
            # FIND SLOT
            # =================================================

            slot = await find_slot(
                session
            )

            print(
                "Using test slot:",
                slot,
            )

            # =================================================
            # CREATE
            # =================================================

            create_args = {
                "national_id": (
                    national_id
                ),

                "slot_id": (
                    slot[
                        "slot_id"
                    ]
                ),

                "service_id": (
                    service_id
                ),

                "idempotency_key": (
                    create_key
                ),

                "channel": (
                    "web"
                ),

                "notes": (
                    "MCP HTTP "
                    "idempotency E2E test"
                ),

                "session_reference": (
                    session_reference
                ),
            }

            print()
            print(
                "Testing CREATE..."
            )

            # -----------------------------------------
            # Create request #1
            # -----------------------------------------

            first_create_result = (
                await session.call_tool(
                    "create_booking",
                    arguments=(
                        create_args
                    ),
                )
            )

            first_create = (
                extract_json(
                    first_create_result
                )
            )

            first_ref = (
                appointment_reference(
                    first_create
                )
            )

            print(
                "CREATE first request ✅"
            )

            print(
                "Appointment:",
                first_ref,
            )

            # -----------------------------------------
            # Create replay
            # -----------------------------------------

            replay_create_result = (
                await session.call_tool(
                    "create_booking",
                    arguments=(
                        create_args
                    ),
                )
            )

            replay_create = (
                extract_json(
                    replay_create_result
                )
            )

            replay_ref = (
                appointment_reference(
                    replay_create
                )
            )

            # -----------------------------------------
            # Same appointment
            # -----------------------------------------

            if (
                first_ref
                !=
                replay_ref
            ):
                raise AssertionError(
                    "Create replay returned "
                    "a different appointment."
                )

            # -----------------------------------------
            # Same confirmation timestamp
            # -----------------------------------------

            first_confirmed_at = field(
                first_create,
                "confirmed_at",
            )

            replay_confirmed_at = field(
                replay_create,
                "confirmed_at",
            )

            if (
                first_confirmed_at
                is not None
                and
                replay_confirmed_at
                is not None
                and
                first_confirmed_at
                !=
                replay_confirmed_at
            ):
                raise AssertionError(
                    "Create replay returned "
                    "different confirmed_at."
                )

            print(
                "CREATE replay ✅"
            )

            # =================================================
            # CANCEL
            # =================================================

            cancel_args = {
                "national_id": (
                    national_id
                ),

                "appointment_reference": (
                    first_ref
                ),

                "idempotency_key": (
                    cancel_key
                ),

                "reason": (
                    "MCP HTTP idempotency "
                    "test cleanup"
                ),

                "session_reference": (
                    session_reference
                ),
            }

            print()
            print(
                "Testing CANCEL..."
            )

            # -----------------------------------------
            # Cancel #1
            # -----------------------------------------

            first_cancel_result = (
                await session.call_tool(
                    "cancel_booking",
                    arguments=(
                        cancel_args
                    ),
                )
            )

            first_cancel = (
                extract_json(
                    first_cancel_result
                )
            )

            print(
                "CANCEL first request ✅"
            )

            # -----------------------------------------
            # Cancel replay
            # -----------------------------------------

            replay_cancel_result = (
                await session.call_tool(
                    "cancel_booking",
                    arguments=(
                        cancel_args
                    ),
                )
            )

            replay_cancel = (
                extract_json(
                    replay_cancel_result
                )
            )

            # -----------------------------------------
            # Check status
            # -----------------------------------------

            first_status = field(
                first_cancel,
                "status",
            )

            replay_status = field(
                replay_cancel,
                "status",
            )

            if (
                first_status is not None
                and
                first_status
                != "cancelled"
            ):
                raise AssertionError(
                    "First cancellation did "
                    "not return cancelled status."
                )

            if (
                replay_status is not None
                and
                replay_status
                != "cancelled"
            ):
                raise AssertionError(
                    "Cancel replay did not "
                    "return cancelled status."
                )

            # -----------------------------------------
            # Same cancellation timestamp
            # -----------------------------------------

            first_cancelled_at = field(
                first_cancel,
                "cancelled_at",
            )

            replay_cancelled_at = field(
                replay_cancel,
                "cancelled_at",
            )

            if (
                first_cancelled_at
                is not None
                and
                replay_cancelled_at
                is not None
                and
                first_cancelled_at
                !=
                replay_cancelled_at
            ):
                raise AssertionError(
                    "Cancel replay returned "
                    "different cancelled_at."
                )

            print(
                "CANCEL replay ✅"
            )

            # =================================================
            # FINAL
            # =================================================

            print()
            print(
                "=" * 60
            )

            print(
                "MCP HTTP IDEMPOTENCY "
                "E2E PASSED ✅"
            )

            print(
                "=" * 60
            )

            print(
                "CREATE:"
                " first + replay ✅"
            )

            print(
                "CANCEL:"
                " first + replay ✅"
            )

            print(
                "Appointment:",
                first_ref,
            )


if __name__ == "__main__":
    asyncio.run(
        main()
    )