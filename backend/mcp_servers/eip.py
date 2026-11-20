from sqlalchemy.orm import Session

from backend.db import engine
from backend.mcp_servers.runtime import create_server, serve
from backend.tool_service import invoke

mcp = create_server("EIP MCP", "eip")


@mcp.tool()
def approval_rules(capability: str) -> dict:
    """Read the simulated purchase approval policy."""
    with Session(engine()) as db:
        return invoke(db, "approval_rules", capability, {})


@mcp.tool()
def approval_status(capability: str, approval_id: int) -> dict:
    """Manager-only: look up an approval request's status."""
    with Session(engine()) as db:
        return invoke(db, "approval_status", capability, {"approval_id": approval_id})


if __name__ == "__main__":
    serve(mcp)
