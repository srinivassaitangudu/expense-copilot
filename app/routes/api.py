from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
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
    from app.services.review import review_transaction
    try:
        return review_transaction(db, DEV_USER, transaction_id, body.decision)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(404 if str(exc) == 'Transaction not found' else 422, detail=str(exc)) from exc

@router.get("/setup")
def setup_state(db: Session=Depends(get_db)):
    ensure_dev_user(db)
    return {"user_id":DEV_USER,"teller_connected":False,"splitwise_connected":False,
            "next":"Import a normalized CSV at /api/transactions/import/csv; bank credentials are optional."}


class CSVImport(BaseModel):
    csv: str = Field(min_length=1, max_length=1_000_000)


@router.post("/transactions/import/csv")
def import_transactions(body: CSVImport, db: Session = Depends(get_db)):
    from app.services.imports import import_csv
    ensure_dev_user(db)
    try:
        return import_csv(db, DEV_USER, body.csv)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, detail=str(exc)) from exc
