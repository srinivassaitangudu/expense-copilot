"""Import normalized CSV rows without bank-provider credentials."""
import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Transaction

REQUIRED = {"transaction_id", "account_id", "date", "amount", "description"}


def parse_csv(content: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")), strict=True)
    try:
        headers = reader.fieldnames or []
        if not REQUIRED.issubset(headers) or len(headers) != len(set(headers)):
            raise ValueError("CSV needs unique columns: transaction_id, account_id, date, amount, description")
        rows = []
        seen = set()
        for line, row in enumerate(reader, 2):
            if len(rows) >= 5000:
                raise ValueError("CSV exceeds 5000 transactions")
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Row {line}: column count does not match header")
            row = {key: value.strip() for key, value in row.items()}
            if any(not row[key] for key in REQUIRED):
                raise ValueError(f"Row {line}: required value is empty")
            if any(len(row[key]) > 200 for key in ("transaction_id", "account_id")) or len(row["description"]) > 2000:
                raise ValueError(f"Row {line}: field is too long")
            try:
                amount = Decimal(row["amount"])
                if not amount.is_finite() or abs(amount) >= Decimal("10000000000") or amount != amount.quantize(Decimal("0.01")):
                    raise ValueError()
                txn_date = date.fromisoformat(row["date"])
            except (ValueError, InvalidOperation):
                raise ValueError(f"Row {line}: use an ISO date and a finite amount with at most two decimals") from None
            identity = (row["account_id"], row["transaction_id"])
            if identity in seen:
                raise ValueError(f"Row {line}: duplicate account/transaction ID")
            seen.add(identity)
            rows.append({**row, "amount": amount, "date": txn_date})
    except csv.Error:
        raise ValueError("Malformed CSV") from None
    if not rows:
        raise ValueError("CSV has no transactions")
    return rows


def import_csv(db: Session, user_id: str, content: str) -> dict:
    # Validate the entire file before writing anything. Stable IDs preserve distinct
    # same-day purchases while making repeated uploads safe.
    rows = parse_csv(content)
    created = skipped = 0
    for row in rows:
        # Retain the legacy column to avoid a schema migration in this first slice.
        # Length-prefixed account IDs make this namespace unambiguous.
        source_id = f"csv:{len(row['account_id'])}:{row['account_id']}:{row['transaction_id']}"
        existing = db.scalar(select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.teller_transaction_id == source_id,
        ))
        if existing:
            skipped += 1
            continue
        db.add(Transaction(
            user_id=user_id, teller_transaction_id=source_id,
            account_id=row["account_id"], txn_date=row["date"], amount=row["amount"],
            description=row["description"], bank_status="posted",
        ))
        created += 1
    db.commit()
    return {"created": created, "skipped": skipped}
