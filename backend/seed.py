from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db import Base, engine
from backend.models import (
    Approval,
    Batch,
    Product,
    ProductionLine,
    PurchaseOrder,
    QualityIssue,
    SalesOrder,
    User,
)


def seed(db: Session) -> None:
    if db.scalar(select(User.id).limit(1)) is not None:
        return
    db.add_all([User(id=1, name="Alice Analyst", role="analyst", active=True),
                User(id=2, name="Ming Manager", role="manager", active=True)])
    db.add_all([Product(id=1, sku="P-100", name="Sensor Module", inventory=25, reorder_point=40),
                Product(id=2, sku="P-200", name="Controller", inventory=140, reorder_point=60)])
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


def initialize() -> None:
    Base.metadata.create_all(engine())
    with Session(engine()) as db:
        seed(db)
