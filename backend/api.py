from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend import workflow
from backend.agent import respond
from backend.config import settings
from backend.db import session
from backend.models import Audit, Product, User, Workflow
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


def workflow_failure(error: workflow.WorkflowError) -> HTTPException:
    return HTTPException(error.status_code, str(error))


@app.post("/api/workflows")
async def create_workflow(body: WorkflowRequest, user: User = Depends(credential_user)) -> dict:
    try:
        return await workflow.run(workflow.start(user, body.message), user)
    except workflow.WorkflowError as exc:
        raise workflow_failure(exc) from exc


@app.get("/api/workflows")
def list_workflows(user: User = Depends(credential_user), db: Session = Depends(session)) -> list[dict]:
    query = select(Workflow).order_by(Workflow.updated_at.desc())
    if user.role != "manager":
        query = query.where(Workflow.owner_id == user.id)
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
    return [{"sku": p.sku, "name": p.name, "inventory": p.inventory,
             "reorder_point": p.reorder_point} for p in db.scalars(select(Product).order_by(Product.id))]


@app.get("/api/dashboard")
async def dashboard(user: User = Depends(credential_user)) -> dict:
    token = issue_capability(user)
    from backend.mcp_client import call_tool
    kpi = await call_tool("production_kpi", token, {})
    issues = await call_tool("quality_issues", token, {})
    sales = await call_tool("sales_analysis", token, {})
    return {"kpi": kpi, "issues": issues, "sales": sales}


@app.post("/api/chat")
async def chat(body: ChatRequest, user: User = Depends(credential_user), db: Session = Depends(session)) -> dict:
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
