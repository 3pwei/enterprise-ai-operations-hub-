"""Compose smoke check: the API must reach all three network MCP services."""

import asyncio

from sqlalchemy.orm import Session

from backend.db import engine
from backend.mcp_client import call_tool
from backend.models import User
from backend.security import issue_capability


async def main() -> None:
    with Session(engine()) as db:
        manager = issue_capability(db.get(User, 2))
        analyst = issue_capability(db.get(User, 1))
    for name, params, source in (
        ("production_kpi", {}, "data.batches"),
        ("inventory", {"sku": "P-100"}, "erp.products"),
        ("approval_rules", {}, "eip.policy"),
    ):
        response = await call_tool(name, manager, params)
        assert response["source"] == source, response
    try:
        await call_tool("approval_status", analyst, {"approval_id": 1})
    except ValueError:
        pass
    else:
        raise AssertionError("EIP did not enforce the manager role")
    print("Three separate HTTP MCP services, tool calls, and role check: OK")


if __name__ == "__main__":
    asyncio.run(main())
