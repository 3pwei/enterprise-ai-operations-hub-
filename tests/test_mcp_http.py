"""Exercise actual network MCP sessions against three separate processes."""

import asyncio
import os
import socket
import subprocess
import sys
import time
from contextlib import ExitStack

import pytest
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db import engine
from backend.mcp_client import call_tool
from backend.models import User
from backend.security import issue_capability


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _stop(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


@pytest.fixture
def http_servers(client, monkeypatch):
    with ExitStack() as stack:
        for name in ("data", "erp", "eip"):
            port = _free_port()
            env = {**os.environ, "MCP_PORT": str(port), "MCP_HOST": "127.0.0.1",
                   "MCP_TRANSPORT": "streamable-http"}
            process = subprocess.Popen(
                [sys.executable, "-m", f"backend.mcp_servers.{name}"], env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            stack.callback(_stop, process)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise AssertionError(f"{name} MCP exited: {process.stderr.read().decode()}")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise AssertionError(f"{name} MCP did not start")
            monkeypatch.setenv(f"MCP_{name.upper()}_URL", f"http://127.0.0.1:{port}/mcp")
        settings.cache_clear()
        yield
        settings.cache_clear()


def test_separate_http_servers_all_tools_and_permissions(http_servers):
    with Session(engine()) as db:
        manager = issue_capability(db.get(User, 2))
        analyst = issue_capability(db.get(User, 1))

    tools = [
        ("production_kpi", {}, "data.batches"),
        ("quality_issues", {}, "data.quality_issues"),
        ("sales_analysis", {}, "data.sales_orders"),
        ("inventory", {"sku": "P-100"}, "erp.products"),
        ("order_status", {"order_id": 1}, "erp.sales_orders"),
        ("approval_rules", {}, "eip.policy"),
        ("approval_status", {"approval_id": 1}, "eip.approvals"),
    ]
    for name, params, source in tools:
        assert asyncio.run(call_tool(name, manager, params))["source"] == source
    with pytest.raises(ValueError, match="access denied"):
        asyncio.run(call_tool("approval_status", analyst, {"approval_id": 1}))
    with pytest.raises(ValueError, match="access denied"):
        asyncio.run(call_tool("inventory", "tampered", {"sku": "P-100"}))


def test_chat_routes_through_http_mcp(http_servers, client, analyst):
    response = client.post("/api/chat", headers=analyst, json={"message": "查詢 P-100 庫存"})
    assert response.status_code == 200
    assert response.json()["mode"] == "mock"
    assert response.json()["trace"][0]["source"] == "erp.products"
