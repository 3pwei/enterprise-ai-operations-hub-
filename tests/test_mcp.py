import asyncio

import pytest
from sqlalchemy.orm import Session

from backend.db import engine
from backend.mcp_client import call_tool
from backend.models import User
from backend.security import issue_capability
from backend.tool_service import invoke


@pytest.mark.parametrize("tool,params,source", [
    ("production_kpi", {}, "data.batches"),
    ("quality_issues", {}, "data.quality_issues"),
    ("sales_analysis", {}, "data.sales_orders"),
    ("inventory", {"sku": "P-100"}, "erp.products"),
    ("order_status", {"order_id": 1}, "erp.sales_orders"),
    ("approval_rules", {}, "eip.policy"),
    ("approval_status", {"approval_id": 1}, "eip.approvals"),
])
def test_every_mcp_tool(client, tool, params, source):
    with Session(engine()) as db:
        token = issue_capability(db.get(User, 2))
    result = asyncio.run(call_tool(tool, token, params))
    assert result["source"] == source
    assert "data" in result


def test_mcp_enforces_role_signature_and_validation(client):
    with Session(engine()) as db:
        analyst_token = issue_capability(db.get(User, 1))
        with pytest.raises(PermissionError):
            invoke(db, "approval_status", analyst_token, {"approval_id": 1})
        with pytest.raises(PermissionError):
            invoke(db, "inventory", "tampered", {"sku": "P-100"})
        with pytest.raises(ValueError):
            invoke(db, "inventory", analyst_token, {"sku": "x' OR 1=1 --"})


def test_seed_idempotent(client):
    from sqlalchemy import func, select

    from backend.models import Product
    from backend.seed import initialize
    initialize()
    with Session(engine()) as db:
        assert db.scalar(select(func.count()).select_from(Product)) == 2
