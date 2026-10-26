"""
Deterministic precedence for the AI booking chain's
authentication settings.

The backend reads its settings once, process
environment first; the MCP server does the same. The
backend lifespan and the agent later call
load_dotenv(override=True), which would let a
conflicting .env value replace a shell-provided one for
later os.getenv readers (the agent's MCP token and
mode), so the agent could send a token the backend and
MCP never saw.

keep_process_auth_settings() wraps such a call: for
the keys below, a value already in the process
environment is kept; .env only fills keys that are not
set. Every other key (AI keys included) keeps the
existing override behaviour. A conflict is logged with
the key name only, never a value.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager


logger = logging.getLogger(
    "uvicorn.error"
)


def dotenv_disabled_for_staging() -> bool:
    """
    APP_ENV=staging in the PROCESS environment: the
    agent must not load .env at all (same rule as
    the backend, app/core/config.py staging_selected;
    duplicated because the agent package does not
    import the app).
    """

    return (
        os.environ.get("APP_ENV")
        or ""
    ).strip().lower() == "staging"


AUTH_CHAIN_ENV_KEYS = (
    # Agent -> MCP
    "MCP_URL",
    "MCP_SERVER_TOKEN",
    "MCP_SERVER_TOKEN_NEXT",
    "MCP_AUTH_MODE",
    # MCP -> Backend
    "MCP_BACKEND_SERVICE_TOKEN",
    "MEDMIND_SERVICE_CREDENTIALS",
    "MEDMIND_SERVICE_CREDENTIALS_NEXT",
    "BOOKING_SERVICE_AUTH_MODE",
)


@contextmanager
def keep_process_auth_settings() -> Iterator[None]:

    before = {
        key: os.environ[key]
        for key in AUTH_CHAIN_ENV_KEYS
        if key in os.environ
    }

    try:

        yield

    finally:

        for key, value in before.items():

            if os.environ.get(key) != value:

                logger.warning(
                    "env_precedence_conflict "
                    "key=%s kept=process_environment",
                    key,
                )

            os.environ[key] = value
