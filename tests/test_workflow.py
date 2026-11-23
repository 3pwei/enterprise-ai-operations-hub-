from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import Approval, Audit, PurchaseOrder, Workflow


def create(client, headers, sku="P-300"):
    return client.post("/api/workflows", headers=headers, json={"message": f"請評估採購 {sku}"})


def test_mcp_handoff_confirmation_and_eip(client, analyst, manager):
    draft = create(client, analyst)
    assert draft.status_code == 200, draft.text
    data = draft.json()
    assert data["status"] == "awaiting_confirmation"
    assert data["quantity"] == 16
    assert data["purchase_id"] is None
    assert [event["agent"] for event in data["events"]] == [
        "router", "data_agent", "data_agent", "router", "procurement_agent", "procurement_agent"]
    assert {e["step"] for e in data["events"]} >= {"inventory", "open_orders", "draft"}
    task_id = data["id"]
    assert len(client.get("/api/workflows", headers=analyst).json()) == 1
    assert len(client.get("/api/workflows", headers=manager).json()) == 1
    denied = client.post(f"/api/workflows/{task_id}/submit", headers=analyst)
    assert denied.status_code == 403
    assert client.get(f"/api/workflows/{task_id}/approval", headers=analyst).status_code == 403
    with Session(engine()) as db:
        assert db.scalar(select(func.count()).select_from(PurchaseOrder)) == 2
        assert db.scalar(select(func.count()).select_from(Audit).where(
            Audit.tool == "workflow.submit", Audit.outcome == "denied")) == 1
    submitted = client.post(f"/api/workflows/{task_id}/submit", headers=manager)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"
    assert submitted.json()["purchase_id"] is not None
    again = client.post(f"/api/workflows/{task_id}/submit", headers=manager)
    assert again.json()["purchase_id"] == submitted.json()["purchase_id"]
    assert client.post(f"/api/workflows/{task_id}/cancel", headers=manager).status_code == 409
    approval = client.get(f"/api/workflows/{task_id}/approval", headers=manager)
    assert approval.status_code == 200, approval.text
    assert approval.json()["source"] == "eip.approvals"
    assert approval.json()["data"]["status"] == "pending"
    with Session(engine()) as db:
        assert db.scalar(select(func.count()).select_from(PurchaseOrder)) == 3
        assert db.scalar(select(func.count()).select_from(Approval)) == 2
        assert db.scalar(select(func.count()).select_from(Audit).where(
            Audit.tool == "workflow.submit", Audit.outcome == "ok")) == 1


def test_no_gap_and_validation(client, analyst, manager):
    # Existing pending PO covers the reorder point and open sales: no duplicate request.
    result = create(client, analyst, "P-100")
    assert result.status_code == 200, result.text
    assert result.json()["quantity"] == 0
    assert result.json()["status"] == "no_gap"
    assert client.post(f"/api/workflows/{result.json()['id']}/submit", headers=manager).status_code == 409
    for message in ["查詢 P-300 庫存", "請採購 P-300 和 P-100"]:
        assert client.post("/api/workflows", headers=analyst,
                           json={"message": message}).status_code == 422
    assert create(client, analyst, "P-9999").json()["status"] == "failed"
    assert client.post("/api/workflows", headers=analyst,
                       json={"message": "請採購 P-300", "role": "manager"}).status_code == 422
    assert client.get("/api/workflows").status_code == 401


def test_stale_drafts_and_owner_isolation(client, analyst, manager):
    first = create(client, analyst).json()
    second = create(client, manager).json()
    assert client.get(f"/api/workflows/{second['id']}", headers=analyst).status_code == 404
    assert [flow["id"] for flow in client.get("/api/workflows", headers=analyst).json()] == [first["id"]]
    assert client.post(f"/api/workflows/{first['id']}/submit", headers=manager).status_code == 200
    assert client.post(f"/api/workflows/{second['id']}/submit", headers=manager).status_code == 409
    with Session(engine()) as db:
        assert db.scalar(select(func.count()).select_from(PurchaseOrder)) == 3


def test_failure_resume_cancel_and_stale_run(client, analyst, manager, monkeypatch):
    from backend import workflow
    actual = workflow.call_tool

    async def unavailable(*args, **kwargs):
        raise TimeoutError("secret transport error")

    monkeypatch.setattr(workflow, "call_tool", unavailable)
    failed = create(client, analyst).json()
    assert failed["status"] == "failed"
    assert "secret" not in str(failed)
    monkeypatch.setattr(workflow, "call_tool", actual)
    restarted = client.post(f"/api/workflows/{failed['id']}/retry", headers=analyst)
    assert restarted.status_code == 200, restarted.text
    assert restarted.json()["status"] == "awaiting_confirmation"
    assert client.post(f"/api/workflows/{failed['id']}/retry", headers=analyst).status_code == 409
    assert client.post(f"/api/workflows/{failed['id']}/cancel", headers=analyst).json()["status"] == "cancelled"
    assert client.post(f"/api/workflows/{failed['id']}/submit", headers=manager).status_code == 409
    with Session(engine()) as db:
        stale_id = "00000000-0000-0000-0000-000000000001"
        row = Workflow(id=stale_id, owner_id=1,
                       sku="P-300", request="請採購 P-300", status="running",
                       updated_at=datetime.now(UTC) - timedelta(minutes=2))
        db.add(row)
        db.commit()
    stale = client.post(f"/api/workflows/{stale_id}/retry", headers=analyst)
    assert stale.status_code == 200, stale.text
    assert stale.json()["status"] == "awaiting_confirmation"
    with Session(engine()) as db:
        db.get(Workflow, stale_id).updated_at = datetime.now(UTC)
        db.get(Workflow, stale_id).status = "running"
        db.commit()
    assert client.post(f"/api/workflows/{stale_id}/retry", headers=analyst).status_code == 409
