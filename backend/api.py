from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend import catalog, demo, workflow
from backend.agent import respond
from backend.config import settings
from backend.db import session
from backend.models import Audit, User, Workflow
from backend.security import credential_user, issue_capability
from backend.seed import initialize


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize()
    yield


app = FastAPI(title="Enterprise AI Operations Hub", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=1000)


class WorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=6, max_length=1000)


class ProductRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str = Field(pattern=r"^P-[0-9]{1,8}$")
    name: str = Field(min_length=1, max_length=100)
    inventory: int = Field(ge=0, le=1000000)
    reorder_point: int = Field(ge=0, le=1000000)


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    inventory: int = Field(ge=0, le=1000000)
    reorder_point: int = Field(ge=0, le=1000000)


class OrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str = Field(pattern=r"^P-[0-9]{1,8}$")
    kind: Literal["sale", "inbound"]
    quantity: int = Field(ge=1, le=1000000)


class RuleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    formula: Literal["standard", "safety_stock"]
    safety_stock: int = Field(ge=0, le=100000)


class RulePreview(RuleRequest):
    sku: str = Field(pattern=r"^P-[0-9]{1,8}$")


class RulePublish(RuleRequest):
    expected_rule_id: int = Field(ge=1)


def catalog_failure(error: catalog.CatalogError) -> HTTPException:
    return HTTPException(error.status, str(error))


def workflow_failure(error: workflow.WorkflowError) -> HTTPException:
    return HTTPException(error.status_code, str(error))


@app.get("/api/demo/config")
def demo_config() -> dict:
    return {"public_demo_mode": settings().public_demo_mode}


def set_demo_cookie(response: Response, workspace: str, role: str) -> None:
    response.set_cookie(demo.COOKIE_NAME, demo.cookie(workspace, role), max_age=demo.MAX_AGE,
                        httponly=True, secure=settings().demo_cookie_secure,
                        samesite="strict", path="/")


@app.post("/api/demo/session")
def create_demo_session(response: Response, db: Session = Depends(session)) -> dict:
    if not settings().public_demo_mode:
        raise HTTPException(404, "Public demo is disabled")
    workspace = demo.create(db)
    set_demo_cookie(response, workspace, "analyst")
    return {"role": "analyst", "expires_in_seconds": demo.MAX_AGE}


class DemoRole(BaseModel):
    role: Literal["analyst", "manager"]


@app.post("/api/demo/role")
def switch_demo_role(body: DemoRole, response: Response,
                     user: User = Depends(credential_user), db: Session = Depends(session)) -> dict:
    scope = demo.workspace_id(db, user)
    if scope is None or not settings().public_demo_mode:
        raise HTTPException(404, "Public demo is disabled")
    set_demo_cookie(response, scope, body.role)
    return {"role": body.role}


@app.post("/api/workflows")
async def create_workflow(body: WorkflowRequest, user: User = Depends(credential_user)) -> dict:
    try:
        return await workflow.run(workflow.start(user, body.message), user)
    except workflow.WorkflowError as exc:
        raise workflow_failure(exc) from exc


@app.get("/api/workflows")
def list_workflows(user: User = Depends(credential_user), db: Session = Depends(session)) -> list[dict]:
    query = select(Workflow).order_by(Workflow.updated_at.desc())
    scope = demo.workspace_id(db, user)
    if scope and user.role == "manager":
        query = query.where(Workflow.owner_id.in_(select(demo.DemoMember.user_id).where(
            demo.DemoMember.workspace_id == scope)))
    elif scope or user.role != "manager":
        query = query.where(Workflow.owner_id == user.id)
    else:
        query = query.where(~Workflow.owner_id.in_(select(demo.DemoMember.user_id)))
    return [workflow.snapshot(db, flow) for flow in db.scalars(query).all()]


@app.get("/api/workflows/{workflow_id}")
def get_workflow(workflow_id: str, user: User = Depends(credential_user),
                 db: Session = Depends(session)) -> dict:
    try:
        return workflow.snapshot(db, workflow.load(db, workflow_id, user))
    except workflow.WorkflowError as exc:
        raise workflow_failure(exc) from exc


@app.post("/api/workflows/{workflow_id}/retry")
async def retry_workflow(workflow_id: str, user: User = Depends(credential_user)) -> dict:
    try:
        workflow.retry(workflow_id, user)
        return await workflow.run(workflow_id, user)
    except workflow.WorkflowError as exc:
        raise workflow_failure(exc) from exc


@app.post("/api/workflows/{workflow_id}/cancel")
def cancel_workflow(workflow_id: str, user: User = Depends(credential_user)) -> dict:
    try:
        return workflow.cancel(workflow_id, user)
    except workflow.WorkflowError as exc:
        raise workflow_failure(exc) from exc


@app.post("/api/workflows/{workflow_id}/submit")
def submit_workflow(workflow_id: str, user: User = Depends(credential_user)) -> dict:
    try:
        return workflow.submit(workflow_id, user)
    except workflow.WorkflowError as exc:
        raise workflow_failure(exc) from exc


@app.get("/api/workflows/{workflow_id}/approval")
async def workflow_approval(workflow_id: str, user: User = Depends(credential_user)) -> dict:
    try:
        return await workflow.approval_status(workflow_id, user)
    except workflow.WorkflowError as exc:
        raise workflow_failure(exc) from exc


@app.get("/health")
def health(db: Session = Depends(session)) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok", "mode": "llm" if settings().openai_api_key else "mock"}


@app.get("/api/me")
def me(user: User = Depends(credential_user)) -> dict:
    return {"id": user.id, "name": user.name, "role": user.role}


@app.get("/api/products")
def products(user: User = Depends(credential_user), db: Session = Depends(session)) -> list[dict]:
    return catalog.products(db, user)


@app.post("/api/products", status_code=201)
def create_product(body: ProductRequest, user: User = Depends(credential_user),
                   db: Session = Depends(session)) -> dict:
    try:
        catalog.edit_product(db, user, body.sku, name=body.name,
                     inventory=body.inventory, reorder_point=body.reorder_point, create=True)
        return {"sku": body.sku, "revision": 0}
    except catalog.CatalogError as exc:
        raise catalog_failure(exc) from exc


@app.put("/api/products/{sku}")
def update_product(sku: str, body: ProductUpdate, user: User = Depends(credential_user),
                   db: Session = Depends(session)) -> dict:
    try:
        row = catalog.edit_product(db, user, sku, name=body.name,
                     inventory=body.inventory, reorder_point=body.reorder_point)
        return {"sku": sku, "revision": catalog.revision(db, row.id).revision}
    except catalog.CatalogError as exc:
        raise catalog_failure(exc) from exc


@app.post("/api/orders", status_code=201)
def create_order(body: OrderRequest, user: User = Depends(credential_user),
                 db: Session = Depends(session)) -> dict:
    try:
        catalog.add_order(db, user, sku=body.sku, kind=body.kind, quantity=body.quantity)
        return {"sku": body.sku, "kind": body.kind, "quantity": body.quantity}
    except catalog.CatalogError as exc:
        raise catalog_failure(exc) from exc


@app.get("/api/rules")
def rules(user: User = Depends(credential_user), db: Session = Depends(session)) -> dict:
    return catalog.rules(db, user)


@app.get("/api/catalog/changes")
def catalog_changes(user: User = Depends(credential_user), db: Session = Depends(session)) -> list[dict]:
    return catalog.changes(db, user)


@app.post("/api/rules/preview")
def preview_rule(body: RulePreview, user: User = Depends(credential_user),
                 db: Session = Depends(session)) -> dict:
    try:
        catalog.require_manager(user, db)
        return catalog.preview(db, body.sku, user, formula=body.formula,
                               safety_stock=body.safety_stock)
    except catalog.CatalogError as exc:
        raise catalog_failure(exc) from exc


@app.post("/api/rules", status_code=201)
def publish_rule(body: RulePublish, user: User = Depends(credential_user),
                 db: Session = Depends(session)) -> dict:
    try:
        return catalog.publish(db, user, formula=body.formula,
             safety_stock=body.safety_stock, expected_rule_id=body.expected_rule_id)
    except catalog.CatalogError as exc:
        raise catalog_failure(exc) from exc


@app.get("/api/dashboard")
async def dashboard(user: User = Depends(credential_user)) -> dict:
    if settings().public_demo_mode:
        raise HTTPException(403, "Dashboard is unavailable in public simulation")
    token = issue_capability(user)
    from backend.mcp_client import call_tool
    kpi = await call_tool("production_kpi", token, {})
    issues = await call_tool("quality_issues", token, {})
    sales = await call_tool("sales_analysis", token, {})
    return {"kpi": kpi, "issues": issues, "sales": sales}


@app.post("/api/chat")
async def chat(body: ChatRequest, user: User = Depends(credential_user), db: Session = Depends(session)) -> dict:
    if settings().public_demo_mode:
        raise HTTPException(403, "Chat is unavailable in public simulation")
    try:
        return await respond(body.message, issue_capability(user), user.role)
    except PermissionError as exc:
        db.add(Audit(actor_id=user.id, tool="approval_status", outcome="denied"))
        db.commit()
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        # No transport details or credentials in response.
        raise HTTPException(502, "Agent or MCP service unavailable") from exc
