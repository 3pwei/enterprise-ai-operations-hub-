# API and MCP contracts

API accepts JSON and returns JSON. `/health` is public and verifies DB access. `/api/me`, `/api/products`, `/api/dashboard`, and `/api/chat` require `Authorization: Bearer <DEMO_ANALYST_TOKEN|DEMO_MANAGER_TOKEN>`. Unauthorized requests return 401. FastAPI publishes the full OpenAPI schema at `/openapi.json` and an interactive reference at `/docs`.

| Endpoint | Inputs | Output |
| --- | --- | --- |
| `GET /api/me` | bearer credential | `{id, name, role}` |
| `GET /api/products` | bearer credential | `[{sku, name, inventory, reorder_point}]` |
| `GET /api/dashboard` | bearer credential | `{kpi, issues, sales}`, each `{source, data}` |
| `POST /api/chat` | `{message}` (2–1000 chars), bearer credential | `{mode: "mock"|"llm", answer, trace: [{tool, input, source, output}]}` |
| `POST /api/workflows` | `{message}` (6–1000 chars with one SKU and procurement intent) | Persisted draft or `no_gap`/`failed` workflow |
| `GET /api/workflows`, `GET /api/workflows/{id}` | bearer credential | Own workflow(s); manager may read all; includes events and draft |
| `POST /api/workflows/{id}/retry` | bearer credential | Re-run failed or stale running task (60-second lease) |
| `POST /api/workflows/{id}/cancel` | bearer credential | Cancel running, failed, or awaiting confirmation |
| `POST /api/workflows/{id}/submit` | manager credential, no body | Atomically create a pending purchase and EIP approval after human confirmation; repeat returns the same IDs |
| `GET /api/workflows/{id}/approval` | manager credential | EIP MCP approval status; no approval mutation |

MCP calls require a signed capability issued by the API. It expires after 120 seconds; callers cannot self-select a user or role. Each tool returns `{source, data}`. Bad signatures, unauthorized roles, invalid inputs and unknown tool names fail closed; recorded audit outcomes are `ok`, `denied`, or `error`.

| Server | Tool | Input | Source and computation |
| --- | --- | --- | --- |
| Data | `production_kpi` | capability | `data.batches`: produced, passed, yield_pct = passed / produced × 100 |
| Data | `quality_issues` | capability | `data.quality_issues`: list of issue IDs, batches, severity, descriptions, status |
| Data | `sales_analysis` | capability | `data.sales_orders`: count, sum(quantity), sum(quantity × unit_price), TWD |
| ERP | `inventory` | capability, `sku` (letters/digits/hyphen, max 40) | `erp.products`: quantity, reorder point, below-threshold flag |
| ERP | `order_status` | capability, positive `order_id` | `erp.sales_orders`: order ID, quantity, status |
| ERP | `open_orders` | capability, validated SKU | `erp.sales_orders+erp.purchase_orders`: open sales demand and pending/approved purchase supply |
| EIP | `approval_rules` | capability | `eip.policy`: demo rule and version |
| EIP | `approval_status` | manager capability, positive `approval_id` | `eip.approvals`: approval ID, purchase ID, status |

The MCP client uses official Python SDK stdio transport, so servers are not publicly exposed. The MCP `call_tool` response is decoded by the API. No generic SQL query tool or mutating MCP method is registered. Purchase submission is a separate, explicitly confirmed and role-checked API action. Individual tools are also independently testable by running the corresponding Python module as a stdio MCP server.

## Knowledge Q&A

`POST /api/knowledge/query` accepts a required `message` and an optional `filters` object with `department`, `document_id`, and `version`. It uses the same developer bearer authentication or public session cookie as the console. It returns `status` (`answered` or `no_evidence`), `mode`, exact quoted `answer`, `citations` (document ID, title, version, department, updated timestamp, section, paragraph, excerpt), `inference` (null), and a correlated `trace`. The trace contains the execution strategy, match count, and request ID. The response is marked `Cache-Control: no-store`. Requests for unauthorized, expired, or superseded sources yield the same no-evidence response as an unknown question.

Internal MCP tool `knowledge_search(capability, question, request_id)` accepts the same typed question object and a UUID. The tool verifies the capability and loads the authorized department scope from server-side configuration. Caller filters only narrow that scope. See [RAG design](rag.md).
