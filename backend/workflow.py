"""Durable, deterministic procurement workflow; model output never authorizes writes."""
import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from backend import catalog, demo
from backend.db import engine
from backend.mcp_client import call_tool
from backend.models import (
    Approval,
    Audit,
    PurchaseOrder,
    User,
    Workflow,
    WorkflowBasis,
    WorkflowEvent,
    WorkflowSubmission,
)
from backend.security import issue_capability

SKU = re.compile(r"\bP-\d+\b", re.IGNORECASE)


class WorkflowError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(message)


def event(db: Session, workflow: Workflow, actor: User, agent: str, step: str,
          outcome: str, detail: dict[str, Any] | None = None) -> None:
    db.add(WorkflowEvent(workflow_id=workflow.id, actor_id=actor.id, agent=agent, step=step,
                         outcome=outcome, detail=json.dumps(detail or {}, ensure_ascii=False)))


def audit(db: Session, actor: User, action: str, outcome: str) -> None:
    db.add(Audit(actor_id=actor.id, tool=action, outcome=outcome))


def load(db: Session, workflow_id: str, actor: User) -> Workflow:
    flow = db.get(Workflow, workflow_id)
    scope = demo.workspace_id(db, actor)
    owner = db.get(User, flow.owner_id) if flow else None
    owner_scope = demo.workspace_id(db, owner) if owner else None
    if flow is None or (scope != owner_scope if scope or owner_scope else False) or \
       (actor.role != "manager" and flow.owner_id != actor.id):
        raise WorkflowError(404, "Workflow not found")
    return flow


def snapshot(db: Session, flow: Workflow) -> dict[str, Any]:
    submission = db.get(WorkflowSubmission, flow.id)
    basis = db.get(WorkflowBasis, flow.id)
    owner = db.get(User, flow.owner_id)
    active = catalog.active_rule(db, owner)
    try:
        product = catalog.product(db, flow.sku, owner)
    except catalog.CatalogError:
        product = None
    current_revision = catalog.revision(db, product.id).revision if product else None
    stale = (flow.status == "awaiting_confirmation" and
             (basis is None or basis.rule_id != active.id or basis.product_revision != current_revision))
    events = db.scalars(select(WorkflowEvent).where(WorkflowEvent.workflow_id == flow.id)
                        .order_by(WorkflowEvent.id)).all()
    return {"id": flow.id, "owner_id": flow.owner_id, "sku": flow.sku,
            "request": flow.request, "status": flow.status, "inventory": flow.inventory,
            "reorder_point": flow.reorder_point, "open_sales": flow.open_sales,
            "inbound": flow.inbound, "quantity": flow.quantity, "error": flow.error,
            "purchase_id": submission.purchase_id if submission else None,
            "approval_id": submission.approval_id if submission else None,
            "rule_id": basis.rule_id if basis else None,
            "product_revision": basis.product_revision if basis else None,
            "stale": stale,
            "events": [{"id": e.id, "actor_id": e.actor_id, "agent": e.agent,
                        "step": e.step, "outcome": e.outcome, "detail": json.loads(e.detail)}
                       for e in events]}


def start(actor: User, message: str) -> str:
    matches = {match.group(0).upper() for match in SKU.finditer(message)}
    if len(matches) != 1 or not any(word in message.lower() for word in ("採購", "purchase", "procure", "補貨")):
        raise WorkflowError(422, "Specify one SKU and a procurement intent")
    sku = matches.pop()
    with Session(engine()) as db:
        demo.require_quota(db, actor, "workflow")
        flow = Workflow(id=str(uuid4()), owner_id=actor.id, sku=sku,
                        request=message, status="running", updated_at=datetime.now(UTC))
        db.add(flow)
        event(db, flow, actor, "router", "route_to_data_agent", "ok", {"sku": sku})
        audit(db, actor, "workflow.start", "ok")
        db.commit()
        return flow.id


async def _read(name: str, token: str, sku: str) -> dict[str, Any]:
    for attempt in range(2):
        try:
            result = await asyncio.wait_for(call_tool(name, token, {"sku": sku}), timeout=12)
            if not isinstance(result.get("data"), dict):
                raise TypeError("Invalid MCP response")
            return result
        except (TimeoutError, ValueError, TypeError, OSError):
            if attempt:
                raise
            await asyncio.sleep(0.2)
    raise RuntimeError("Unreachable")


async def run(workflow_id: str, actor: User) -> dict[str, Any]:
    with Session(engine()) as db:
        flow = load(db, workflow_id, actor)
        if flow.status != "running":
            raise WorkflowError(409, "Workflow is not running")
        sku = flow.sku
    try:
        token = issue_capability(actor)
        inventory = await _read("inventory", token, sku)
        orders = await _read("open_orders", token, sku)
        stock, pending = inventory["data"], orders["data"]
        if "error" in stock or "error" in pending:
            raise ValueError("Unknown SKU")
        on_hand = int(stock["inventory"])
        reorder = int(stock["reorder_point"])
        demand = sum(int(o["quantity"]) for o in pending["open_sales"])
        inbound = sum(int(o["quantity"]) for o in pending["inbound_purchases"])
        if min(on_hand, reorder, demand, inbound) < 0:
            raise ValueError("Invalid order quantities")
        with Session(engine()) as db:
            flow = load(db, workflow_id, actor)
            if flow.status != "running":
                return snapshot(db, flow)
            rule = catalog.active_rule(db, actor)
            product = catalog.product(db, sku, actor)
            product_revision = catalog.revision(db, product.id).revision
            gap = catalog.calculate(rule, reorder=reorder, demand=demand,
                                    stock=on_hand, inbound=inbound)
            db.add(WorkflowBasis(workflow_id=flow.id, product_revision=product_revision,
                                 rule_id=rule.id))
            event(db, flow, actor, "data_agent", "inventory", "ok",
                  {"source": inventory["source"], "output": stock})
            event(db, flow, actor, "data_agent", "open_orders", "ok",
                  {"source": orders["source"], "output": pending})
            event(db, flow, actor, "router", "handoff_to_procurement_agent", "ok")
            event(db, flow, actor, "procurement_agent", "calculate_gap", "ok",
                  {"rule": catalog.rule_dict(rule), "product_revision": product_revision,
                   "quantity": gap})
            flow.inventory, flow.reorder_point = on_hand, reorder
            flow.open_sales, flow.inbound, flow.quantity = demand, inbound, gap
            flow.error = None
            flow.status = "awaiting_confirmation" if gap else "no_gap"
            flow.updated_at = datetime.now(UTC)
            event(db, flow, actor, "procurement_agent", "draft", "ok",
                  {"quantity": gap, "requires_manager_confirmation": gap > 0})
            db.commit()
            return snapshot(db, flow)
    except Exception:  # noqa: BLE001 - persist failures without exposing MCP details
        with Session(engine()) as db:
            flow = load(db, workflow_id, actor)
            if flow.status == "running":
                flow.status, flow.error, flow.updated_at = "failed", "Data lookup failed; retry permitted", datetime.now(UTC)
                event(db, flow, actor, "data_agent", "lookup", "error",
                      {"message": "MCP unavailable or SKU invalid"})
                audit(db, actor, "workflow.run", "error")
                db.commit()
            return snapshot(db, flow)


def retry(workflow_id: str, actor: User) -> None:
    with Session(engine()) as db:
        flow = load(db, workflow_id, actor)
        stale = (flow.status == "running" and
                 flow.updated_at.replace(tzinfo=flow.updated_at.tzinfo or UTC)
                 < datetime.now(UTC) - timedelta(seconds=60))
        previous = flow.status
        if not stale and previous != "failed":
            raise WorkflowError(409, "Only failed or stale running workflows can be retried")
        query = update(Workflow).where(Workflow.id == workflow_id, Workflow.status == previous)
        if stale:
            query = query.where(Workflow.updated_at == flow.updated_at)
        if not cast(CursorResult[Any], db.execute(query.values(
                status="running", error=None, updated_at=datetime.now(UTC)))).rowcount:
            raise WorkflowError(409, "Workflow changed during retry")
        event(db, flow, actor, "router", "retry", "ok")
        audit(db, actor, "workflow.retry", "ok")
        db.commit()


def cancel(workflow_id: str, actor: User) -> dict[str, Any]:
    with Session(engine()) as db:
        flow = load(db, workflow_id, actor)
        count = cast(CursorResult[Any], db.execute(update(Workflow).where(Workflow.id == workflow_id,
                           Workflow.status.in_(["running", "failed", "awaiting_confirmation"]))
                           .values(status="cancelled", updated_at=datetime.now(UTC)))).rowcount
        if not count:
            audit(db, actor, "workflow.cancel", "denied")
            db.commit()
            raise WorkflowError(409, "Cannot cancel this workflow")
        db.refresh(flow)
        event(db, flow, actor, "router", "cancel", "ok")
        audit(db, actor, "workflow.cancel", "ok")
        db.commit()
        return snapshot(db, flow)


def submit(workflow_id: str, actor: User) -> dict[str, Any]:
    if actor.role != "manager":
        with Session(engine()) as db:
            load(db, workflow_id, actor)
            audit(db, actor, "workflow.submit", "denied")
            db.commit()
        raise WorkflowError(403, "Manager confirmation required")
    with Session(engine()) as db:
        flow = load(db, workflow_id, actor)
        existing = db.get(WorkflowSubmission, workflow_id)
        if existing:
            return snapshot(db, flow)  # Idempotent duplicate confirmation.
        count = cast(CursorResult[Any], db.execute(update(Workflow).where(Workflow.id == workflow_id,
                           Workflow.status == "awaiting_confirmation", Workflow.quantity > 0)
                           .values(status="submitted", updated_at=datetime.now(UTC)))).rowcount
        if not count:
            audit(db, actor, "workflow.submit", "denied")
            db.commit()
            raise WorkflowError(409, "Draft is not awaiting confirmation")
        # All writers of the mock ERP rows lock the product first. Check the
        # rule pointer and revision before creating any side effects.
        try:
            product = catalog.product(db, flow.sku, actor, lock=True)
        except catalog.CatalogError:
            product = None
        if product is None or flow.quantity is None:
            raise WorkflowError(409, "Product missing")
        basis = db.get(WorkflowBasis, flow.id)
        rule = catalog.active_rule(db, actor, lock=True)
        if basis is None or basis.rule_id != rule.id or basis.product_revision != catalog.revision(db, product.id, lock=True).revision:
            raise WorkflowError(409, "Draft data or rule changed; create a new draft")
        # Recheck supply and demand in the same transaction; another submitted draft
        # or a changed ERP record makes an old approval screen unsafe to confirm.
        from backend.models import SalesOrder
        sales = db.scalars(select(SalesOrder).where(
            SalesOrder.product_id == product.id, SalesOrder.status == "open")).all()
        purchases = db.scalars(select(PurchaseOrder).where(
            PurchaseOrder.product_id == product.id,
            PurchaseOrder.status.in_(["pending", "approved"]))).all()
        current_gap = catalog.calculate(rule, reorder=product.reorder_point,
                demand=sum(o.quantity for o in sales), stock=product.inventory,
                inbound=sum(o.quantity for o in purchases))
        if current_gap != flow.quantity:
            raise WorkflowError(409, "ERP quantities changed; create a new draft")
        purchase = PurchaseOrder(product_id=product.id, quantity=flow.quantity, status="pending")
        db.add(purchase)
        db.flush()
        approval = Approval(requester_id=flow.owner_id, purchase_id=purchase.id, status="pending")
        db.add(approval)
        db.flush()
        db.add(WorkflowSubmission(workflow_id=workflow_id, purchase_id=purchase.id,
                                  approval_id=approval.id))
        catalog.revision(db, product.id, lock=True).revision += 1
        event(db, flow, actor, "procurement_agent", "human_confirmed_submission", "ok",
              {"purchase_id": purchase.id, "approval_id": approval.id})
        audit(db, actor, "workflow.submit", "ok")
        db.commit()
        return snapshot(db, flow)


async def approval_status(workflow_id: str, actor: User) -> dict[str, Any]:
    if actor.role != "manager":
        with Session(engine()) as db:
            load(db, workflow_id, actor)
            audit(db, actor, "workflow.approval_status", "denied")
            db.commit()
        raise WorkflowError(403, "Manager role required")
    with Session(engine()) as db:
        flow = load(db, workflow_id, actor)
        submission = db.get(WorkflowSubmission, flow.id)
        if submission is None:
            raise WorkflowError(409, "Submission required")
        approval_id = submission.approval_id
    try:
        result = await asyncio.wait_for(call_tool("approval_status", issue_capability(actor),
                                                   {"approval_id": approval_id}), timeout=12)
    except Exception as exc:
        raise WorkflowError(502, "EIP status unavailable") from exc
    with Session(engine()) as db:
        flow = load(db, workflow_id, actor)
        event(db, flow, actor, "procurement_agent", "approval_status", "ok",
              {"source": result["source"], "output": result["data"]})
        db.commit()
    return result
