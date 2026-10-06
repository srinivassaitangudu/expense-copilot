# Expense Copilot v0.1

A chat-first shared-expense assistant.

## Mental model
Teller -> Expense Copilot (FastAPI + Postgres) -> review in MCP client -> Splitwise.

The database owns workflow state. Splitwise is an output, not the database.

## v0.1 scope
- Multi-user-shaped schema (user_id is present everywhere that matters)
- Teller client + idempotent transaction upsert
- 10-day reconciliation window for pending->posted changes
- Review states: unreviewed/shared/personal/ignored
- Splitwise client abstraction
- onboarding page scaffold
- MCP tool contract scaffold
- Render blueprint
- local SQLite for development; hosted Postgres for deployment

## Run locally
1. Use Python 3.12: `python -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt`
3. `cp .env.example .env`
4. `python -m scripts.init_db`
5. `uvicorn app.main:app --reload`
6. Open `http://localhost:8000`

## Before real bank data
Teller development/production requires mTLS. Never commit Teller certificates, private
keys, access tokens, Splitwise tokens, or `.env`. The current code defaults to Teller
sandbox and a dev identity.

## Next build slice
1. Complete Teller Connect callback and encrypted token persistence.
2. Add Splitwise OAuth authorize/callback flow.
3. Add real auth (OIDC) so MCP calls map to a user.
4. Implement `push_verified_expenses` with an idempotency ledger.
5. Expose Streamable HTTP MCP endpoint.
6. Add webhook-driven Teller sync.

## Important product constraint
Splitwise's self-serve API is documented for hobbyist/personal integrations and is not
intended for fee-based commercial services. If this becomes a commercial product,
revisit licensing before launch.

## Develop without Teller

Teller signup is not required for this development path. Start with normalized CSV
imports, then review transactions through the existing API. The current endpoints
use a shared development identity: do not expose this app publicly or import real
financial data until authentication and per-user authorization are implemented.

1. Install requirements and run `python -m scripts.init_db` from the repository root.
2. Start `uvicorn app.main:app --reload`.
3. Open `/docs`, choose `POST /api/transactions/import/csv`, and submit a JSON object
   with a `csv` string containing the contents of `examples/transactions.csv`.
4. Use `GET /api/transactions/unreviewed` and the review endpoint to classify rows.

Required CSV columns: `transaction_id,account_id,date,amount,description`.
Dates use YYYY-MM-DD. Amounts are signed decimals with at most two decimal places;
use positive amounts for expenses and negative amounts for refunds. Import only
posted transactions in one currency (currency-aware splitting is not implemented).
Bank exports must be normalized to this format before import. Use stable source
transaction IDs, not row numbers that change across exports. Distinct purchases
need distinct IDs even when date, amount, and description match.

Imports accept up to 5,000 rows and a 1,000,000-character CSV string. Invalid files
are rejected before transaction insertion. Repeated account/transaction IDs within
a file are rejected. Previously imported IDs are skipped, preserving review state;
changed values for an existing ID are also skipped, not reconciled. Imports are
intended to run sequentially in this development version.

CSV IDs use a separate namespace in the legacy `teller_transaction_id` column, so
this slice requires no database migration and does not change Teller sync behavior.
The CSV route does not require Teller credentials or call any bank API. Splitwise
writes and an actual MCP transport remain future work.

## Branch and cloud workflow

Use feature branches and pull requests targeting `main`. Run `python -m pytest`
before opening a PR. GitHub Actions runs the same tests without provider secrets.
For Codex Cloud, select this repository, install `requirements.txt`, and use
`python -m pytest` as the verification command. A cloud environment must be created
and published in Codex separately; committing these files does not activate one.

Never commit `.env` files, private keys, certificates, provider tokens, database
credentials, or real transaction exports. `.env.example` must contain placeholders
only. Keep development imports and local databases outside version control.
