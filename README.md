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
1. `python -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt`
3. `cp .env.example .env`
4. `python scripts/init_db.py`
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
