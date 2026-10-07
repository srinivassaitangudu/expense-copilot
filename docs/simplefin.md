# On-demand SimpleFIN ingestion

This is an independently reviewable backend service, not a provider commitment.
The MCP PR registers `sync_transactions` when this module is installed. Neither
PR requires the other to run its own tests. No scheduler or review UI is added.

SimpleFIN Bridge uses MX for institution connections, according to its privacy
policy: https://beta-bridge.simplefin.org/info/privacy . Direct MX integration is
not inherently more accurate; bank coverage, refresh reliability, access terms
and pricing still decide suitability. SimpleFIN offers a personal-use API for
$1.50/month or $15/year plus tax: https://beta-bridge.simplefin.org/ . Check your
US bank/card coverage: https://beta-bridge.simplefin.org/search-institutions .
No actual signup or bank connection has been verified for this user.

## Private setup

Initialize tables with `python -m scripts.init_db`. This adds `bank_sync_states`
without changing existing tables. Use a strong random `ENCRYPTION_KEY` of at least
32 characters in your private environment. Existing encrypted connections depend
on that key; do not rotate it without re-encrypting or reconnecting them.

Use your authenticated MCP `get_status` database user ID (or `dev-user` for local
stdio) with the same database and encryption configuration:

```bash
python -m scripts.connect_simplefin --user-id YOUR_DATABASE_USER_ID
```

It prompts privately for a one-time setup token generated in SimpleFIN's portal,
claims it once, and stores the encrypted access URL. Never paste setup tokens,
access URLs, or bank credentials into chat, tool arguments, source files, or logs.
A claim followed by a DB failure needs a new setup token. Only official Bridge
HTTPS hosts are accepted; redirects and arbitrary user-provided URLs are rejected.
The command can reconnect the primary connection for a user.

## Sync semantics

- Only an explicit call fetches data. Listing saved rows does not contact a bank.
- Initial fetch: up to 90 days. Later fetches overlap five days from the successful
  checkpoint. Long absences catch up in 90-day windows; `catchup_remaining` tells
  the client another later request is needed. Provider history may be shorter.
- One provider attempt per hour per user, including failed attempts. An atomic DB
  lease prevents overlapping fetches across processes; cached calls report their
  next allowed time. This stays within the documented 24-request expectation,
  but other applications sharing the same token can consume its quota too.
- Checkpoint and transaction writes commit together only after a complete fetch.
  Provider errors or malformed data fail closed without advancing the checkpoint.
- Pending rows are excluded. Expense outflows are negated into our positive-expense
  convention; refunds/income remain negative. Account currency is retained in
  normalized metadata, never guessed. No currency conversion or splitting occurs.
- Stable provider/connection/account/transaction IDs prevent duplicates. Unchanged rows retain
  review decisions. Description-only corrections preserve decisions. Amount/date/
  currency corrections return unpublished rows to unreviewed. Published rows are
  left untouched and counted as conflicts; no Splitwise update is attempted.
- Changed pending-to-posted IDs are not reconciled by guesswork. Pending rows never
  enter this workflow, but provider ID churn can still require manual reconciliation.
- Credentials and full provider responses are never included in tool results.

SimpleFIN is daily-update-oriented. On-demand fetching does not force fresh bank
aggregation. Limits/history: https://beta-bridge.simplefin.org/info/developers .

Tests use mock HTTP and synthetic transactions. Live signup, bank coverage,
Supabase/Postgres execution and cloud hosting remain separate verification steps.
