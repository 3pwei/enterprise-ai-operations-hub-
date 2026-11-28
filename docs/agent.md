# Phase 06 Operations Agent

## Run the procurement demo

1. Start the developer setup with `OPENAI_API_KEY` and optionally `OPENAI_MODEL`. Use the developer analyst token. The API sends the prompt and authorized synthetic MCP facts to the configured OpenAI model.
2. In 營運助理, choose **填入 P-300 採購範例**, select **允許建立此 SKU 的採購草稿**, and send. The model selects the ERP inventory and Knowledge SOP tools over separate turns. The API renders the returned SOP references and the workflow-calculated result.
3. With seed data, the existing ERP workflow gets 4 in stock, a reorder point of 20, and zero open sales and inbound purchases. The rule yields 16 and leaves the draft in `awaiting_confirmation`. Expand **Agent 執行追蹤** for tool selections, sources, outcomes, match counts, durations, and token totals.
4. Sign in as manager and open Workflow Console. Confirm the draft manually and query its EIP status. Backend confirmation rechecks authorization, current inputs, and the active rule. EIP records a pending simulation request.
5. To run offline, clear `OPENAI_API_KEY` and restart. Use **企業知識問答** and **採購 Workflow Console** for the equivalent deterministic demonstration. The public demo uses these same deterministic flows.

## Execution and authority

- Authenticated developer `POST /api/chat` routes to the single SDK agent when the key is configured. Data, ERP, EIP and Knowledge tools use the existing stdio MCP transport, server permissions and 120-second signed capability. Explicit `/api/knowledge/query` retains the independent knowledge agent.
- Granting a draft requires `draft_sku` matching the sole SKU named in the user's message. The agent gets a draft-request tool only for such an authorized run. The server checks the actor role, a successful inventory lookup for that SKU, and an authorized citation from the current purchase SOP. The tool queues at most one draft per run. The workflow starts only after the model loop completes and the server revalidates the actor. Existing workflow creation, arithmetic, revisions and submission remain authoritative. The model never supplies quantities, order IDs for writes, SQL or a submission instruction.
- The orchestration budget is seven model turns, eight tool calls, 700 output tokens per model response, six seconds per MCP call, 15 seconds per API request, and 35 seconds for the model loop. Orchestration calls are single-attempt. Provider timeouts, rate limits and connection failures have distinct sanitized error codes. Invalid tool arguments are rejected before the MCP call. The existing workflow retains its own bounded ERP retry policy.
- The agent treats retrieved passages as data. Prompt injection can still degrade generated wording or tool selection. The allowlist, per-tool validation, server-side RBAC and draft gate enforce action bounds independently of wording. The UI presents the server-generated draft status, quantity and citations separately.
- `GET /api/agent/executions/{id}` returns the saved run summary to the run owner, including sanitized failure codes. The database stores no user prompt, answer, raw tool arguments, raw MCP outputs, credentials or private reasoning in the execution record. SDK trace export and provider response storage are disabled for this route. An interrupted process can leave a run marked `running`. Token totals can be unavailable when the provider returns no usage.

## Reproduce the checks

- Run `pytest -q tests/test_orchestration.py`. The 30 fixed prompts in `tests/fixtures/agent_cases.json` exercise scripted SDK tool calls and role-dependent tool exposure. Separate integration cases invoke actual MCP subprocesses and the purchase Workflow. The fixed suite measures orchestration wiring against scripted choices.
- See [Phase 06B Live Agent verification](live-agent-verification.md) for the manual 20-case suite, cost preflight and current verification results.

## Phase 06 baseline verification report

Local run on 2026-11-28 with Python 3.12, OpenAI Agents SDK 0.26.0 and system-compatible Chromium.

| Check | Result |
| --- | --- |
| Full pytest suite, including RAG, MCP, Workflow and public demo regression | 95 passed in 50.36 seconds |
| Fixed Agent Evaluation | 30 scripted cases passed within the full suite |
| Orchestration integration | Actual MCP subprocesses returned the seeded 16-unit gap and current SOP. Analyst submission was denied, and manager confirmation created a pending EIP record. |
| Ruff, mypy, and Git whitespace check | Passed |
| Vite root and `/operations/` builds | Both passed |
| Playwright UI tests | 3 passed using stubbed API responses |
| Playwright workflow integration | 1 passed against local FastAPI, MCP and SQLite |
| Developer and public Docker Compose | Docker is unavailable locally. The repository CI runs these checks with PostgreSQL and pgvector. |
| OpenAI API | Unverified. The independent smoke command returned `not_verified` and exit 77 because `OPENAI_API_KEY` is absent. |
