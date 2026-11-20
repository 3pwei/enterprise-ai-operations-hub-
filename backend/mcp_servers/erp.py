from sqlalchemy.orm import Session

from backend.db import engine
from backend.mcp_servers.runtime import create_server, serve
from backend.tool_service import invoke

mcp = create_server("ERP MCP", "erp")


@mcp.tool()
def inventory(capability: str, sku: str) -> dict:
    """Look up a product SKU, on-hand inventory and reorder point."""
    with Session(engine()) as db:
        return invoke(db, "inventory", capability, {"sku": sku})


@mcp.tool()
def order_status(capability: str, order_id: int) -> dict:
    """Look up a sales order's quantity and status by numeric ID."""
    with Session(engine()) as db:
        return invoke(db, "order_status", capability, {"order_id": order_id})


if __name__ == "__main__":
    serve(mcp)
