# Project guidance

- Develop only against simulated enterprise records. Never imply a connection to actual ERP, SAP, or EIP.
- Keep SQL and numeric calculations in the backend; LLMs summarize only tool results.
- Add role checks to MCP tool implementations, not just to UI or agent prompts.
- Never hardcode API keys or demo credentials in the application bundle. Use `.env` locally.
- Add a meaningful automated test for each changed tool or API contract.
- Use a feature branch and pull request; do not force push or directly push the default branch.
