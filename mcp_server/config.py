from functools import lru_cache

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

    MCP_HOST=127.0.0.1
    MCP_PORT=9000
    MCP_STREAMABLE_HTTP_PATH=/mcp
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