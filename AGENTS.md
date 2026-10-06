# Expense Copilot

Use feature branches and PRs targeting main. Do not merge without user authorization.
Install dependencies with `python -m pip install -r requirements.txt`.
Run `python -m pytest -q` from the repository root.

Development endpoints use a shared identity and must not be exposed publicly.
Use synthetic data in tests; do not require bank or Splitwise credentials.
Do not commit .env files, certificates, keys, tokens, real financial exports,
local databases, or secrets in logs. Keep .env.example placeholder-only.

Teller access is unavailable for the current development path. Continue with
normalized CSV imports and keep provider-specific ingestion separate from review.
Do not claim MCP or Splitwise writes work until they are implemented and tested.
