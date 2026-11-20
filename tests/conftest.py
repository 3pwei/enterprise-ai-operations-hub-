import pytest
from fastapi.testclient import TestClient

from backend.api import app
from backend.config import settings
from backend.db import engine


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'demo.db'}")
    monkeypatch.setenv("MCP_SIGNING_KEY", "testing-signing-key-at-least-32-characters")
    monkeypatch.setenv("DEMO_ANALYST_TOKEN", "example-analyst-token-at-least-24-characters")
    monkeypatch.setenv("DEMO_MANAGER_TOKEN", "example-manager-token-at-least-24-characters")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings.cache_clear()
    engine.cache_clear()
    yield
    engine().dispose()
    engine.cache_clear()
    settings.cache_clear()


@pytest.fixture
def client(configured):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def analyst():
    return {"Authorization": "Bearer example-analyst-token-at-least-24-characters"}


@pytest.fixture
def manager():
    return {"Authorization": "Bearer example-manager-token-at-least-24-characters"}
