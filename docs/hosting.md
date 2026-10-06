# Render free + Supabase Postgres

Deployment preparation only. No Render/Supabase resources have been provisioned,
and neither a real client login nor a live bank connection has been verified.
Merge MCP PR #3 and ingestion PR #4 before enabling the blueprint. This PR can be
reviewed independently on main, but its deploy target requires both components.
Do not merge UI PR #2. There is no expense website, static hosting or cron service.

## Supabase database

1. Create/select a Supabase project. In Connect, copy the session-pooler connection
   details (port 5432). Session pooling supports IPv4 clients and is appropriate
   for a persistent SQLAlchemy backend. Do not use transaction pooling here.
2. Use `postgresql+psycopg` as the URL scheme; psycopg2 is not installed. URL-encode
   the password. Keep the entire URL private in Render's `DATABASE_URL` setting.
3. Download your project's CA certificate using Supabase's SSL guidance. Upload it
   as a Render secret file named `supabase-ca.crt`; reference
   `/etc/secrets/supabase-ca.crt`. Add `sslmode=verify-full` and `sslrootcert` to the
   connection URL as shown in `deploy/render.env.example`. Never commit credentials
   or certificate files. Verify the pooler hostname with the project certificate.
4. Startup creates existing tables plus additive bank sync state inside one
   transaction. It enables RLS and revokes `anon`/`authenticated` table access so
   financial tables are not exposed through Supabase's REST API. The backend's
   trusted DB owner bypasses RLS; every MCP operation separately enforces user
   identity. This is not a claim of complete multi-tenant database isolation.

Official connection guidance:
https://supabase.com/docs/guides/database/connecting-to-postgres

Free projects have service limits and can pause; check current quotas before
relying on continuous availability. Render cold starts and Supabase pauses are
separate conditions. SQLite files on Render would not persist; do not use them.

## OAuth without an expense UI

Use a hosted OAuth provider for login/consent. Auth0 is one setup option:

1. Create a tenant and a custom API with identifier exactly
   `https://YOUR_SERVICE.onrender.com/mcp`, signing algorithm RS256, and permissions
   `expenses:read` and `expenses:write`. Enable offline access for refresh tokens.
2. Create appropriate OAuth clients for ChatGPT and Claude Code. Register exact
   callback URLs supplied by those clients. Use authorization-code + PKCE; use
   refresh-token rotation if supported. Keep confidential client secrets only in
   the client's private OAuth setup. The MCP resource server needs no client secret.
3. Enable the issuer's compatible MCP client-registration flow, or configure
   pre-registered client credentials where the client supports them. Claude Code
   documents preconfigured OAuth credentials; ChatGPT account/workspace controls
   can differ. Do not assume arbitrary dynamic registration is enabled by default.
4. Configure Auth0's resource-parameter compatibility when available, or set this
   API as the tenant default audience in a tenant dedicated to Expense Copilot.
   MCP clients commonly send `resource`; Auth0 deployments expecting `audience`
   can otherwise mint userinfo/opaque tokens. This server intentionally rejects
   such tokens. Confirm the token audience matches the MCP URL, rather than
   weakening audience validation.
5. Create your permitted personal login account. Copy its subject ID into the JSON
   `OAUTH_ALLOWED_SUBJECTS` list. Set issuer/JWKS URLs exactly, including trailing
   issuer slash. Configure consent to grant both expense scopes. Subjects, issuer
   and URLs are configuration, not bank credentials; access tokens stay private.

Official references:
https://auth0.com/docs/secure/tokens/access-tokens/get-access-tokens
https://support.auth0.com/center/s/article/mcp-audience-error-with-auth0
https://developers.openai.com/plugins/build/auth
https://code.claude.com/docs/en/mcp

No custom authorization UI is added. Supabase is used for Postgres here, not as an
already-configured OAuth issuer. Using Supabase OAuth instead would require its
own login/consent and token-audience configuration.

## Render

After code review/merge and explicit deployment authorization:

1. Connect the existing GitHub repository and create the Blueprint service.
2. Keep the free web-service plan. No background worker, scheduler, static site or
   Render database is needed. Automatic deployment is off; deploy manually after
   the required PRs are merged and settings are complete.
3. Set the private values described above, using `deploy/render.env.example` as a
   placeholder reference. Render generates an encryption secret; preserve it.
4. Upload the DB CA secret file. Build checks that the MCP and ingestion modules
   exist; startup validates Postgres/TLS, encryption and OAuth configuration, creates
   tables atomically, and serves only `app.mcp_http:create_app`.
5. `/healthz` reports process health only. It does not prove the database, OAuth
   issuer or bank connection is ready. Access logging is off to avoid financial or
   credential-bearing request data in logs. Database errors are sanitized.

A free service sleeps after 15 minutes; allow for its wake-up time and retry client
connection/discovery when needed. MCP HTTP is stateless; checkpoint and review
state live in Supabase, not memory. No keep-alive pings or scheduled sync.
https://render.com/docs/free

## Actual client verification

- `/healthz` succeeds; `/mcp` without authorization returns 401 and a protected-resource
  metadata challenge. `/api/transactions/unreviewed` and `/` must not expose data/UI.
- Add the HTTPS `/mcp` endpoint to ChatGPT's supported custom-app workflow with OAuth.
  In Claude Code: `claude mcp add --transport http expense-copilot YOUR_MCP_URL`, then
  complete sign-in from `/mcp`. Confirm discovery lists review tools and sync.
- Ask the client to call `get_status`, import synthetic example CSV text, list rows,
  save a personal decision, and reimport. Confirm no duplicate and saved state.
- Repeat after a service restart/cold start. Test denied access with an unpermitted
  account. Do not disable audience/scopes/subject checks to make setup succeed.
- For bank setup, run `python -m scripts.connect_simplefin --user-id YOUR_DB_USER_ID`
  from a private trusted environment with the same Supabase URL and encryption key.
  Render free has no shell; this setup does not require a laptop to stay online.
  If this cloud environment is used, configure its outbound destinations and secrets
  through the environment workflow first. Enter the one-time token via hidden prompt.
- Only then ask for `sync_transactions`. Listing existing rows never fetches banks.
  No tool publishes to Splitwise. Live financial data needs explicit user setup.

Do not call the project connected end to end in ChatGPT/Claude until these account
and deployed-endpoint steps succeed. Automated SDK protocol tests are a separate,
already-repeatable layer of verification.
