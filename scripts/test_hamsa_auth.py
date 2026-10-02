from __future__ import annotations

import asyncio
import os

import websockets

from voice_gateway.config import (
    load_environment,
)


load_environment()


HAMSA_WS_URL = (
    "wss://api.tryhamsa.com/v1/realtime/ws"
)


async def main() -> None:

    api_key = (
        os.getenv(
            "HAMSA_API_KEY",
            "",
        )
        .strip()
    )

    if not api_key:

        print(
            "HAMSA_AUTH_FAILED "
            "reason=HAMSA_API_KEY_NOT_CONFIGURED"
        )

        return

    print(
        "HAMSA_API_KEY_FOUND "
        f"length={len(api_key)}"
    )

    uri = (
        f"{HAMSA_WS_URL}"
        f"?api_key={api_key}"
    )

    try:

        async with websockets.connect(
            uri,
            open_timeout=10,
            close_timeout=5,
            max_size=None,
        ) as websocket:

            message = (
                await asyncio.wait_for(
                    websocket.recv(),
                    timeout=10.0,
                )
            )

            print(
                "HAMSA_AUTH_OK"
            )

            print(
                "HAMSA_CONNECTION_READY"
            )

            print(
                "server_message_type="
                f"{type(message).__name__}"
            )

            # Do not print API key.
            print(
                "HAMSA_TEST_COMPLETED"
            )

    except (
        websockets.exceptions.ConnectionClosed
    ) as exc:

        print(
            "HAMSA_AUTH_FAILED "
            f"code={exc.code} "
            f"reason={exc.reason}"
        )

    except asyncio.TimeoutError:

        print(
            "HAMSA_AUTH_FAILED "
            "reason=CONNECTION_TIMEOUT"
        )

    except Exception as exc:

        print(
            "HAMSA_AUTH_FAILED "
            f"error_type="
            f"{type(exc).__name__}"
        )

        print(
            f"message={exc}"
        )


if __name__ == "__main__":

    asyncio.run(
        main()
    )