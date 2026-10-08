import asyncio
import os

from dotenv import load_dotenv


# Load .env BEFORE importing uvicorn/app modules.
load_dotenv()


import uvicorn


def selector_loop_factory():
    """
    Force SelectorEventLoop on Windows.

    Required by async psycopg on Windows.
    """

    return asyncio.SelectorEventLoop()


def main() -> None:

    host = os.getenv(
        "APP_HOST",
        "127.0.0.1",
    )

    port = int(
        os.getenv(
            "APP_PORT",
            "8004",
        )
    )

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=False,
        loop=(
            "run_backend:"
            "selector_loop_factory"
        ),
    )


if __name__ == "__main__":
    main()