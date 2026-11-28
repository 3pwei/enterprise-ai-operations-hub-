# RAG and Knowledge Agent

The knowledge corpus is bundled with the API image. It contains synthetic purchasing, approval, inventory and quality policies, two restricted policies and one expired notice. The fixture policies illustrate document Q&A. They do not change the procurement console's executable rules or approve any workflow.

## Publish and reindex documents

Store a matched `<id>.json` and `<id>.md` under [documents](../backend/knowledge/documents). JSON records the stable document ID, title, integer version, owning department, allowed role, update timestamp with offset and optional expiry date. The expiry date is exclusive and interpreted in UTC. The Markdown starts with a `##` heading and a `關鍵詞：` line of pipe-delimited search phrases per section. Blank lines divide citable paragraphs. Authors should use specific phrases to limit off-topic matches.

API startup loads the bundled corpus. An operator can also publish reviewed files into an initialized database:

```bash
docker compose exec -T api python -m backend.knowledge.index
docker compose exec -T api python -m backend.knowledge.index --reindex
```

For a separate reviewed corpus, make the directory available to the API container and pass its path to the same module. Keep released Markdown sources under version control. A citation is identified by `document-id@version#section.paragraph`. The database serves the latest version per document ID. A newer version replaces metadata and chunks in one transaction. A replay is a no-op, a lower version cannot roll back the index, and edits to an existing version are rejected. `--reindex` rebuilds the current, unchanged source and stays safe to retry. Retire an existing policy by publishing a new version with an expiry date. Removing a file from the seed bundle alone leaves the indexed policy in place.

## Retrieval and answer construction

1. FastAPI authenticates the existing bearer identity or public visitor cookie. Policy intent from `/api/chat` and the explicit `/api/knowledge/query` both route to the Knowledge Agent. The public console uses the explicit endpoint while operational chat stays private.
2. The agent sends a signed, short-lived capability and a correlation ID to the read-only `knowledge_search` MCP tool. The server loads the active user and intersects role and department permissions with optional `department`, `document_id` and `version` filters. It excludes expired versions. If the question specifies a version such as `v2`, that version also restricts retrieval.
3. PostgreSQL materializes eligible rows before computing exact pgvector cosine distance. The score combines keyword matches (65%) and cosine similarity (35%). A section keyword is required for a passage to qualify as evidence. Embeddings are deterministic 384-dimensional hashes of English term/character features and Chinese characters and bigrams. This keeps the demo offline and reproducible. SQLite uses the same score with a local vector calculation. The small corpus uses exact scoring without an ANN index; broad paraphrase coverage is limited by the authored keyword gate and the offline embeddings.
4. The server emits up to four authorized source passages. Mock Mode quotes them directly. With an API key, the optional Agents SDK step may select or reorder their indices. It receives only the question and authorized passages. It has no tools, and only its validated indices reach the answer renderer. All displayed statements are excerpts with citations. The `inference` field is null because this release does not infer policies. With no evidence, the service returns an explicit refusal to answer.

## Authorization and audit

| Resolved identity | Departments | Roles on documents |
| --- | --- | --- |
| Developer analyst (seed user 1) | shared, operations, quality | all or analyst |
| Developer manager (seed user 2) | shared, procurement | all or manager |
| Active public simulation visitor | shared | all |

Public visitors can switch simulated roles within a workspace. Knowledge permissions remain limited to the shared, role-neutral corpus. The server derives permissions from the verified identity, never from the question, filters or model. The public API uses Mock Mode even if an API key is accidentally configured. An operator setting an API key in developer mode enables disclosure of authorized passages and the question to the configured model provider. SDK tracing is disabled for this step.

`audit_events` records the MCP tool call; `knowledge_lookups` records the same execution's correlation ID, actor, outcome, requested filters and authorized references. It omits raw questions, excerpts and credentials. Public lookup records are removed along with their expired workspace. The client sees the correlation ID, result count and strategy in the RAG / MCP trace.

## Reproduce the demo

1. In developer Compose, sign in as analyst. Ask `請購單需要填哪些欄位？` in **企業知識問答**. Expand **採購作業 SOP · v2 · §1.1** and **RAG / MCP 執行追蹤**.
2. Ask `供應商黑名單如何解除？` as analyst and then as the developer manager. The analyst gets no evidence. The developer manager gets the restricted procurement policy. Both public visitor roles get no evidence for the same question.
3. Ask `採購 SOP v1 詢價如何處理？` or `可以先買後報嗎？` to verify superseded or expired policy does not become current evidence.

Run the fixed HTTP cases against a running developer-mode Compose deployment with `OPENAI_API_KEY` empty:

```bash
set -a
. ./.env
set +a
python3 scripts/evaluate_knowledge.py
```

The 29 cases cover answer text and citation identity, department and version filters, expired and unknown queries, and prompt injection across the authorization boundary. The pytest suite additionally checks parsing, index replay and atomicity, MCP capability validation, the simulated public boundary and model input with a stub. A stub and Mock Mode do not validate live model behavior.
