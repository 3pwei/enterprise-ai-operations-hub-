"""Versioned, bounded procurement rules and audited mock ERP edits."""
import json
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import demo
from backend.models import (
    ActiveProcurementRule,
    Audit,
    CatalogChange,
    DemoProduct,
    DemoRule,
    DemoWorkspace,
    ProcurementRule,
    Product,
    ProductRevision,
    PurchaseOrder,
    SalesOrder,
    User,
)


class CatalogError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


def change(db: Session, user: User, action: str, target: str,
           before: dict, after: dict) -> None:
    db.add(CatalogChange(workspace_id=demo.workspace_id(db, user), actor_id=user.id,
             action=action, target=target, before_json=json.dumps(before, ensure_ascii=False),
             after_json=json.dumps(after, ensure_ascii=False)))


def require_manager(user: User, db: Session | None = None) -> None:
    if user.role != "manager":
        if db is not None:
            db.add(Audit(actor_id=user.id, tool="catalog.write", outcome="denied"))
            db.commit()
        raise CatalogError(403, "Manager role required")


def active_rule(db: Session, user: User | None = None, *, lock: bool = False) -> ProcurementRule:
    scope = demo.workspace_id(db, user) if user else None
    if scope:
        query = select(DemoWorkspace).where(DemoWorkspace.id == scope)
        workspace = db.scalar(query.with_for_update() if lock else query)
        if workspace is None:
            raise CatalogError(404, "Demo workspace missing")
        rule = db.get(ProcurementRule, workspace.active_rule_id)
        if rule is None:
            raise CatalogError(503, "Procurement rule is missing")
        return rule
    pointer = db.scalar(select(ActiveProcurementRule).where(ActiveProcurementRule.id == 1)
                        .with_for_update() if lock else select(ActiveProcurementRule).where(ActiveProcurementRule.id == 1))
    if pointer is None:
        raise CatalogError(503, "Procurement rule is not initialized")
    rule = db.get(ProcurementRule, pointer.rule_id)
    if rule is None:
        raise CatalogError(503, "Procurement rule is missing")
    return rule


def calculate(rule: ProcurementRule, *, reorder: int, demand: int, stock: int, inbound: int) -> int:
    if rule.formula not in ("standard", "safety_stock") or min(reorder, demand, stock, inbound, rule.safety_stock) < 0:
        raise ValueError("Invalid procurement inputs or rule")
    extra = rule.safety_stock if rule.formula == "safety_stock" else 0
    return max(0, reorder + extra + demand - stock - inbound)


def rule_dict(rule: ProcurementRule) -> dict:
    return {"id": rule.id, "formula": rule.formula, "safety_stock": rule.safety_stock,
            "expression": "max(0, reorder_point + " +
            ("safety_stock + " if rule.formula == "safety_stock" else "") +
            "open_sales - inventory - inbound)", "author_id": rule.author_id,
            "created_at": rule.created_at.isoformat() if rule.created_at else None}


def revision(db: Session, product_id: int, *, lock: bool = False) -> ProductRevision:
    query = select(ProductRevision).where(ProductRevision.product_id == product_id)
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise CatalogError(503, "Product revision is missing")
    return row


def product(db: Session, sku: str, user: User | None = None, *, lock: bool = False) -> Product:
    scope = demo.workspace_id(db, user) if user else None
    if scope:
        query = select(Product).join(DemoProduct, DemoProduct.product_id == Product.id).where(
            DemoProduct.workspace_id == scope, DemoProduct.display_sku == sku)
    else:
        query = select(Product).where(Product.sku == sku)
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise CatalogError(404, "Unknown SKU")
    return row


def edit_product(db: Session, user: User, sku: str, *, name: str, inventory: int,
                 reorder_point: int, create: bool = False) -> Product:
    require_manager(user, db)
    scope = demo.workspace_id(db, user)
    try:
        row = product(db, sku, user, lock=True)
    except CatalogError as exc:
        if exc.status != 404:
            raise
        row = None
    if create:
        if row is not None:
            raise CatalogError(409, "SKU already exists")
        demo.require_quota(db, user, "product")
        from uuid import uuid4
        row = Product(sku="D-" + uuid4().hex if scope else sku, name=name,
                      inventory=inventory, reorder_point=reorder_point)
        db.add(row)
        db.flush()
        db.add(ProductRevision(product_id=row.id, revision=0))
        if scope:
            db.add(DemoProduct(product_id=row.id, workspace_id=scope, display_sku=sku))
    else:
        if row is None:
            raise CatalogError(404, "Unknown SKU")
        before = {"name": row.name, "inventory": row.inventory,
                  "reorder_point": row.reorder_point}
        row.name, row.inventory, row.reorder_point = name, inventory, reorder_point
        revision(db, row.id, lock=True).revision += 1
        change(db, user, "product.update", sku, before,
               {"name": name, "inventory": inventory, "reorder_point": reorder_point})
    if create:
        change(db, user, "product.create", sku, {},
               {"name": name, "inventory": inventory, "reorder_point": reorder_point})
    db.add(Audit(actor_id=user.id, tool="catalog.product.create" if create else "catalog.product.update", outcome="ok"))
    db.commit()
    return row


def add_order(db: Session, user: User, *, sku: str, kind: str, quantity: int) -> None:
    require_manager(user, db)
    demo.require_quota(db, user, "order")
    row = product(db, sku, user, lock=True)
    revision(db, row.id, lock=True).revision += 1
    if kind == "sale":
        db.add(SalesOrder(product_id=row.id, quantity=quantity, unit_price=0,
                          status="open", ordered_on=date.today()))
    else:
        db.add(PurchaseOrder(product_id=row.id, quantity=quantity, status="pending"))
    change(db, user, "order.create", sku, {}, {"kind": kind, "quantity": quantity})
    db.add(Audit(actor_id=user.id, tool="catalog.order.add", outcome="ok"))
    db.commit()


def preview(db: Session, sku: str, user: User, *, formula: str, safety_stock: int) -> dict:
    if formula == "standard" and safety_stock != 0:
        raise CatalogError(422, "Standard formula requires zero safety stock")
    row = product(db, sku, user)
    sales = db.scalars(select(SalesOrder).where(SalesOrder.product_id == row.id,
                                                SalesOrder.status == "open")).all()
    purchases = db.scalars(select(PurchaseOrder).where(PurchaseOrder.product_id == row.id,
                     PurchaseOrder.status.in_(["pending", "approved"]))).all()
    candidate = ProcurementRule(formula=formula, safety_stock=safety_stock)
    demand = sum(o.quantity for o in sales)
    inbound = sum(o.quantity for o in purchases)
    return {"sku": sku, "inventory": row.inventory, "reorder_point": row.reorder_point,
            "open_sales": demand, "inbound": inbound, "formula": formula,
            "safety_stock": safety_stock,
            "quantity": calculate(candidate, reorder=row.reorder_point, demand=demand,
                                  stock=row.inventory, inbound=inbound)}


def publish(db: Session, user: User, *, formula: str, safety_stock: int,
            expected_rule_id: int) -> dict:
    require_manager(user, db)
    if (formula not in ("standard", "safety_stock") or safety_stock < 0 or safety_stock > 100000
            or (formula == "standard" and safety_stock != 0)):
        raise CatalogError(422, "Invalid rule")
    demo.require_quota(db, user, "rule")
    scope = demo.workspace_id(db, user)
    if scope:
        workspace = db.scalar(select(DemoWorkspace).where(DemoWorkspace.id == scope).with_for_update())
        if workspace is None or workspace.active_rule_id != expected_rule_id:
            raise CatalogError(409, "Active rule changed; preview again")
    else:
        pointer = db.scalar(select(ActiveProcurementRule).where(ActiveProcurementRule.id == 1).with_for_update())
        if pointer is None or pointer.rule_id != expected_rule_id:
            raise CatalogError(409, "Active rule changed; preview again")
    rule = ProcurementRule(formula=formula, safety_stock=safety_stock, author_id=user.id,
                           created_at=datetime.now(UTC))
    db.add(rule)
    db.flush()
    if scope:
        assert workspace is not None
        workspace.active_rule_id = rule.id
        db.add(DemoRule(rule_id=rule.id, workspace_id=scope))
    else:
        assert pointer is not None
        pointer.rule_id = rule.id
    change(db, user, "rule.publish", str(rule.id),
           {"rule_id": expected_rule_id}, rule_dict(rule))
    db.add(Audit(actor_id=user.id, tool="catalog.rule.publish", outcome="ok"))
    db.commit()
    return rule_dict(rule)


def products(db: Session, user: User) -> list[dict]:
    scope = demo.workspace_id(db, user)
    if scope:
        rows = [(row, sku) for row, sku in db.execute(select(Product, DemoProduct.display_sku).join(
            DemoProduct, DemoProduct.product_id == Product.id).where(
            DemoProduct.workspace_id == scope).order_by(DemoProduct.display_sku)).all()]
    else:
        rows = [(row, row.sku) for row in db.scalars(select(Product).where(
            ~Product.sku.like("D-%")).order_by(Product.id)).all()]
    return [{"sku": sku, "name": row.name, "inventory": row.inventory,
             "reorder_point": row.reorder_point, "revision": revision(db, row.id).revision}
            for row, sku in rows]


def rules(db: Session, user: User) -> dict:
    scope = demo.workspace_id(db, user)
    if scope:
        query = select(ProcurementRule).join(DemoRule, DemoRule.rule_id == ProcurementRule.id).where(
            DemoRule.workspace_id == scope).order_by(ProcurementRule.id.desc())
    else:
        query = select(ProcurementRule).where(~ProcurementRule.id.in_(
            select(DemoRule.rule_id))).order_by(ProcurementRule.id.desc())
    return {"active": rule_dict(active_rule(db, user)),
            "versions": [rule_dict(row) for row in db.scalars(query).all()]}


def changes(db: Session, user: User) -> list[dict]:
    scope = demo.workspace_id(db, user)
    query = select(CatalogChange).where(CatalogChange.workspace_id == scope if scope else
                                         CatalogChange.workspace_id.is_(None))
    rows = db.scalars(query.order_by(CatalogChange.id.desc()).limit(100)).all()
    return [{"id": row.id, "actor_id": row.actor_id, "action": row.action,
             "target": row.target, "before": json.loads(row.before_json),
             "after": json.loads(row.after_json), "created_at": row.created_at.isoformat()}
            for row in rows]
