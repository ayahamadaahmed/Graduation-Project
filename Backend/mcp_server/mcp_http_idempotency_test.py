import asyncio
import json
import os

from datetime import date, timedelta
from uuid import uuid4

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


DOCTOR_ID = os.getenv(
    "MCP_TEST_DOCTOR_ID",
    "a2535a86-7d48-4a56-9149-d376c5e86197",
)

BRANCH_ID = os.getenv(
    "MCP_TEST_BRANCH_ID",
    "11111111-1111-4111-8111-111111111111",
)

SERVICE_ID = os.getenv(
    "MCP_TEST_SERVICE_ID",
    "c549dca9-1247-51ef-bc27-424eb3c50f4c",
)


NATIONAL_ID = os.getenv(
    "MCP_TEST_NATIONAL_ID"
)


# ============================================================
# MCP RESPONSE HELPERS
# ============================================================

def error_text(result) -> str:

    texts = []

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
            texts.append(text)

    return "\n".join(texts)


def extract_payload(result):
    """
    Convert MCP CallToolResult into normal Python data.

    FastMCP may return:
    - one JSON object in one TextContent
    - one JSON list
    - multiple TextContent items, one per list item
    - structuredContent

    This function supports all of them.
    """

    if getattr(
        result,
        "isError",
        False,
    ):
        raise RuntimeError(
            "MCP tool failed:\n"
            + error_text(result)
        )

    # ========================================================
    # Parse ALL TextContent entries
    # ========================================================

    parsed_items = []

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

        parsed_items.append(
            parsed
        )

    # --------------------------------------------------------
    # Nothing parsed from text -> structured content fallback
    # --------------------------------------------------------

    if not parsed_items:

        structured = getattr(
            result,
            "structuredContent",
            None,
        )

        if structured is None:
            structured = getattr(
                result,
                "structured_content",
                None,
            )

        if structured is not None:
            return structured

        raise RuntimeError(
            "MCP tool returned no JSON payload."
        )

    # --------------------------------------------------------
    # One TextContent only
    # --------------------------------------------------------

    if len(parsed_items) == 1:
        return parsed_items[0]

    # --------------------------------------------------------
    # Multiple TextContent entries
    #
    # Example list_available_slots:
    #
    # content[0] -> slot 1
    # content[1] -> slot 2
    # ...
    # content[13] -> slot 14
    #
    # Return them as one Python list.
    # --------------------------------------------------------

    return parsed_items


def find_list(value):
    """
    Recursively locate a list inside an MCP response.
    """

    if isinstance(
        value,
        list,
    ):
        return value

    if not isinstance(
        value,
        dict,
    ):
        return None

    preferred_keys = (
        "slots",
        "items",
        "results",
        "data",
        "result",
        "root",
        "value",
    )

    for key in preferred_keys:

        if key not in value:
            continue

        found = find_list(
            value[key]
        )

        if found is not None:
            return found

    for nested in value.values():

        found = find_list(
            nested
        )

        if found is not None:
            return found

    return None


def find_dict_with_key(
    value,
    required_key: str,
):
    """
    Recursively find a response object containing
    a particular field.
    """

    if isinstance(value, dict):

        if required_key in value:
            return value

        for nested in value.values():

            found = find_dict_with_key(
                nested,
                required_key,
            )

            if found is not None:
                return found

    elif isinstance(value, list):

        for item in value:

            found = find_dict_with_key(
                item,
                required_key,
            )

            if found is not None:
                return found

    return None


# ============================================================
# SLOT HELPERS
# ============================================================

async def get_slots(
    session: ClientSession,
    target_date: date,
):

    print(
        f"Requesting slots for "
        f"{target_date.isoformat()}..."
    )

    started = (
        asyncio
        .get_running_loop()
        .time()
    )

    result = await session.call_tool(
        "list_available_slots",
        arguments={
            "slot_date": (
                target_date.isoformat()
            ),
            "doctor_id": DOCTOR_ID,
            "branch_id": BRANCH_ID,
            "limit": 100,
    },
    )

    elapsed = (
        asyncio
        .get_running_loop()
        .time()
        - started
    )

    print(
        f"Slots response received "
        f"in {elapsed:.2f}s"
    )

    payload = extract_payload(
        result
    )

    print(
        "Payload type:",
        type(payload).__name__,
    )

    slots = find_list(
        payload
    )

    if slots is None:
        print(
            "RAW PAYLOAD:",
            repr(payload),
        )

        raise RuntimeError(
            "Could not locate slots list "
            "inside MCP response."
        )

    available = []

    for slot in slots:

        if not isinstance(
            slot,
            dict,
        ):
            continue

        slot_id = (
            slot.get("id")
            or
            slot.get("slot_id")
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
            available.append(slot)

    print(
        "Slots extracted:",
        len(slots),
    )

    print(
        "Available slots:",
        len(available),
    )

    return available


async def find_two_slots(
    session: ClientSession,
):
    """
    Find two available slots from the configured
    test branch.
    """

    for offset in range(
        1,
        15,
    ):

        target_date = (
            date.today()
            + timedelta(
                days=offset
            )
        )

        slots = await get_slots(
            session,
            target_date,
        )

        if len(slots) >= 2:

            print(
                "Selected branch:",
                BRANCH_ID,
            )

            return (
                slots[0],
                slots[1],
            )

    raise RuntimeError(
        "Could not find two available "
        "slots in the configured test branch."
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    if not NATIONAL_ID:
        raise RuntimeError(
            "MCP_TEST_NATIONAL_ID "
            "is not configured."
        )

    run_id = uuid4().hex

    create_key = (
        f"mcp-create-{run_id}"
    )

    reschedule_key = (
        f"mcp-reschedule-{run_id}"
    )

    cancel_key = (
        f"mcp-cancel-{run_id}"
    )

    session_reference = (
        f"mcp-e2e-{run_id}"
    )

    print(
        "Connecting to:",
        MCP_URL,
    )

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

            await session.initialize()

            print(
                "MCP initialized ✅"
            )

            # =================================================
            # FIND SLOTS
            # =================================================

            (
                original_slot,
                new_slot,
            ) = await find_two_slots(
                session
            )

            original_slot_id = str(
                original_slot.get("id")
                or
                original_slot.get(
                    "slot_id"
                )
            )

            new_slot_id = str(
                new_slot.get("id")
                or
                new_slot.get(
                    "slot_id"
                )
            )

            print()
            print(
                "Original slot:",
                original_slot_id,
            )

            print(
                "Original time:",
                original_slot.get(
                    "slot_date"
                ),
                original_slot.get(
                    "start_time"
                ),
            )

            print(
                "New slot:",
                new_slot_id,
            )

            print(
                "New time:",
                new_slot.get(
                    "slot_date"
                ),
                new_slot.get(
                    "start_time"
                ),
            )

            # =================================================
            # CREATE
            # =================================================

            print()
            print(
                "Testing CREATE..."
            )

            create_args = {

                "national_id":
                    NATIONAL_ID,

                "slot_id":
                    original_slot_id,

                "service_id":
                    SERVICE_ID,

                "idempotency_key":
                    create_key,

                "channel":
                    "web",

                "notes":
                    "MCP HTTP idempotency E2E",

                "session_reference":
                    session_reference,
            }

            first_create_result = (
                await session.call_tool(
                    "create_booking",
                    arguments=create_args,
                )
            )

            first_create = (
                extract_payload(
                    first_create_result
                )
            )

            first_create_obj = (
                find_dict_with_key(
                    first_create,
                    "appointment_reference",
                )
            )

            if first_create_obj is None:
                print(
                    "CREATE PAYLOAD:",
                    repr(first_create),
                )

                raise RuntimeError(
                    "Create response missing "
                    "appointment_reference."
                )

            appointment_reference = (
                first_create_obj[
                    "appointment_reference"
                ]
            )

            print(
                "CREATE first request ✅"
            )

            print(
                "Appointment:",
                appointment_reference,
            )

            # -------------------------------------------------
            # CREATE REPLAY
            # -------------------------------------------------

            create_replay_result = (
                await session.call_tool(
                    "create_booking",
                    arguments=create_args,
                )
            )

            create_replay = (
                extract_payload(
                    create_replay_result
                )
            )

            create_replay_obj = (
                find_dict_with_key(
                    create_replay,
                    "appointment_reference",
                )
            )

            assert (
                create_replay_obj
                is not None
            )

            assert (
                create_replay_obj[
                    "appointment_reference"
                ]
                ==
                appointment_reference
            )

            if (
                "confirmed_at"
                in first_create_obj
                and
                "confirmed_at"
                in create_replay_obj
            ):
                assert (
                    first_create_obj[
                        "confirmed_at"
                    ]
                    ==
                    create_replay_obj[
                        "confirmed_at"
                    ]
                )

            print(
                "CREATE replay ✅"
            )

            # =================================================
            # RESCHEDULE
            # =================================================

            print()
            print(
                "Testing RESCHEDULE..."
            )

            reschedule_args = {

                "national_id":
                    NATIONAL_ID,

                "appointment_reference":
                    appointment_reference,

                "new_slot_id":
                    new_slot_id,

                "idempotency_key":
                    reschedule_key,

                "reason":
                    "MCP HTTP E2E test",

                "session_reference":
                    session_reference,
            }

            first_reschedule_result = (
                await session.call_tool(
                    "reschedule_booking",
                    arguments=(
                        reschedule_args
                    ),
                )
            )

            first_reschedule = (
                extract_payload(
                    first_reschedule_result
                )
            )

            print(
                "RESCHEDULE first request ✅"
            )

            # -------------------------------------------------
            # RESCHEDULE REPLAY
            # -------------------------------------------------

            replay_reschedule_result = (
                await session.call_tool(
                    "reschedule_booking",
                    arguments=(
                        reschedule_args
                    ),
                )
            )

            replay_reschedule = (
                extract_payload(
                    replay_reschedule_result
                )
            )

            first_reschedule_obj = (
                find_dict_with_key(
                    first_reschedule,
                    "new_slot_id",
                )
            )

            replay_reschedule_obj = (
                find_dict_with_key(
                    replay_reschedule,
                    "new_slot_id",
                )
            )

            if (
                first_reschedule_obj
                and
                replay_reschedule_obj
            ):

                assert (
                    first_reschedule_obj[
                        "new_slot_id"
                    ]
                    ==
                    replay_reschedule_obj[
                        "new_slot_id"
                    ]
                )

                if (
                    "reschedule_count"
                    in first_reschedule_obj
                    and
                    "reschedule_count"
                    in replay_reschedule_obj
                ):
                    assert (
                        first_reschedule_obj[
                            "reschedule_count"
                        ]
                        ==
                        replay_reschedule_obj[
                            "reschedule_count"
                        ]
                    )

                if (
                    "updated_at"
                    in first_reschedule_obj
                    and
                    "updated_at"
                    in replay_reschedule_obj
                ):
                    assert (
                        first_reschedule_obj[
                            "updated_at"
                        ]
                        ==
                        replay_reschedule_obj[
                            "updated_at"
                        ]
                    )

            print(
                "RESCHEDULE replay ✅"
            )

            # =================================================
            # CANCEL
            # =================================================

            print()
            print(
                "Testing CANCEL..."
            )

            cancel_args = {

                "national_id":
                    NATIONAL_ID,

                "appointment_reference":
                    appointment_reference,

                "idempotency_key":
                    cancel_key,

                "reason":
                    "MCP HTTP E2E cleanup",

                "session_reference":
                    session_reference,
            }

            first_cancel_result = (
                await session.call_tool(
                    "cancel_booking",
                    arguments=cancel_args,
                )
            )

            first_cancel = (
                extract_payload(
                    first_cancel_result
                )
            )

            print(
                "CANCEL first request ✅"
            )

            # -------------------------------------------------
            # CANCEL REPLAY
            # -------------------------------------------------

            replay_cancel_result = (
                await session.call_tool(
                    "cancel_booking",
                    arguments=cancel_args,
                )
            )

            replay_cancel = (
                extract_payload(
                    replay_cancel_result
                )
            )

            first_cancel_obj = (
                find_dict_with_key(
                    first_cancel,
                    "cancelled_at",
                )
            )

            replay_cancel_obj = (
                find_dict_with_key(
                    replay_cancel,
                    "cancelled_at",
                )
            )

            if (
                first_cancel_obj
                and
                replay_cancel_obj
            ):
                assert (
                    first_cancel_obj[
                        "cancelled_at"
                    ]
                    ==
                    replay_cancel_obj[
                        "cancelled_at"
                    ]
                )

            print(
                "CANCEL replay ✅"
            )

            # =================================================
            # DONE
            # =================================================

            print()
            print(
                "=" * 60
            )

            print(
                "MCP IDEMPOTENCY "
                "E2E PASSED ✅"
            )

            print(
                "=" * 60
            )

            print(
                "CREATE       "
                "first + replay ✅"
            )

            print(
                "RESCHEDULE   "
                "first + replay ✅"
            )

            print(
                "CANCEL       "
                "first + replay ✅"
            )

            print(
                "Appointment:",
                appointment_reference,
            )


if __name__ == "__main__":
    asyncio.run(
        main()
    )