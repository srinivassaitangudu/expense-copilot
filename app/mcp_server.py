"""
MCP boundary for v0.1.

Keep chat clients thin: tools should call application services, not Teller/Splitwise
directly. This file intentionally stays transport-agnostic until the hosted MCP auth
choice is finalized.
"""
TOOLS = {
    "list_unreviewed_expenses": "Return transactions awaiting a user decision.",
    "review_expense": "Mark a transaction shared, personal, or ignored.",
    "sync_bank_transactions": "Fetch/reconcile recent Teller transactions.",
    "push_verified_expenses": "Create Splitwise expenses for verified shared items."
}
