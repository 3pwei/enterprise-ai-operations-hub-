# Phase 06B Live Agent verification

## Manual run

Install the developer dependencies with `pip install -e '.[dev]'`. Run the preflight from the repository root before confirming paid execution.

```bash
python scripts/smoke_live_agent.py
```

Check the current [OpenAI model pricing](https://developers.openai.com/api/docs/models/gpt-4o-mini). The evaluator is configured for standard GPT-4o mini text rates of US$0.15 per million input tokens, US$0.075 per million cached input tokens and US$0.60 per million output tokens. If current pricing or model availability is uncertain, leave the run at preflight. Supply `OPENAI_API_KEY` through your local secret manager or shell environment before running the evaluation.

```bash
python scripts/smoke_live_agent.py --confirm-live --confirm-standard-prices
```

The full run plans 20 cases. Use `--limit 1` for only the P-300 draft. Preflight estimates US$0.1428 for 20 cases assuming seven requests per case, 4,000 input tokens and 700 output tokens per request. Before each request the evaluator reserves up to US$0.01962 at the stated prices using the 128,000-token model context and 700-token output cap. The aggregate limits are US$1, 1,000,000 tokens and 140 model requests. Unused reservations are released after provider usage arrives. A failed or interrupted request with unknown usage keeps the reservation and ends the suite. Reported costs are calculated from provider usage and the listed rates. A provider invoice can include account-level adjustments.

The evaluator uses isolated synthetic SQLite records and the existing ERP, Data, EIP and Knowledge MCP tools. The procurement case requires an inventory read, a purchase SOP citation, an awaiting-confirmation P-300 draft for 16 units, and no increase in purchase orders, approvals or workflow submissions. Each case checks tool names and outcomes, plus seeded answer markers or citations where specified. The report omits raw user prompts, model answers, tool arguments and credentials. For ambiguity and refusal cases the score tests observable actions and state, with basic checks on the answer. It does not perform semantic grading of every response. Case success is the share of attempted cases passing all assertions. Tool accuracy is the share matching the expected tool/outcome rules. A truncated report has status `incomplete` and its rates describe only attempted cases.

The command exits 0 when every selected case passes, 1 for a failed or incomplete run, and 77 when credentials or confirmations are absent. Normal CI only runs offline tests. Provider calls have zero automatic retries, including rate limits and ambiguous transport failures. The existing procurement workflow retains its bounded ERP read retry and explicit manager confirmation.

## Verification record

| Check | Phase 06B result |
| --- | --- |
| Live LLM | **NOT VERIFIED**. No API key was present. Preflight exited 77. |
| Actual success rate, tool accuracy, latency and usage-based cost | Unavailable. Zero live cases and zero paid requests. |
| pytest, including MCP, RAG and Workflow regression | 108 passed locally. |
| Ruff and mypy | Passed locally. |
| Vite production build | Passed locally. |
| Playwright | Three UI tests and one workflow integration test passed locally. The integration run used FastAPI, real stdio MCP and SQLite. |
| PostgreSQL/pgvector and public Compose browser checks | Repository CI covers these environments. Docker was unavailable in the local workspace. |
