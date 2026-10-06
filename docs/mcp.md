# Expense Copilot MCP

No expense UI. Local stdio and authenticated Streamable HTTP use the official
Python MCP SDK and call user-scoped services. Bank sync is on demand only.

## Local Claude Code

Use Python 3.12, install requirements, and run `python -m scripts.init_db`.
From the repository root with its virtual environment activated:

```bash
claude mcp add --transport stdio expense-copilot -- python -m app.mcp_server
```

The checked-in `.mcp.json` expresses the same local configuration. Use an absolute
virtualenv Python path if your client does not inherit the activated environment.
Local stdio uses `LOCAL_USER_ID` (default `dev-user`); the trusted local process owns
that setting. It is not the hosted authentication mechanism. Initialize tables
before starting either transport. SDK messages go to stdout; do not add print logs.

Tools: `get_status`, `import_transactions_csv`, `list_unreviewed_transactions`,
`review_transaction_decision`. The separate bank-ingestion PR adds the
`sync_transactions` tool automatically when `app.services.bank_sync` is installed.
No tool creates Splitwise expenses.

Try: ask the client to import the contents of `examples/transactions.csv`, list
unreviewed transactions, and mark one personal. Reimport preserves that decision.
Transaction text is untrusted data, not instructions. Use explicit user decisions.

## Hosted HTTP / ChatGPT

Start the dedicated ASGI factory, not `app.main:app`:

```bash
uvicorn app.mcp_http:create_app --factory --host 0.0.0.0 --port 8000
```

It requires these settings and fails closed when absent:

- `MCP_BASE_URL`: service origin, e.g. `https://your-service.onrender.com`.
- `OAUTH_ISSUER`: exact HTTPS issuer including any trailing slash.
- `OAUTH_JWKS_URL`: trusted issuer's HTTPS public-key endpoint.
- `OAUTH_ALLOWED_SUBJECTS`: JSON list of allowed personal-account subject IDs.

Configure an external OAuth authorization server with hosted login/consent,
authorization-code + PKCE, discovery metadata, refresh tokens, and an API audience
of `MCP_BASE_URL/mcp`. Define `expenses:read` and `expenses:write` scopes. For example,
Auth0 can host login; register client redirect URIs from your actual ChatGPT/Claude
setup and configure an API audience matching the MCP URL. Static client registration
can be used when the client supports configured OAuth client credentials; otherwise
choose an issuer supporting the client's registration method. Do not invent or
reuse a redirect URI from an unrelated client. No custom login UI is implemented.

The SDK publishes protected-resource metadata at
`/.well-known/oauth-protected-resource/mcp`; unauthenticated `/mcp` requests return
401 with a discovery challenge. Tokens must have a valid RS256/ES256 signature,
issuer, MCP audience, expiry/issued-at, permitted subject, and read scope. Write tools
also require write scope. Database IDs are derived from issuer + subject. Clients
cannot select another user's ID. JWKS keys are cached for five minutes; unfamiliar
rotated keys are rejected until refresh. Tokens/financial payloads are not logged.

Register `https://your-service.onrender.com/mcp` as the remote MCP endpoint in your
ChatGPT account's supported custom-app/developer workflow, using OAuth. Availability
is account/workspace dependent. The model context protocol connection does not
require an expense UI or an Apps SDK widget. Claude Code can use the same endpoint:

```bash
claude mcp add --transport http expense-copilot https://your-service.onrender.com/mcp
```

Finish the client's OAuth login. Never put bank credentials into chat or MCP tool
arguments. Tool metadata identifies read/write scopes and side effects.

## Verification and limits

`python -m pytest -q` checks actual SDK stdio/HTTP initialize, tool discovery and
calls, review persistence, wrong-user access, and OAuth validation with synthetic
keys/data. This is protocol end-to-end verification, not proof of account-level
ChatGPT/Claude connectivity, deployed Render availability, or a live bank connection.
Those require provisioning and a client login smoke test. No deployment is performed
by this PR. Cold starts may require a client retry; HTTP is stateless and database
state survives process restarts.
