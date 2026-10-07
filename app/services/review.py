"""User-scoped operations shared by conversational and HTTP boundaries."""
from sqlalchemy import select
import json
from sqlalchemy.orm import Session
from app.models import User, Transaction, ReviewState, SyncState


def ensure_user(db: Session, user_id: str):
    if not db.get(User, user_id):
        db.add(User(id=user_id))
        db.flush()


def list_unreviewed(db: Session, user_id: str, limit: int = 100, offset: int = 0):
    if not 1 <= limit <= 200 or offset < 0:
        raise ValueError('Use a limit between 1 and 200 and a nonnegative offset')
    rows = db.scalars(select(Transaction).where(
        Transaction.user_id == user_id,
        Transaction.review_state == ReviewState.UNREVIEWED,
    ).order_by(Transaction.txn_date.desc(), Transaction.id).offset(offset).limit(limit + 1)).all()
    return {'transactions': [serialize(row) for row in rows[:limit]],
            'next_offset': offset + limit if len(rows) > limit else None}


def serialize(row):
    currency = None
    try:
        metadata = json.loads(row.raw_json or '{}')
        if isinstance(metadata, dict) and metadata.get('source') == 'simplefin':
            currency = metadata.get('currency')
    except (ValueError, TypeError):
        pass
    return {'id': row.id, 'date': row.txn_date.isoformat(), 'amount': str(row.amount),
            'currency': currency,
            'merchant': row.merchant, 'description': row.description,
            'category': row.category, 'status': row.bank_status}


def review_transaction(db: Session, user_id: str, transaction_id: str, decision: ReviewState):
    row = db.get(Transaction, transaction_id)
    if row is None or row.user_id != user_id:
        raise ValueError('Transaction not found')
    if row.sync_state == SyncState.SYNCED:
        raise ValueError('Already-published expenses cannot be changed through review')
    if decision == ReviewState.SHARED and (row.bank_status != 'posted' or row.amount <= 0):
        raise ValueError('Only posted positive expenses can be marked shared')
    row.review_state = decision
    row.sync_state = SyncState.READY if decision == ReviewState.SHARED else SyncState.NOT_READY
    db.commit()
    return {'id': row.id, 'review_state': row.review_state.value, 'sync_state': row.sync_state.value,
            'published_to_splitwise': False}
