"""Manually evaluate the existing Operations Agent against the OpenAI Responses API."""
import argparse
import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from secrets import token_urlsafe
from statistics import median, quantiles
from tempfile import TemporaryDirectory
from time import monotonic

import httpx2 as httpx
from openai import DefaultAsyncHttpxClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db import engine
from backend.models import Approval, PurchaseOrder, User, Workflow, WorkflowSubmission
from backend.orchestration import MAX_TURNS, respond
from backend.seed import initialize

MODEL = "gpt-4o-mini"
# Integer nanodollars per token, standard uncached input and output.
INPUT_RATE, CACHED_RATE, OUTPUT_RATE = 150, 75, 600
INPUT_LIMIT, OUTPUT_LIMIT = 128_000, 700
REQUEST_TOKENS = INPUT_LIMIT + OUTPUT_LIMIT
REQUEST_COST = INPUT_LIMIT * INPUT_RATE + OUTPUT_LIMIT * OUTPUT_RATE
USD = 1_000_000_000
TOKEN_LIMIT = 1_000_000
CASE_LIMIT = 20
CALL_LIMIT = CASE_LIMIT * MAX_TURNS
ENDPOINT = "https://api.openai.com/v1/responses"


@dataclass
class Budget:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    pending: bool = False
    stopped: str | None = None

    @property
    def cost(self) -> int:
        return ((self.input_tokens - self.cached_tokens) * INPUT_RATE
                + self.cached_tokens * CACHED_RATE + self.output_tokens * OUTPUT_RATE)

    async def reserve(self, request: httpx.Request) -> None:
        payload = json.loads(request.content)
        if (request.method != "POST" or str(request.url) != ENDPOINT
                or payload.get("model") != MODEL or payload.get("stream")
                or payload.get("previous_response_id") or payload.get("conversation")
                or payload.get("service_tier") != "default"
                or any(tool.get("type") != "function" for tool in payload.get("tools", []))
                or not 0 < payload.get("max_output_tokens", 0) <= OUTPUT_LIMIT):
            self.stopped = "unpriced_request"
        elif self.pending:
            self.stopped = "unknown_provider_usage"
        elif self.calls >= CALL_LIMIT:
            self.stopped = "call_limit"
        elif self.input_tokens + self.output_tokens + REQUEST_TOKENS > TOKEN_LIMIT:
            self.stopped = "token_limit"
        elif self.cost + REQUEST_COST > USD:
            self.stopped = "budget_limit"
        if self.stopped:
            raise RuntimeError(self.stopped)
        self.calls += 1
        self.pending = True

    async def settle(self, response: httpx.Response) -> None:
        if not response.is_success:
            self.stopped = f"provider_http_{response.status_code}"
            return
        await response.aread()
        data = response.json()
        usage = data.get("usage") or {}
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        cached_tokens = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
        if (data.get("service_tier") not in (None, "default") or type(cached_tokens) is not int
                or type(input_tokens) is not int or type(output_tokens) is not int
                or not 0 < input_tokens <= INPUT_LIMIT or not 0 <= output_tokens <= OUTPUT_LIMIT
                or not 0 <= cached_tokens <= input_tokens):
            self.stopped = "unknown_provider_usage"
            raise RuntimeError(self.stopped)
        self.cached_tokens += cached_tokens
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.pending = False


def database_state() -> tuple[int, int, int, int]:
    with Session(engine()) as db:
        return (
            db.scalar(select(func.count()).select_from(PurchaseOrder)) or 0,
            db.scalar(select(func.count()).select_from(Approval)) or 0,
            db.scalar(select(func.count()).select_from(Workflow)) or 0,
            db.scalar(select(func.count()).select_from(WorkflowSubmission)) or 0,
        )


def score(case: dict, result: dict, before: tuple[int, ...], after: tuple[int, ...],
          secrets: tuple[str, ...]) -> dict:
    execution = result["execution"]
    draft = result.get("draft")
    trace = execution["trace"]
    expected = case["tools"]
    allowed = {**expected, **case.get("optional_tools", {})}
    outcomes = {(step["tool"], step["outcome"]) for step in trace}
    accepted = set(allowed.items())
    if case.get("draft_sku"):
        accepted.add(("prepare_purchase_draft", "queued"))
    tool_correct = set(expected.items()) <= outcomes <= accepted
    citations = {row["document_id"] for row in result["citations"]}
    citation_correct = (not case.get("citation") or case["citation"] in citations)
    citation_correct &= not case.get("no_citations") or not citations
    draft_expected = bool(case.get("draft_sku"))
    workflow_correct = (
        before[:2] == after[:2] and before[3] == after[3]
        and after[2] - before[2] == int(draft_expected)
        and (draft is None if not draft_expected else
             bool(draft and draft.get("sku") == case["draft_sku"]
                  and draft.get("status") == "awaiting_confirmation" and draft.get("quantity") == 16))
    )
    safe = all(secret not in json.dumps(result, ensure_ascii=False) for secret in secrets)
    answer = re.sub(r"(?<=\d),(?=\d)", "", result["answer"]).casefold()
    answer_correct = bool(answer.strip()) and all(
        re.search(r"(?<!\w)" + re.escape(marker.casefold()) + r"(?!\w)", answer)
        if not marker.isdecimal() else re.search(r"(?<!\d)" + marker + r"(?!\d)", answer)
        for marker in case.get("answer_contains", [])
    )
    run_correct = execution["status"] == "completed" or (
        execution["status"] == "partial" and ("order_status", "invalid_arguments") in outcomes
    )
    return {"id": case["id"], "group": case["group"],
            "passed": all((tool_correct, citation_correct, workflow_correct,
                           safe, answer_correct, run_correct)),
            "tool_outcomes": sorted(outcomes),
            "tool_correct": tool_correct, "citation_correct": citation_correct,
            "workflow_correct": workflow_correct, "secret_check": safe,
            "answer_check": answer_correct, "execution_status": execution["status"],
            "error": execution["error"], "elapsed_ms": execution["elapsed_ms"]}


async def evaluate(cases: list[dict], key: str) -> tuple[dict, int]:
    budget = Budget()
    rows = []
    started = monotonic()
    with TemporaryDirectory(prefix="hub-live-agent-") as directory:
        signing_key = token_urlsafe(40)
        os.environ.update(DATABASE_URL=f"sqlite:///{Path(directory) / 'smoke.db'}",
                          MCP_SIGNING_KEY=signing_key, PUBLIC_DEMO_MODE="false",
                          OPENAI_MODEL=MODEL, DEMO_ANALYST_TOKEN="", DEMO_MANAGER_TOKEN="")
        settings.cache_clear()
        engine.cache_clear()
        try:
            initialize()
            for case in cases:
                with Session(engine()) as db:
                    actor = db.get(User, 2 if case.get("manager") else 1)
                    assert actor is not None
                before = database_state()
                previous = (budget.input_tokens, budget.output_tokens, budget.cost, budget.calls)
                case_started = monotonic()
                try:
                    async with DefaultAsyncHttpxClient(
                        event_hooks={"request": [budget.reserve], "response": [budget.settle]},
                    ) as http_client:
                        result = await respond(case["prompt"], actor, case.get("draft_sku"),
                                               http_client=http_client)
                    row = score(case, result, before, database_state(), (key, signing_key))
                except Exception:  # noqa: BLE001 - preserve observed usage without raw diagnostics
                    budget.stopped = budget.stopped or "evaluation_error"
                    row = {"id": case["id"], "group": case["group"], "passed": False,
                           "tool_correct": False, "error": "evaluation_error",
                           "elapsed_ms": int((monotonic() - case_started) * 1000)}
                row.update(input_tokens=budget.input_tokens - previous[0],
                           output_tokens=budget.output_tokens - previous[1],
                           observed_cost_usd=(budget.cost - previous[2]) / USD,
                           provider_calls=budget.calls - previous[3])
                rows.append(row)
                if not row["provider_calls"] and not budget.stopped:
                    budget.stopped = "no_provider_request"
                if budget.stopped or budget.pending:
                    break
        finally:
            engine().dispose()
    latencies = [row["elapsed_ms"] for row in rows]
    complete = len(rows) == len(cases) and not budget.stopped and not budget.pending
    passed = complete and all(row["passed"] for row in rows)
    report = {
        "status": "passed" if passed else "failed" if complete else
                  "incomplete" if budget.calls else "not_verified",
        "model": MODEL, "planned": len(cases), "evaluated": len(rows), "cases": rows,
        "success_rate": sum(row["passed"] for row in rows) / len(rows),
        "tool_accuracy": sum(row["tool_correct"] for row in rows) / len(rows),
        "input_tokens": budget.input_tokens, "output_tokens": budget.output_tokens,
        "cached_input_tokens": budget.cached_tokens,
        "provider_calls": budget.calls, "observed_cost_usd": budget.cost / USD,
        "reserved_cost_upper_usd": (budget.cost + REQUEST_COST * budget.pending) / USD,
        "latency_p50_ms": median(latencies),
        "latency_p95_ms": quantiles(latencies, n=20, method="inclusive")[-1]
                          if len(latencies) > 1 else latencies[0],
        "wall_ms": int((monotonic() - started) * 1000),
        "stop_reason": budget.stopped or ("unknown_provider_usage" if budget.pending else None),
    }
    return report, 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--confirm-standard-prices", action="store_true",
                        help="Confirm current OpenAI standard input/cached/output prices are $0.15/$0.075/$0.60 per 1M tokens.")
    parser.add_argument("--limit", type=int, choices=range(1, CASE_LIMIT + 1), default=CASE_LIMIT)
    args = parser.parse_args()
    key = os.getenv("OPENAI_API_KEY", "").strip()
    cases = json.loads(Path(__file__).with_name("live_agent_cases.json").read_text())[:args.limit]
    print(json.dumps({
        "status": "preflight", "model": MODEL, "cases": len(cases),
        "estimated_cost_usd": len(cases) * MAX_TURNS * (4_000 * INPUT_RATE + 700 * OUTPUT_RATE) / USD,
        "next_request_upper_usd": REQUEST_COST / USD, "budget_usd": 1,
        "token_limit": TOKEN_LIMIT, "call_limit": CALL_LIMIT,
    }), flush=True)
    if not key or not args.confirm_live or not args.confirm_standard_prices:
        print(json.dumps({"status": "not_verified", "reason": "API key absent" if not key
                          else "Manual execution and current pricing must both be confirmed"}))
        return 77
    # Keep provider bodies, prompts and credentials out of opt-in reports and SDK logs.
    logging.disable(logging.CRITICAL)
    try:
        report, status = asyncio.run(evaluate(cases, key))
    except Exception:  # noqa: BLE001 - provider diagnostics may include request data
        print(json.dumps({"status": "incomplete", "reason": "evaluation_error"}))
        return 1
    print(json.dumps(report, ensure_ascii=False))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
