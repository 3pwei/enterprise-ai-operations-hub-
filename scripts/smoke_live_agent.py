"""Opt-in OpenAI API smoke test with fresh synthetic records and no submission."""
import json
import os
import sys
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from backend.api import app
from backend.config import settings
from backend.db import engine

MESSAGE = "查詢 P-300 庫存，參考採購 SOP，評估是否需要採購，並建立待確認的採購草稿。"


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        print(json.dumps({"status": "not_verified", "reason": "OPENAI_API_KEY is absent"}))
        return 77
    with TemporaryDirectory(prefix="hub-live-agent-") as directory:
        analyst_token = token_urlsafe(32)
        os.environ.update(
            DATABASE_URL=f"sqlite:///{Path(directory) / 'smoke.db'}",
            MCP_SIGNING_KEY=token_urlsafe(40),
            DEMO_ANALYST_TOKEN=analyst_token,
            DEMO_MANAGER_TOKEN=token_urlsafe(32),
            PUBLIC_DEMO_MODE="false",
        )
        settings.cache_clear()
        engine.cache_clear()
        headers = {"Authorization": f"Bearer {analyst_token}"}
        try:
            with TestClient(app) as client:
                response = client.post("/api/chat", headers=headers,
                                       json={"message": MESSAGE, "draft_sku": "P-300"})
                response.raise_for_status()
                result = response.json()
                execution = result["execution"]
                draft = result["draft"] or {}
                reads = {step["tool"] for step in execution["trace"] if step["outcome"] == "ok"}
                flows = client.get("/api/workflows", headers=headers).json()
                passed = (
                    execution["status"] == "completed"
                    and {"inventory", "knowledge_search"} <= reads
                    and any(row["document_id"] == "purchase-sop" for row in result["citations"])
                    and draft.get("status") == "awaiting_confirmation"
                    and draft.get("quantity") == 16
                    and len(flows) == 1
                    and flows[0]["purchase_id"] is None
                )
                print(json.dumps({"status": "passed" if passed else "failed", "model": settings().openai_model,
                                  "execution": execution, "draft_status": draft.get("status"),
                                  "draft_quantity": draft.get("quantity")}, ensure_ascii=False))
                return 0 if passed else 1
        finally:
            engine().dispose()


if __name__ == "__main__":
    sys.exit(main())
