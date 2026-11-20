from mcp.server.fastmcp import FastMCP
from sqlalchemy.orm import Session

from backend.db import engine
from backend.tool_service import invoke

mcp = FastMCP("ERP MCP")


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


@mcp.tool()
def open_orders(capability: str, sku: str) -> dict:
    """Look up unfulfilled sales and submitted pending/approved purchase orders for a SKU."""
    with Session(engine()) as db:
        return invoke(db, "open_orders", capability, {"sku": sku})


if __name__ == "__main__":
    mcp.run()
