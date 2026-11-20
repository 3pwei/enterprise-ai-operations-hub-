from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import Audit


def test_health_seed_and_access(client, analyst):
    assert client.get("/health").json() == {"status": "ok", "database": "ok", "mode": "mock"}
    assert client.get("/api/products").status_code == 401
    assert client.get("/api/products", headers={"Authorization": "Bearer wrong"}).status_code == 401
    result = client.get("/api/products", headers=analyst)
    assert result.status_code == 200
    assert [p["sku"] for p in result.json()] == ["P-100", "P-200"]


def test_dashboard_and_chat_use_real_mcp(client, analyst, manager):
    dashboard = client.get("/api/dashboard", headers=analyst)
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["kpi"]["data"]["yield_pct"] == 96.67
    assert dashboard.json()["sales"]["data"]["revenue"] == 4500
    chat = client.post("/api/chat", headers=analyst, json={"message": "查詢 P-100 庫存和品質異常"})
    assert chat.status_code == 200, chat.text
    assert chat.json()["mode"] == "mock"
    assert {t["tool"] for t in chat.json()["trace"]} == {"inventory", "quality_issues"}
    denied = client.post("/api/chat", headers=analyst, json={"message": "簽核 1"})
    assert denied.status_code == 403
    allowed = client.post("/api/chat", headers=manager, json={"message": "簽核 1"})
    assert allowed.status_code == 200
    assert allowed.json()["trace"][0]["output"]["status"] == "pending"
    with Session(engine()) as db:
        assert db.scalar(select(func.count()).select_from(Audit)) >= 7
        assert db.scalar(select(func.count()).select_from(Audit).where(Audit.outcome == "denied")) >= 1


def test_invalid_chat_and_unknown_intent(client, analyst):
    assert client.post("/api/chat", headers=analyst, json={"message": "x"}).status_code == 422
    answer = client.post("/api/chat", headers=analyst, json={"message": "你好呀"}).json()
    assert answer["trace"] == []
    assert answer["mode"] == "mock"
