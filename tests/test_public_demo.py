from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api import app
from backend.config import settings
from backend.db import engine
from backend.models import DemoWorkspace, PurchaseOrder


def make_client():
    return TestClient(app, base_url="https://demo.example.test")


def test_independent_visitors_and_role_simulation(configured, monkeypatch):
    monkeypatch.setenv("PUBLIC_DEMO_MODE", "true")
    settings.cache_clear()
    with make_client() as first, make_client() as second:
        assert first.post("/api/demo/session").status_code == 200
        assert second.post("/api/demo/session").status_code == 200
        assert first.get("/api/products").json()[1]["inventory"] == 4
        assert second.get("/api/products").json()[1]["inventory"] == 4
        assert first.put("/api/products/P-300", json={"name": "test", "inventory": 10,
            "reorder_point": 20}).status_code == 403
        assert first.post("/api/demo/role", json={"role": "manager"}).status_code == 200
        assert first.put("/api/products/P-300", json={"name": "test", "inventory": 10,
            "reorder_point": 20}).status_code == 200
        assert first.get("/api/products").json()[1]["inventory"] == 10
        assert second.get("/api/products").json()[1]["inventory"] == 4
        assert first.get("/api/catalog/changes").json()[0]["target"] == "P-300"
        assert second.get("/api/catalog/changes").json() == []
        first_rule = first.get("/api/rules").json()["active"]["id"]
        assert first.post("/api/rules", json={"formula": "safety_stock", "safety_stock": 5,
                                            "expected_rule_id": first_rule}).status_code == 201
        assert second.get("/api/rules").json()["active"]["formula"] == "standard"
        assert first.post("/api/workflows", json={"message": "請評估採購 P-300"}).json()["quantity"] == 15
        assert second.get("/api/workflows").json() == []
        assert first.get("/api/dashboard").status_code == 403
        assert first.post("/api/chat", json={"message": "簽核 1"}).status_code == 403
        assert first.get("/api/products", headers={"Authorization": "Bearer example-manager-token-at-least-24-characters"}).status_code == 200
        with make_client() as anonymous:
            assert anonymous.get("/api/products", headers={"Authorization": "Bearer example-manager-token-at-least-24-characters"}).status_code == 401


def test_cross_session_submission_and_approval_are_blocked(configured, monkeypatch):
    monkeypatch.setenv("PUBLIC_DEMO_MODE", "true")
    settings.cache_clear()
    with make_client() as first, make_client() as second:
        first.post("/api/demo/session")
        second.post("/api/demo/session")
        flow = first.post("/api/workflows", json={"message": "請評估採購 P-300"}).json()
        assert flow["quantity"] == 16
        assert first.post(f"/api/workflows/{flow['id']}/submit").status_code == 403
        second.post("/api/demo/role", json={"role": "manager"})
        assert second.get(f"/api/workflows/{flow['id']}").status_code == 404
        assert second.post(f"/api/workflows/{flow['id']}/submit").status_code == 404
        first.post("/api/demo/role", json={"role": "manager"})
        submitted = first.post(f"/api/workflows/{flow['id']}/submit")
        assert submitted.status_code == 200, submitted.text
        assert first.get(f"/api/workflows/{flow['id']}/approval").json()["data"]["status"] == "pending"
        assert second.get(f"/api/workflows/{flow['id']}/approval").status_code == 404
        with Session(engine()) as db:
            assert db.scalar(select(func.count()).select_from(PurchaseOrder)) == 5


def test_expired_workspace_removed_on_new_session(configured, monkeypatch):
    monkeypatch.setenv("PUBLIC_DEMO_MODE", "true")
    settings.cache_clear()
    with make_client() as visitor:
        visitor.post("/api/demo/session")
        with Session(engine()) as db:
            old = db.scalar(select(DemoWorkspace))
            old.created_at = datetime.now(UTC) - timedelta(days=2)
            db.commit()
        assert visitor.post("/api/demo/session").status_code == 200
        with Session(engine()) as db:
            assert db.scalar(select(func.count()).select_from(DemoWorkspace)) == 1
