import asyncio
import json
from pathlib import Path

import httpx2 as httpx
import pytest
from openai import DefaultAsyncHttpxClient
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db import engine
from backend.models import User
from backend.orchestration import respond
from scripts import smoke_live_agent as evaluation


def request(**changes):
    return httpx.Request("POST", evaluation.ENDPOINT, json={
        "model": evaluation.MODEL, "service_tier": "default", "max_output_tokens": evaluation.OUTPUT_LIMIT, **changes,
    })


@pytest.mark.parametrize(("changes", "initial", "reason"), [
    ({"model": "different-model"}, {}, "unpriced_request"),
    ({"tools": [{"type": "web_search"}]}, {}, "unpriced_request"),
    ({}, {"pending": True}, "unknown_provider_usage"),
    ({}, {"calls": evaluation.CALL_LIMIT}, "call_limit"),
    ({}, {"input_tokens": evaluation.TOKEN_LIMIT}, "token_limit"),
    ({"service_tier": "priority"}, {}, "unpriced_request"),
])
def test_budget_refuses_requests_before_dispatch(changes, initial, reason):
    budget = evaluation.Budget(**initial)
    with pytest.raises(RuntimeError, match=reason):
        asyncio.run(budget.reserve(request(**changes)))
    assert budget.calls == initial.get("calls", 0)


def test_budget_enforces_cost_independent_of_token_limit(monkeypatch):
    monkeypatch.setattr(evaluation, "USD", evaluation.REQUEST_COST - 1)
    budget = evaluation.Budget()
    with pytest.raises(RuntimeError, match="budget_limit"):
        asyncio.run(budget.reserve(request()))
    assert budget.calls == 0


def test_budget_settles_usage_and_holds_reservation_for_unknown_usage():
    async def run():
        budget = evaluation.Budget()
        await budget.reserve(request())
        await budget.settle(httpx.Response(200, json={
            "usage": {"input_tokens": 123, "output_tokens": 5},
        }))
        assert budget.cost == 123 * evaluation.INPUT_RATE + 5 * evaluation.OUTPUT_RATE
        await budget.reserve(request())
        with pytest.raises(RuntimeError, match="unknown_provider_usage"):
            await budget.settle(httpx.Response(200, json={}))
        assert budget.pending
        assert budget.calls == 2

    asyncio.run(run())


@pytest.mark.parametrize(("failure", "code"), [
    (429, "provider_rate_limited"),
    ("timeout", "provider_timeout"),
    ("connection", "provider_connection_failed"),
])
def test_sdk_request_is_budgeted_and_provider_failure_is_sanitized(
    client, monkeypatch, failure, code,
):
    secret = "provider-secret-test-value"
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    monkeypatch.setenv("OPENAI_MODEL", evaluation.MODEL)
    settings.cache_clear()
    budget = evaluation.Budget()
    requests = []

    def transport(request):
        requests.append(json.loads(request.content))
        if failure == "timeout":
            raise httpx.ReadTimeout(secret, request=request)
        if failure == "connection":
            raise httpx.ConnectError(secret, request=request)
        return httpx.Response(failure, json={"error": {"message": secret}}, request=request)

    async def run():
        with Session(engine()) as db:
            actor = db.get(User, 1)
        async with DefaultAsyncHttpxClient(
            transport=httpx.MockTransport(transport),
            event_hooks={"request": [budget.reserve], "response": [budget.settle]},
        ) as provider:
            return await respond("查 P-300 庫存", actor, None, http_client=provider)

    result = asyncio.run(run())
    assert len(requests) == budget.calls == 1
    assert requests[0]["store"] is False
    assert result["execution"]["status"] == "failed"
    assert result["execution"]["error"] == code
    assert secret not in json.dumps(result)
    assert result["draft"] is None


def test_live_manifest_covers_required_cases_and_missing_key_exits_77(monkeypatch, capsys):
    cases = json.loads(Path(evaluation.__file__).with_name("live_agent_cases.json").read_text())
    assert len({case["id"] for case in cases}) == len(cases) == evaluation.CASE_LIMIT
    assert {case["group"] for case in cases} == {"normal", "ambiguous", "unauthorized", "abnormal"}
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["smoke_live_agent.py", "--confirm-live",
                                     "--confirm-standard-prices"])
    assert evaluation.main() == 77
    assert '"status": "not_verified"' in capsys.readouterr().out
