# API and MCP contracts

API accepts JSON and returns JSON. `/health` is public and verifies DB access. `/api/me`, `/api/products`, `/api/dashboard`, and `/api/chat` require `Authorization: Bearer <DEMO_ANALYST_TOKEN|DEMO_MANAGER_TOKEN>`. Unauthorized requests return 401. FastAPI publishes the full OpenAPI schema at `/openapi.json` and an interactive reference at `/docs`.

| Endpoint | Inputs | Output |
| --- | --- | --- |
| `GET /api/me` | bearer credential | `{id, name, role}` |
| `GET /api/products` | bearer credential | `[{sku, name, inventory, reorder_point}]` |
| `GET /api/dashboard` | bearer credential | `{kpi, issues, sales}`, each `{source, data}` |
| `POST /api/chat` | `{message}` (2–1000 chars), bearer credential | `{mode: "mock"|"llm", answer, trace: [{tool, input, source, output}]}` |

MCP calls require a signed capability issued by the API. It expires after 120 seconds; callers cannot self-select a user or role. Each tool returns `{source, data}`. Bad signatures, unauthorized roles, invalid inputs and unknown tool names fail closed; recorded audit outcomes are `ok`, `denied`, or `error`.

| Server | Tool | Input | Source and computation |
| --- | --- | --- | --- |
| Data | `production_kpi` | capability | `data.batches`: produced, passed, yield_pct = passed / produced × 100 |
| Data | `quality_issues` | capability | `data.quality_issues`: list of issue IDs, batches, severity, descriptions, status |
| Data | `sales_analysis` | capability | `data.sales_orders`: count, sum(quantity), sum(quantity × unit_price), TWD |
| ERP | `inventory` | capability, `sku` (letters/digits/hyphen, max 40) | `erp.products`: quantity, reorder point, below-threshold flag |
| ERP | `order_status` | capability, positive `order_id` | `erp.sales_orders`: order ID, quantity, status |
| EIP | `approval_rules` | capability | `eip.policy`: demo rule and version |
| EIP | `approval_status` | manager capability, positive `approval_id` | `eip.approvals`: approval ID, purchase ID, status |

The MCP client uses official Python SDK stdio transport, so servers are not publicly exposed. The MCP `call_tool` response is decoded by the API. No generic SQL query tool or mutating MCP method is registered. Individual tools are also independently testable by running the corresponding Python module as a stdio MCP server.
