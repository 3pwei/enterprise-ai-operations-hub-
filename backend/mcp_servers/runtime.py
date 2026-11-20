"""Transport settings shared by the three independently runnable MCP services."""

import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings


def create_server(name: str, service: str) -> FastMCP:
    port = int(os.getenv("MCP_PORT", "8001"))
    return FastMCP(
        name,
        host=os.getenv("MCP_HOST", "127.0.0.1"),
        port=port,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=[f"{service}-mcp:{port}", f"localhost:{port}", f"127.0.0.1:{port}"]
        ),
    )


def serve(mcp: FastMCP) -> None:
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "streamable-http":
        mcp.run(transport="streamable-http")
    else:
        raise ValueError("MCP_TRANSPORT must be stdio or streamable-http")
