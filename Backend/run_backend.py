import asyncio
import os

from dotenv import load_dotenv

from app.core.config import staging_selected


def load_local_env(dotenv_path=None) -> bool:
    """Load Backend/.env unless APP_ENV=staging is set in the process environment.

    Outside staging this is the previous behaviour: fill unset variables from
    .env (no override). Returns whether .env loading was attempted.
    """
    if staging_selected():
        return False
    load_dotenv(dotenv_path)
    return True


# Load .env BEFORE importing uvicorn/app modules (only when run as a script,
# so importing this module, e.g. in tests, never reads .env).
if __name__ == "__main__":
    load_local_env()


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