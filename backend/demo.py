"""Isolated, short-lived public simulation sessions (never real ERP actions)."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models import (
    Approval,
    Audit,
    CatalogChange,
    DemoMember,
    DemoProduct,
    DemoRule,
    DemoWorkspace,
    ProcurementRule,
    Product,
    ProductRevision,
    PurchaseOrder,
    SalesOrder,
    User,
    Workflow,
    WorkflowBasis,
    WorkflowEvent,
    WorkflowSubmission,
)

COOKIE_NAME = "hub_demo"
MAX_AGE = 60 * 60 * 24


def serializer() -> URLSafeTimedSerializer:
    secret = settings().mcp_signing_key
    if len(secret) < 32:
        raise RuntimeError("MCP_SIGNING_KEY must be at least 32 characters")
    return URLSafeTimedSerializer(secret, salt="public-demo-session-v1")


def workspace_id(db: Session, user: User) -> str | None:
    member = db.get(DemoMember, user.id)
    return member.workspace_id if member else None


def create(db: Session) -> str:
    purge_expired(db)
    if (db.scalar(select(func.count()).select_from(DemoWorkspace)) or 0) >= 500:
        raise HTTPException(429, "Demo capacity reached; try later")
    analyst = User(name="Demo Analyst", role="analyst", active=True)
    manager = User(name="Demo Manager", role="manager", active=True)
    db.add_all([analyst, manager])
    db.flush()
    rule = ProcurementRule(formula="standard", safety_stock=0, author_id=manager.id)
    db.add(rule)
    db.flush()
    workspace = DemoWorkspace(id=str(uuid4()), active_rule_id=rule.id)
    db.add(workspace)
    db.flush()
    db.add_all([DemoMember(user_id=analyst.id, workspace_id=workspace.id),
                DemoMember(user_id=manager.id, workspace_id=workspace.id)])
    db.add(DemoRule(rule_id=rule.id, workspace_id=workspace.id))
    for sku, name, stock, threshold in (
        ("P-100", "Sensor Module", 25, 40),
        ("P-300", "Actuator Demo", 4, 20),
    ):
        product = Product(sku="D-" + uuid4().hex, name=name,
                          inventory=stock, reorder_point=threshold)
        db.add(product)
        db.flush()
        db.add(DemoProduct(product_id=product.id, workspace_id=workspace.id, display_sku=sku))
        db.add(ProductRevision(product_id=product.id, revision=0))
        if sku == "P-100":
            db.add(SalesOrder(product_id=product.id, quantity=10, unit_price=200,
                              status="open", ordered_on=datetime.now(UTC).date()))
            db.add(PurchaseOrder(product_id=product.id, quantity=50, status="pending"))
    db.commit()
    return workspace.id


def purge_expired(db: Session) -> int:
    """Remove up to 20 expired workspaces when a new visitor starts a session."""
    cutoff = datetime.now(UTC) - timedelta(seconds=MAX_AGE)
    expired = db.scalars(select(DemoWorkspace).where(DemoWorkspace.created_at < cutoff)
                         .order_by(DemoWorkspace.created_at).limit(20)).all()
    for workspace in expired:
        member_ids = db.scalars(select(DemoMember.user_id).where(
            DemoMember.workspace_id == workspace.id)).all()
        product_ids = db.scalars(select(DemoProduct.product_id).where(
            DemoProduct.workspace_id == workspace.id)).all()
        rule_ids = db.scalars(select(DemoRule.rule_id).where(
            DemoRule.workspace_id == workspace.id)).all()
        flow_ids = db.scalars(select(Workflow.id).where(Workflow.owner_id.in_(member_ids))).all()
        purchase_ids = db.scalars(select(PurchaseOrder.id).where(
            PurchaseOrder.product_id.in_(product_ids))).all()
        db.execute(delete(WorkflowSubmission).where(WorkflowSubmission.workflow_id.in_(flow_ids)))
        db.execute(delete(WorkflowBasis).where(WorkflowBasis.workflow_id.in_(flow_ids)))
        db.execute(delete(WorkflowEvent).where(WorkflowEvent.workflow_id.in_(flow_ids)))
        db.execute(delete(Workflow).where(Workflow.id.in_(flow_ids)))
        db.execute(delete(Approval).where(Approval.purchase_id.in_(purchase_ids)))
        db.execute(delete(SalesOrder).where(SalesOrder.product_id.in_(product_ids)))
        db.execute(delete(PurchaseOrder).where(PurchaseOrder.id.in_(purchase_ids)))
        db.execute(delete(ProductRevision).where(ProductRevision.product_id.in_(product_ids)))
        db.execute(delete(DemoProduct).where(DemoProduct.workspace_id == workspace.id))
        db.execute(delete(Product).where(Product.id.in_(product_ids)))
        db.execute(delete(DemoRule).where(DemoRule.workspace_id == workspace.id))
        db.execute(delete(DemoMember).where(DemoMember.workspace_id == workspace.id))
        db.execute(delete(CatalogChange).where(CatalogChange.workspace_id == workspace.id))
        db.execute(delete(DemoWorkspace).where(DemoWorkspace.id == workspace.id))
        db.execute(delete(ProcurementRule).where(ProcurementRule.id.in_(rule_ids)))
        db.execute(delete(Audit).where(Audit.actor_id.in_(member_ids)))
        db.execute(delete(User).where(User.id.in_(member_ids)))
    if expired:
        db.commit()
    return len(expired)


def cookie(workspace: str, role: str) -> str:
    return serializer().dumps({"workspace": workspace, "role": role})


def authenticate(db: Session, value: str | None) -> User:
    try:
        data = serializer().loads(value or "", max_age=MAX_AGE)
    except (BadSignature, SignatureExpired) as exc:
        raise HTTPException(401, "Start a new demo session") from exc
    if not isinstance(data, dict) or data.get("role") not in ("analyst", "manager"):
        raise HTTPException(401, "Invalid demo session")
    workspace = db.get(DemoWorkspace, data.get("workspace"))
    if workspace is None or workspace.created_at.replace(tzinfo=UTC) < datetime.now(UTC) - timedelta(seconds=MAX_AGE):
        raise HTTPException(401, "Demo session expired")
    user = db.scalar(select(User).join(DemoMember, DemoMember.user_id == User.id).where(
        DemoMember.workspace_id == workspace.id, User.role == data["role"], User.active.is_(True)))
    if user is None:
        raise HTTPException(401, "Demo account unavailable")
    return user


def require_quota(db: Session, user: User, resource: str) -> None:
    scope = workspace_id(db, user)
    if scope is None:
        return
    if resource == "product":
        count = db.scalar(select(func.count()).select_from(DemoProduct).where(DemoProduct.workspace_id == scope))
        limit = 12
    elif resource == "rule":
        count = db.scalar(select(func.count()).select_from(DemoRule).where(DemoRule.workspace_id == scope))
        limit = 12
    elif resource == "workflow":
        ids = select(DemoMember.user_id).where(DemoMember.workspace_id == scope)
        count = db.scalar(select(func.count()).select_from(Workflow).where(Workflow.owner_id.in_(ids)))
        limit = 30
    else:
        ids = select(DemoProduct.product_id).where(DemoProduct.workspace_id == scope)
        count = db.scalar(select(func.count()).select_from(SalesOrder).where(SalesOrder.product_id.in_(ids)))
        count = (count or 0) + (db.scalar(select(func.count()).select_from(PurchaseOrder).where(
            PurchaseOrder.product_id.in_(ids))) or 0)
        limit = 50
    if (count or 0) >= limit:
        raise HTTPException(429, "Demo session limit reached")
