from datetime import UTC, date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    inventory: Mapped[int] = mapped_column(Integer)
    reorder_point: Mapped[int] = mapped_column(Integer)


class SalesOrder(Base):
    __tablename__ = "sales_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    ordered_on: Mapped[date] = mapped_column(Date)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))


class ProductionLine(Base):
    __tablename__ = "production_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class Batch(Base):
    __tablename__ = "batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("production_lines.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    produced: Mapped[int] = mapped_column(Integer)
    passed: Mapped[int] = mapped_column(Integer)
    produced_on: Mapped[date] = mapped_column(Date)


class QualityIssue(Base):
    __tablename__ = "quality_issues"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"))
    severity: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20))


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"))
    status: Mapped[str] = mapped_column(String(20))


class Audit(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(Integer)
    tool: Mapped[str] = mapped_column(String(60))
    outcome: Mapped[str] = mapped_column(String(30))


class Workflow(Base):
    __tablename__ = "workflows"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    sku: Mapped[str] = mapped_column(String(40))
    request: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(30))
    inventory: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reorder_point: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open_sales: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inbound: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"))
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    agent: Mapped[str] = mapped_column(String(40))
    step: Mapped[str] = mapped_column(String(60))
    outcome: Mapped[str] = mapped_column(String(30))
    detail: Mapped[str] = mapped_column(Text)


class WorkflowSubmission(Base):
    __tablename__ = "workflow_submissions"
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), primary_key=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), unique=True)
    approval_id: Mapped[int] = mapped_column(ForeignKey("approvals.id"), unique=True)
