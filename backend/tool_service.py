from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend import catalog, demo
from backend.models import Approval, Audit, Batch, PurchaseOrder, QualityIssue, SalesOrder
from backend.security import verify_capability


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InventoryArgs(Args):
    sku: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9-]+$")


class OrderArgs(Args):
    order_id: int = Field(ge=1, le=2_147_483_647)


class ApprovalArgs(Args):
    approval_id: int = Field(ge=1, le=2_147_483_647)


ARG_TYPES: dict[str, type[Args]] = {
    "production_kpi": Args, "quality_issues": Args, "sales_analysis": Args,
    "inventory": InventoryArgs, "order_status": OrderArgs,
    "open_orders": InventoryArgs,
    "approval_rules": Args, "approval_status": ApprovalArgs,
}
SOURCES = {
    "production_kpi": "data.batches", "quality_issues": "data.quality_issues",
    "sales_analysis": "data.sales_orders", "inventory": "erp.products",
    "order_status": "erp.sales_orders", "approval_rules": "eip.policy",
    "open_orders": "erp.sales_orders+erp.purchase_orders",
    "approval_status": "eip.approvals",
}


def invoke(db: Session, tool: str, capability: str, params: dict[str, Any]) -> dict[str, Any]:
    if tool not in ARG_TYPES:
        raise ValueError("Unknown tool")
    actor = 0
    outcome = "denied"
    try:
        user = verify_capability(db, capability, manager_only=tool == "approval_status")
        actor = user.id
        args = ARG_TYPES[tool].model_validate(params)
        scope = demo.workspace_id(db, user)
        if scope and tool not in ("inventory", "open_orders", "approval_status", "approval_rules"):
            raise PermissionError("Tool not available in public simulation")
        outcome = "ok"
        result: dict[str, Any]
        if tool == "production_kpi":
            produced, passed = db.execute(select(func.sum(Batch.produced), func.sum(Batch.passed))).one()
            result = {"produced": produced or 0, "passed": passed or 0,
                      "yield_pct": round(100 * passed / produced, 2) if produced else 0}
        elif tool == "quality_issues":
            issues = db.scalars(select(QualityIssue).order_by(QualityIssue.id)).all()
            result = {"items": [{"id": i.id, "batch_id": i.batch_id, "severity": i.severity,
                                 "description": i.description, "status": i.status} for i in issues]}
        elif tool == "sales_analysis":
            quantity, revenue = db.execute(select(func.sum(SalesOrder.quantity),
                func.sum(SalesOrder.quantity * SalesOrder.unit_price))).one()
            result = {"order_count": db.scalar(select(func.count()).select_from(SalesOrder)),
                      "units": quantity or 0, "revenue": revenue or 0, "currency": "TWD"}
        elif tool == "inventory":
            sku = cast(InventoryArgs, args).sku
            try:
                product = catalog.product(db, sku, user)
            except catalog.CatalogError:
                product = None
            result = {"sku": sku, "inventory": product.inventory,
                      "reorder_point": product.reorder_point,
                      "below_reorder_point": product.inventory < product.reorder_point} if product else {"error": "not_found"}
        elif tool == "order_status":
            order = db.get(SalesOrder, cast(OrderArgs, args).order_id)
            result = {"order_id": order.id, "quantity": order.quantity,
                      "status": order.status} if order else {"error": "not_found"}
        elif tool == "open_orders":
            sku = cast(InventoryArgs, args).sku
            try:
                product = catalog.product(db, sku, user)
            except catalog.CatalogError:
                product = None
            if product is None:
                result = {"error": "not_found"}
            else:
                sales = db.scalars(select(SalesOrder).where(
                    SalesOrder.product_id == product.id, SalesOrder.status == "open"
                ).order_by(SalesOrder.id)).all()
                purchases = db.scalars(select(PurchaseOrder).where(
                    PurchaseOrder.product_id == product.id,
                    PurchaseOrder.status.in_(["pending", "approved"])
                ).order_by(PurchaseOrder.id)).all()
                result = {"sku": sku,
                          "open_sales": [{"id": o.id, "quantity": o.quantity} for o in sales],
                          "inbound_purchases": [{"id": o.id, "quantity": o.quantity,
                                                  "status": o.status} for o in purchases]}
        elif tool == "approval_rules":
            result = {"policy": "Demo purchase approval: manager review required for all pending requests.",
                      "version": "demo-1"}
        else:
            approval = db.get(Approval, cast(ApprovalArgs, args).approval_id)
            if scope and approval:
                purchase = db.get(PurchaseOrder, approval.purchase_id)
                from backend.models import DemoProduct
                mapping = db.get(DemoProduct, purchase.product_id) if purchase else None
                if mapping is None or mapping.workspace_id != scope:
                    approval = None
            result = {"approval_id": approval.id, "purchase_id": approval.purchase_id,
                      "status": approval.status} if approval else {"error": "not_found"}
        return {"source": SOURCES[tool], "data": result}
    except Exception:
        outcome = "error" if outcome == "ok" else "denied"
        raise
    finally:
        db.add(Audit(actor_id=actor, tool=tool, outcome=outcome))
        db.commit()
