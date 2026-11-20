from sqlalchemy.orm import Session

from backend.db import engine
from backend.mcp_servers.runtime import create_server, serve
from backend.tool_service import invoke

mcp = create_server("Data MCP", "data")


@mcp.tool()
def production_kpi(capability: str) -> dict:
    """Calculate production total, passed units and yield percentage."""
    with Session(engine()) as db:
        return invoke(db, "production_kpi", capability, {})


@mcp.tool()
def quality_issues(capability: str) -> dict:
    """List quality anomalies with batch IDs and severity."""
    with Session(engine()) as db:
        return invoke(db, "quality_issues", capability, {})


@mcp.tool()
def sales_analysis(capability: str) -> dict:
    """Compute sales order count, total units and revenue."""
    with Session(engine()) as db:
        return invoke(db, "sales_analysis", capability, {})


if __name__ == "__main__":
    serve(mcp)
