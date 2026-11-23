from datetime import date

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.db import Base, engine
from backend.models import (
    ActiveProcurementRule,
    Approval,
    Batch,
    ProcurementRule,
    Product,
    ProductionLine,
    ProductRevision,
    PurchaseOrder,
    QualityIssue,
    SalesOrder,
    User,
)


def seed(db: Session) -> None:
    if db.scalar(select(User.id).limit(1)) is not None:
        sync_postgres_sequences(db)
        # Add the Phase 04 demo SKU to databases initialized by an earlier phase.
        if db.scalar(select(Product.id).where(Product.sku == "P-300")) is None:
            db.add(Product(sku="P-300", name="Actuator Demo", inventory=4, reorder_point=20))
            db.commit()
        seed_rules(db)
        return
    db.add_all([User(id=1, name="Alice Analyst", role="analyst", active=True),
                User(id=2, name="Ming Manager", role="manager", active=True)])
    db.add_all([Product(id=1, sku="P-100", name="Sensor Module", inventory=25, reorder_point=40),
                Product(id=2, sku="P-200", name="Controller", inventory=140, reorder_point=60),
                Product(id=3, sku="P-300", name="Actuator Demo", inventory=4, reorder_point=20)])
    db.add_all([ProductionLine(id=1, name="Line A"), ProductionLine(id=2, name="Line B")])
    # Explicit IDs do not create ORM relationship edges: flush parents before dependent rows.
    db.flush()
    db.add_all([SalesOrder(id=1, product_id=1, quantity=10, unit_price=200, status="open", ordered_on=date(2026, 11, 1)),
                SalesOrder(id=2, product_id=2, quantity=5, unit_price=500, status="fulfilled", ordered_on=date(2026, 11, 2))])
    db.add_all([PurchaseOrder(id=1, product_id=1, quantity=50, status="pending"),
                PurchaseOrder(id=2, product_id=2, quantity=80, status="approved")])
    db.add_all([Batch(id=1, line_id=1, product_id=1, produced=100, passed=92, produced_on=date(2026, 11, 1)),
                Batch(id=2, line_id=2, product_id=2, produced=200, passed=198, produced_on=date(2026, 11, 2))])
    db.flush()
    db.add(QualityIssue(id=1, batch_id=1, severity="high", description="Calibration drift", status="open"))
    db.add(Approval(id=1, requester_id=1, purchase_id=1, status="pending"))
    db.commit()
    sync_postgres_sequences(db)
    seed_rules(db)
    db.commit()


def seed_rules(db: Session) -> None:
    for product_id in db.scalars(select(Product.id)).all():
        if db.get(ProductRevision, product_id) is None:
            db.add(ProductRevision(product_id=product_id, revision=0))
    if db.get(ActiveProcurementRule, 1) is None:
        rule = ProcurementRule(formula="standard", safety_stock=0, author_id=2)
        db.add(rule)
        db.flush()
        db.add(ActiveProcurementRule(id=1, rule_id=rule.id))
    db.commit()


def sync_postgres_sequences(db: Session) -> None:
    """Fixed demo seed IDs do not advance PostgreSQL SERIAL sequences."""
    if db.get_bind().dialect.name != "postgresql":
        return
    for table in ("users", "products", "sales_orders", "purchase_orders", "approvals"):
        # Table names are internal fixed constants, never user inputs.
        db.execute(text(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
            f"GREATEST((SELECT COALESCE(MAX(id), 1) FROM {table}), "
            f"(SELECT last_value FROM {table}_id_seq)))"
        ))


def initialize() -> None:
    Base.metadata.create_all(engine())
    with Session(engine()) as db:
        seed(db)
