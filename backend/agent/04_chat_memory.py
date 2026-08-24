from __future__ import annotations

import asyncio
import json

from medmind.service import (
    MedMindService,
)


async def main() -> None:

    print(
        "=" * 70
    )

    print(
        "MEDMIND CHAT WITH MEMORY"
    )

    print(
        "=" * 70
    )

    print(
        "Creating Agent..."
    )

    service = await (
        MedMindService.create()
    )

    session_id = (
        "agent-memory-test-001"
    )

    print()
    print(
        f"Session: {session_id}"
    )

    print()
    print(
        "Commands:"
    )

    print(
        "/history  -> show memory"
    )

    print(
        "/state    -> show state"
    )

    print(
        "/exit     -> exit"
    )

    while True:

        print()

        message = input(
            "You: "
        ).strip()

        if not message:
            continue

        # ----------------------------------------------------
        # Exit
        # ----------------------------------------------------

        if message == "/exit":

            break

        # ----------------------------------------------------
        # History
        # ----------------------------------------------------

        if message == "/history":

            history = await (
                service.get_history(
                    session_id
                )
            )

            print()

            print(
                "=" * 70
            )

            print(
                "CONVERSATION HISTORY"
            )

            print(
                "=" * 70
            )

            for item in history:

                print(
                    f"{item.role}: "
                    f"{item.content}"
                )

            continue

        # ----------------------------------------------------
        # State
        # ----------------------------------------------------

        if message == "/state":

            state = await (
                service.get_state(
                    session_id
                )
            )

            print()

            print(
                json.dumps(
                    (
                        state.model_dump()
                        if state
                        else {}
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )

            continue

        # ----------------------------------------------------
        # Normal Chat
        # ----------------------------------------------------

        response = await (
            service.chat(
                session_id=
                    session_id,

                message=
                    message,
            )
        )

        print()

        print(
            f"MedMind: "
            f"{response['reply']}"
        )

        if response[
            "tool_calls"
        ]:

            print()

            print(
                "Tool calls:"
            )

            for tool_call in response[
                "tool_calls"
            ]:

                print(
                    f"- "
                    f"{tool_call['name']} "
                    f"{tool_call['args']}"
                )


if __name__ == "__main__":

    asyncio.run(
        main()
    )