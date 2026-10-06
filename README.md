# Expense Copilot

A personal, chat-first shared-expense assistant:

**Transaction source → Postgres → MCP review in ChatGPT/Claude Code → future Splitwise publishing.**

The database owns workflow state. No expense UI is required. Teller signup is
unavailable for the current path. Normalized CSV and synthetic data are usable now;
live-bank access is a separate integration, not a prerequisite for MCP review.

## Development

Use Python 3.12 from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m scripts.init_db
python -m app.mcp_server
```

The last command starts local stdio MCP, not a browser app. See [MCP setup](docs/mcp.md)
for Claude Code configuration, authenticated remote HTTP, and verification details.
Use `examples/transactions.csv` as synthetic tool input. The normalized format is
`transaction_id,account_id,date,amount,description`, with YYYY-MM-DD dates and at
most two decimal places. Positive amounts are expenses; negative amounts are refunds.
CSV assumes posted transactions in a single, unspecified currency. Stable source IDs
are required. Repeat IDs skip changed values and preserve decisions. Limits:
5,000 rows and 1,000,000 characters. Sequential development imports only.

The private development REST API (`app.main:app`) remains for compatibility. It
uses `dev-user` and must never be the public hosted entrypoint. The MCP HTTP factory
is `app.mcp_http:create_app`; it exposes no development REST endpoints or UI.
Do not use the old Render blueprint until the hosting configuration PR is merged.

## Current scope

- Official MCP SDK: stdio and authenticated, stateless Streamable HTTP.
- CSV import, paginated outstanding review, and explicit decisions.
- OAuth issuer/JWKS verification, scope enforcement, and personal-subject allowlist.
- Per-user database access; local stdio has an operator-selected development identity.
- Shared decisions never publish automatically. Only posted positive expenses can
  be marked shared; already-published rows cannot be changed through review.
- On-demand bank sync is added by the separate bank-ingestion PR. No scheduled sync.
- Splitwise authorization, split allocation, and idempotent publishing remain future work.

Run `python -m pytest -q`. GitHub Actions runs synthetic tests without credentials.
OAuth authentication is implemented as a resource server; a hosted issuer and real
client login must be configured and verified before claiming ChatGPT connectivity.

## Workflow and data

Use separate feature branches and PRs targeting `main`. Do not merge or deploy
without authorization. Use synthetic data until hosted access is configured.
Never commit `.env`, certificates, private keys, provider tokens, credential-bearing
URLs, databases, or real financial exports. Keep placeholders in `.env.example`.
Render free hosting and Supabase Postgres are the intended deployment; cloud coding
alone neither provisions nor hosts them. Review current Splitwise API terms before
any commercial use; this project is personal and is not production-ready multi-user SaaS.
