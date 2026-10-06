"""On-demand sync with persistent checkpoints and a cross-process database lease."""
import json
import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from app.bank_models import BankSyncState
from app.clients.simplefin import SimpleFINClient, ProviderError
from app.models import Connection, Transaction, ReviewState, SyncState
from app.security import decrypt
from app.config import settings


def require_encryption():
    if len(settings.encryption_key) < 32 or settings.encryption_key == 'dev-only-change-me':
        raise ValueError('Configure a strong ENCRYPTION_KEY before connecting a provider')


def utc_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def sync_simplefin(db, user_id: str, *, client=None, now=None):
    require_encryption()
    now = now or utc_naive()
    connection = db.scalar(select(Connection).where(Connection.user_id == user_id,
        Connection.provider == 'simplefin', Connection.external_id == 'primary'))
    if connection is None:
        raise ValueError('SimpleFIN is not connected for this user; use the private setup command')
    # Creation races are contained in a savepoint; claims use one atomic UPDATE.
    key = {'user_id': user_id, 'provider': 'simplefin'}
    if db.get(BankSyncState, (user_id, 'simplefin')) is None:
        try:
            with db.begin_nested():
                db.add(BankSyncState(**key))
                db.flush()
        except IntegrityError:
            pass
    state = db.get(BankSyncState, (user_id, 'simplefin'))
    previous = state.successful_through
    lease_until = now + timedelta(minutes=2)
    acquired = db.execute(update(BankSyncState).where(
        BankSyncState.user_id == user_id, BankSyncState.provider == 'simplefin',
        (BankSyncState.lease_until.is_(None) | (BankSyncState.lease_until <= now)),
        (BankSyncState.last_attempt.is_(None) | (BankSyncState.last_attempt <= now - timedelta(hours=1))),
    ).values(last_attempt=now, lease_until=lease_until)).rowcount
    # Persist rate budget before the request, including failed attempts.
    db.commit()
    if not acquired:
        db.expire_all()
        state = db.get(BankSyncState, (user_id, 'simplefin'))
        return {'status': 'cached', 'created': 0, 'updated': 0,
                'successful_through': state.successful_through.isoformat() if state.successful_through else None,
                'next_sync_at': (state.last_attempt + timedelta(hours=1)).isoformat() if state.last_attempt else None,
                'bank_refresh_forced': False}
    try:
        try:
            access_url = decrypt(connection.secret_ciphertext)
            provider = client or SimpleFINClient(access_url)
        except Exception:
            raise ValueError('Cannot read SimpleFIN credentials; check the encryption key or reconnect') from None
        start = previous - timedelta(days=5) if previous else now - timedelta(days=90)
        end = min(now, start + timedelta(days=90))
        async with asyncio.timeout(45):
            normalized = await provider.transactions(start.replace(tzinfo=timezone.utc), end.replace(tzinfo=timezone.utc))
        db.expire_all()
        state = db.scalar(select(BankSyncState).where(BankSyncState.user_id == user_id,
            BankSyncState.provider == 'simplefin').with_for_update())
        if state.lease_until != lease_until:
            raise ValueError('Sync lease expired; retry later')
        created = updated = unchanged = conflicts = 0
        for source in normalized:
            identity = f'simplefin:{len(source.account_id)}:{source.account_id}:{source.source_id}'
            row = db.scalar(select(Transaction).where(Transaction.user_id == user_id,
                                                     Transaction.teller_transaction_id == identity))
            raw = json.dumps({'source': 'simplefin', 'currency': source.currency})
            if row is None:
                row = Transaction(user_id=user_id, teller_transaction_id=identity, account_id=source.account_id,
                                  amount=source.amount, txn_date=source.posted_at.date(), description=source.description,
                                  bank_status='posted', raw_json=raw)
                db.add(row)
                created += 1
            elif (row.amount, row.txn_date, row.description, row.raw_json) == (source.amount, source.posted_at.date(), source.description, raw):
                unchanged += 1
            elif row.sync_state == SyncState.SYNCED:
                # Never silently rewrite the source of a published expense.
                conflicts += 1
            else:
                material_change = (row.amount, row.txn_date, row.raw_json) != (source.amount, source.posted_at.date(), raw)
                row.amount, row.txn_date, row.description, row.raw_json = source.amount, source.posted_at.date(), source.description, raw
                row.bank_status = 'posted'
                if material_change:
                    row.review_state, row.sync_state = ReviewState.UNREVIEWED, SyncState.NOT_READY
                updated += 1
        db.execute(update(BankSyncState).where(BankSyncState.user_id == user_id,
            BankSyncState.provider == 'simplefin', BankSyncState.lease_until == lease_until).values(successful_through=end, lease_until=None))
        db.commit()
        return {'status': 'synced', 'created': created, 'updated': updated, 'unchanged': unchanged,
                'published_conflicts': conflicts, 'successful_through': end.isoformat(),
                'catchup_remaining': end < now, 'bank_refresh_forced': False,
                'note': 'Fetched provider-available data; this does not force a bank refresh.'}
    except Exception as exc:
        db.rollback()
        db.execute(update(BankSyncState).where(BankSyncState.user_id == user_id,
            BankSyncState.provider == 'simplefin', BankSyncState.lease_until == lease_until).values(lease_until=None))
        db.commit()
        if isinstance(exc, (ProviderError, ValueError)):
            raise
        raise ValueError('Bank sync failed; no transaction changes or checkpoint advance were saved') from None
