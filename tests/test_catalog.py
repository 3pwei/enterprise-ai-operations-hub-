from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import Audit, PurchaseOrder


def draft(client, analyst, sku="P-300"):
    response = client.post("/api/workflows", headers=analyst,
                           json={"message": f"請評估採購 {sku}"})
    assert response.status_code == 200, response.text
    return response.json()


def test_live_product_data_invalidates_draft(client, analyst, manager):
    first = draft(client, analyst)
    assert first["quantity"] == 16 and first["rule_id"] == 1
    assert client.put("/api/products/P-300", headers=analyst,
                      json={"name": "Demo", "inventory": 10, "reorder_point": 20}).status_code == 403
    updated = client.put("/api/products/P-300", headers=manager,
                         json={"name": "Demo", "inventory": 10, "reorder_point": 20})
    assert updated.status_code == 200 and updated.json()["revision"] == 1
    changes = client.get("/api/catalog/changes", headers=manager).json()
    assert changes[0]["action"] == "product.update"
    assert changes[0]["before"]["inventory"] == 4
    assert changes[0]["after"]["inventory"] == 10
    assert client.get(f"/api/workflows/{first['id']}", headers=analyst).json()["stale"]
    assert client.post(f"/api/workflows/{first['id']}/submit", headers=manager).status_code == 409
    assert draft(client, analyst)["quantity"] == 10
    with Session(engine()) as db:
        assert db.scalar(select(func.count()).select_from(PurchaseOrder).where(
            PurchaseOrder.product_id == 3)) == 0


def test_order_inputs_and_new_product(client, analyst, manager):
    assert client.post("/api/products", headers=analyst,
                       json={"sku": "P-900", "name": "new", "inventory": 1,
                             "reorder_point": 10}).status_code == 403
    created = client.post("/api/products", headers=manager,
                          json={"sku": "P-900", "name": "new", "inventory": 1,
                                "reorder_point": 10})
    assert created.status_code == 201
    assert client.post("/api/products", headers=manager,
                       json={"sku": "P-900", "name": "new", "inventory": 1,
                             "reorder_point": 10}).status_code == 409
    assert client.post("/api/orders", headers=manager,
                       json={"sku": "P-900", "kind": "sale", "quantity": 3}).status_code == 201
    assert client.post("/api/orders", headers=manager,
                       json={"sku": "P-900", "kind": "inbound", "quantity": 2}).status_code == 201
    assert draft(client, analyst, "P-900")["quantity"] == 10
    assert client.post("/api/orders", headers=manager,
                       json={"sku": "P-900", "kind": "sale", "quantity": -1}).status_code == 422


def test_rule_preview_publish_and_versioned_confirmation(client, analyst, manager):
    old = draft(client, analyst)
    params = {"formula": "safety_stock", "safety_stock": 5}
    assert client.post("/api/rules/preview", headers=analyst,
                       json={**params, "sku": "P-300"}).status_code == 403
    preview = client.post("/api/rules/preview", headers=manager,
                          json={**params, "sku": "P-300"})
    assert preview.json()["quantity"] == 21
    assert client.post("/api/rules", headers=analyst,
                       json={**params, "expected_rule_id": 1}).status_code == 403
    published = client.post("/api/rules", headers=manager,
                            json={**params, "expected_rule_id": 1})
    assert published.status_code == 201 and published.json()["id"] == 2
    assert client.post("/api/rules", headers=manager,
                       json={**params, "expected_rule_id": 1}).status_code == 409
    assert client.get(f"/api/workflows/{old['id']}", headers=analyst).json()["stale"]
    assert client.post(f"/api/workflows/{old['id']}/submit", headers=manager).status_code == 409
    new = draft(client, analyst)
    assert new["quantity"] == 21 and new["rule_id"] == 2
    assert client.post(f"/api/workflows/{new['id']}/submit", headers=manager).status_code == 200
    assert client.post(f"/api/workflows/{new['id']}/submit", headers=manager).json()["purchase_id"] == \
           client.get(f"/api/workflows/{new['id']}", headers=analyst).json()["purchase_id"]
    with Session(engine()) as db:
        assert db.scalar(select(func.count()).select_from(Audit).where(
            Audit.tool == "catalog.rule.publish", Audit.outcome == "ok")) == 1
