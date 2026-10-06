import secrets
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User, Transaction, ReviewState, SyncState

router=APIRouter()

# v0.1 development identity. Replace with OAuth/OIDC before public multi-user release.
DEV_USER="dev-user"

def ensure_dev_user(db: Session):
    u=db.get(User, DEV_USER)
    if not u:
        u=User(id=DEV_USER); db.add(u); db.commit()
    return u

@router.get("/transactions/unreviewed")
def unreviewed(db: Session=Depends(get_db)):
    ensure_dev_user(db)
    rows=db.scalars(select(Transaction).where(
        Transaction.user_id==DEV_USER,
        Transaction.review_state==ReviewState.UNREVIEWED
    ).order_by(Transaction.txn_date.desc())).all()
    return [{"id":x.id,"date":x.txn_date,"amount":str(x.amount),"merchant":x.merchant,
             "description":x.description,"category":x.category,"status":x.bank_status} for x in rows]

class Review(BaseModel):
    decision: ReviewState

@router.post("/transactions/{transaction_id}/review")
def review(transaction_id: str, body: Review, db: Session=Depends(get_db)):
    ensure_dev_user(db)
    txn=db.get(Transaction,transaction_id)
    if not txn or txn.user_id!=DEV_USER: raise HTTPException(404)
    txn.review_state=body.decision
    txn.sync_state=SyncState.READY if body.decision==ReviewState.SHARED else SyncState.NOT_READY
    db.commit()
    return {"id":txn.id,"review_state":txn.review_state,"sync_state":txn.sync_state}

@router.get("/setup")
def setup_state(db: Session=Depends(get_db)):
    ensure_dev_user(db)
    return {"user_id":DEV_USER,"teller_connected":False,"splitwise_connected":False,
            "next":"Wire provider credentials; UI scaffold is available at /."}
