# Phase 04 procurement workflow

This demo uses simulated ERP, EIP and manufacturing data. The Phase 04 route is deterministic and works without an API key. The existing chat may use the Agents SDK with an API key, but it cannot submit or approve purchases.

## Workflow and handoff

1. Router validates one SKU such as `P-300` and an explicit procurement intent; it persists a `running` task before calling MCP.
2. Data Agent calls ERP MCP `inventory` and `open_orders`. Each call uses the current user's signed, short-lived capability. The ERP tool validates the SKU and records an audit event. The workflow stores the returned sources, data and agent handoff as durable events.
3. Procurement Agent computes `max(0, reorder_point + open_sales - inventory - inbound_purchases)`. Only open sales orders count as demand. Submitted pending and approved purchase orders count as incoming supply; drafts and rejected orders do not. The result is a draft awaiting confirmation, or `no_gap`.
4. A manager explicitly confirms the draft in Workflow Console. The server checks the role again, rechecks current ERP quantities and atomically inserts one pending purchase, one pending EIP approval, an idempotency mapping keyed by workflow ID, and audit/history records. A duplicate confirmation returns the original identifiers. This **submits a request**, never approves it.
5. The manager can call EIP MCP `approval_status` to read the pending approval state. A new event records the lookup. No approval mutation exists.

| From | Event | To |
| --- | --- | --- |
| created | validated route | `running` |
| `running` | MCP data and positive gap | `awaiting_confirmation` |
| `running` | MCP data and zero gap | `no_gap` |
| `running` | lookup or processing error | `failed` |
| `failed` or stale `running` | explicit retry | `running` |
| `running`, `failed`, `awaiting_confirmation` | explicit cancel | `cancelled` |
| `awaiting_confirmation` | manager confirmation + current quantity recheck | `submitted` |

`submitted`, `cancelled`, and `no_gap` cannot be retried or submitted again (repeating an already submitted confirmation returns the same IDs). If a process is interrupted while running, a retry is possible after 60 seconds. Read calls have a 12-second timeout and one bounded retry. Failed requests keep their history and a generic error without exposing transport details. State and event tables survive API restarts when the DB volume is retained. Cancellation during MCP work wins: the runner checks the stored status before saving a draft. A stale draft is rejected if quantities changed; create a new task to recalculate.

The demo uses bearer tokens and role records, not SSO. The manager-only submit and EIP checks happen server-side; hiding controls in the UI is for clarity. SQLAlchemy `create_all` adds new workflow tables for an earlier demo DB; this is a demo upgrade path, not a migration framework. No real SAP/EIP integration, production auth, or live LLM workflow evaluation has been performed.

## Reproduce

After `docker compose up -d --build --wait`, sign in with the analyst token, create `請評估採購 P-300`, inspect the 16-unit draft and its Data Agent and Procurement Agent events. Confirming with the analyst token returns HTTP 403. Sign in with the manager token, refresh and explicitly submit; the request becomes `submitted` with a purchase and approval ID. Check EIP status: `pending`. Repeat the submit request: the same IDs return. Try `請評估採購 P-100`: the existing pending purchase covers the 25-unit stock/reorder/sales deficit, so the task becomes `no_gap`. Cancel an unsubmitted draft, or retry a failed lookup in the console.

Backend tests use actual local MCP subprocesses with SQLite; UI Playwright tests use stateful mocked API responses. CI Compose smoke checks the real API/MCP flow against PostgreSQL.
