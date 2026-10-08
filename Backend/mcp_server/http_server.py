"""
MedMind MCP Streamable HTTP Server.

Run:

    python -m mcp_server.http_server

Default endpoint:

    http://127.0.0.1:9000/mcp
"""

from mcp_server.server import (
    mcp,
)


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http"
    )