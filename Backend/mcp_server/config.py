from functools import lru_cache
from typing import Literal

from pydantic import (
    SecretStr,
    field_validator,
)
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


class MCPSettings(
    BaseSettings
):
    """
    MCP -> FastAPI Backend configuration.

    Environment variables use the MCP_ prefix.

    Examples:

    MCP_BACKEND_BASE_URL=http://127.0.0.1:8002
    MCP_REQUEST_TIMEOUT=30

    MCP_HOST, MCP_PORT and MCP_STREAMABLE_HTTP_PATH
    are NOT used by the server: it binds
    127.0.0.1:9000/mcp, set explicitly in
    mcp_server/server.py.

    MCP_SERVER_TOKEN=<agent -> MCP credential>
    MCP_SERVER_TOKEN_NEXT=<rotation overlap only>
    MCP_AUTH_MODE=audit
    MCP_BACKEND_SERVICE_TOKEN=<MCP -> backend credential>
    """

    # -----------------------------------------
    # Backend
    # -----------------------------------------

    backend_base_url: str = (
        "http://127.0.0.1:8001"
    )

    request_timeout: float = (
        30.0
    )

    # -----------------------------------------
    # MCP HTTP Server
    # -----------------------------------------

    host: str = (
        "127.0.0.1"
    )

    port: int = (
        9000
    )

    streamable_http_path: str = (
        "/mcp"
    )

    # -----------------------------------------
    # Authentication (two separate credentials)
    # -----------------------------------------

    # Agent -> MCP: what callers must send in
    # X-MedMind-Service-Token.
    server_token: SecretStr | None = None

    # Rotation overlap only: a second accepted
    # inbound token. Remove it once the new token
    # is promoted to MCP_SERVER_TOKEN.
    server_token_next: SecretStr | None = None

    # "audit" is transitional: a request without
    # the header is still served and logged.
    # "enforce" rejects it. A present but wrong
    # token is rejected in both modes.
    auth_mode: Literal[
        "audit",
        "enforce",
    ] = "audit"

    # MCP -> Backend: the mcp_server token from
    # the backend's MEDMIND_SERVICE_CREDENTIALS.
    backend_service_token: SecretStr | None = None

    @field_validator(
        "auth_mode",
        mode="before",
    )
    @classmethod
    def _normalize_auth_mode(
        cls,
        value: object,
    ) -> object:

        # Any other value fails settings loading
        # (fail closed), never "off".
        if isinstance(value, str):
            return value.strip().lower()

        return value

    # -----------------------------------------
    # Pydantic Settings
    # -----------------------------------------

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="MCP_",
        extra="ignore",
    )


@lru_cache
def get_mcp_settings() -> MCPSettings:

    return MCPSettings()