import json
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.clients.teller import TellerClient
from app.models import Transaction

async def sync_teller(db: Session, user_id: str, access_token: str, lookback_days: int=10):
    client=TellerClient(access_token)
    accounts=await client.accounts()
    start=(date.today()-timedelta(days=lookback_days)).isoformat()
    seen=0
    for account in accounts:
        rows=await client.transactions(account["id"], start_date=start)
        for x in rows:
            txn=db.scalar(select(Transaction).where(
                Transaction.user_id==user_id,
                Transaction.teller_transaction_id==x["id"]))
            details=x.get("details") or {}
            counterparty=details.get("counterparty") or {}
            if txn is None:
                txn=Transaction(user_id=user_id,teller_transaction_id=x["id"],account_id=x["account_id"],
                    amount=Decimal(x["amount"]),txn_date=date.fromisoformat(x["date"]),
                    description=x["description"])
                db.add(txn)
            txn.amount=Decimal(x["amount"]); txn.txn_date=date.fromisoformat(x["date"])
            txn.description=x["description"]; txn.bank_status=x["status"]
            txn.category=details.get("category"); txn.merchant=counterparty.get("name")
            txn.raw_json=json.dumps(x)
            seen += 1
    db.commit()
    return {"accounts":len(accounts),"transactions_seen":seen}
