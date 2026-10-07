import asyncio
import base64
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.bank_models import BankSyncState
from app.models import Connection, User, Transaction, ReviewState, SyncState
from app.config import settings
from app.security import encrypt
from app.clients.simplefin import BankTransaction, ProviderError, SimpleFINClient, claim_setup_token, normalize, validate_url
from app.services.bank_sync import sync_simplefin

ACCESS = 'https://synthetic:synthetic@bridge.simplefin.org/simplefin'
NOW = datetime(2026, 10, 5, 12)


def payload():
    return {'errlist': [], 'accounts': [{'id': 'checking', 'conn_id': 'synthetic-bank', 'currency': 'USD', 'transactions': [
        {'id': 'purchase', 'posted': 1791158400, 'amount': '-12.50', 'description': 'Synthetic lunch'},
        {'id': 'refund', 'posted': 1791158400, 'amount': '2.50', 'description': 'Synthetic refund'},
        {'id': 'pending', 'posted': 1791158400, 'amount': '-1.00', 'description': 'Pending', 'pending': True},
    ]}]}


def test_normalization_and_currency():
    rows = normalize(payload())
    assert [row.amount for row in rows] == [Decimal('12.50'), Decimal('-2.50')]
    assert all(row.currency == 'USD' for row in rows)


@pytest.mark.parametrize('url', ['http://bridge.simplefin.org/simplefin',
    'https://user:pass@127.0.0.1/simplefin', 'https://user:pass@bridge.simplefin.org.evil.example/simplefin',
    ACCESS + '?secret=value', 'https://user:pass@bridge.simplefin.org:444/simplefin'])
def test_unsafe_urls(url):
    with pytest.raises(ProviderError):
        validate_url(url)


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '1.001', '10000000000', 'bad'])
def test_bad_amounts(value):
    data = payload()
    data['accounts'][0]['transactions'][0]['amount'] = value
    with pytest.raises(ProviderError):
        normalize(data)


def test_provider_errors_and_duplicates():
    with pytest.raises(ProviderError):
        normalize({**payload(), 'errlist': [{'message': 'synthetic provider error'}]})
    data = payload()
    data['accounts'][0]['transactions'].append(data['accounts'][0]['transactions'][0])
    with pytest.raises(ProviderError):
        normalize(data)


def test_mock_http_and_setup_claim():
    requests = []
    def handle(request):
        requests.append(request)
        if request.method == 'POST':
            return httpx.Response(200, text=ACCESS)
        return httpx.Response(200, json=payload())
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            token = base64.b64encode(b'https://bridge.simplefin.org/simplefin/claim/SYNTHETIC').decode()
            assert await claim_setup_token(token, client) == ACCESS
            rows = await SimpleFINClient(ACCESS).transactions(datetime(2026, 10, 1, tzinfo=timezone.utc), NOW.replace(tzinfo=timezone.utc), client)
            assert len(rows) == 2
            assert requests[-1].url.params['pending'] == '0'
            assert requests[-1].url.params['version'] == '2'
            assert requests[-1].headers['authorization'].startswith('Basic ')
    asyncio.run(check())


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'encryption_key', 'synthetic-test-key-only-32-characters-long')
    engine = create_engine(f'sqlite:///{tmp_path}/bank.db')
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as db:
        db.add_all([User(id='alice'), User(id='bob')])
        db.flush()
        for user in ['alice', 'bob']:
            db.add(Connection(user_id=user, provider='simplefin', external_id='primary', secret_ciphertext=encrypt(ACCESS)))
        db.commit()
    yield factory
    engine.dispose()


class Provider:
    def __init__(self):
        self.calls = []
        self.rows = normalize(payload())
        self.fail = False
    async def transactions(self, start, end):
        self.calls.append((start, end))
        if self.fail:
            raise ProviderError('Synthetic failure')
        return self.rows


def test_sync_preservation_corrections_and_user_isolation(sessions):
    provider = Provider()
    async def check():
        with sessions() as db:
            result = await sync_simplefin(db, 'alice', client=provider, now=NOW)
            assert result['created'] == 2
            row = db.scalar(select(Transaction).where(Transaction.user_id == 'alice', Transaction.amount > 0))
            assert json.loads(row.raw_json)['currency'] == 'USD'
            row.review_state = ReviewState.PERSONAL
            db.commit()
            result = await sync_simplefin(db, 'alice', client=provider, now=NOW + timedelta(minutes=10))
            assert result['status'] == 'cached'
            assert len(provider.calls) == 1
            result = await sync_simplefin(db, 'alice', client=provider, now=NOW + timedelta(hours=2))
            assert result['unchanged'] == 2
            assert row.review_state == ReviewState.PERSONAL
            provider.rows[0] = BankTransaction('purchase', provider.rows[0].account_id, provider.rows[0].posted_at, Decimal('15.00'), 'Correction', 'USD')
            result = await sync_simplefin(db, 'alice', client=provider, now=NOW + timedelta(hours=4))
            assert result['updated'] == 1
            db.refresh(row)
            assert row.review_state == ReviewState.UNREVIEWED
            row.sync_state = SyncState.SYNCED
            db.commit()
            provider.rows[0] = BankTransaction('purchase', provider.rows[0].account_id, provider.rows[0].posted_at, Decimal('18.00'), 'Correction', 'USD')
            assert (await sync_simplefin(db, 'alice', client=provider, now=NOW + timedelta(hours=6)))['published_conflicts'] == 1
            db.refresh(row)
            assert row.amount == Decimal('15.00')
            assert (await sync_simplefin(db, 'bob', client=provider, now=NOW))['created'] == 2
    asyncio.run(check())


def test_failed_sync_keeps_checkpoint_and_rate_budget(sessions):
    provider = Provider()
    async def check():
        with sessions() as db:
            await sync_simplefin(db, 'alice', client=provider, now=NOW)
            provider.fail = True
            with pytest.raises(ProviderError):
                await sync_simplefin(db, 'alice', client=provider, now=NOW + timedelta(hours=2))
            state = db.get(BankSyncState, ('alice', 'simplefin'))
            assert state.successful_through == NOW
            assert state.lease_until is None
            assert (await sync_simplefin(db, 'alice', client=provider, now=NOW + timedelta(hours=2, minutes=1)))['status'] == 'cached'
    asyncio.run(check())


def test_simultaneous_requests_share_db_lease(sessions):
    async def check():
        started, release = asyncio.Event(), asyncio.Event()
        class Slow(Provider):
            async def transactions(self, start, end):
                started.set()
                await release.wait()
                return self.rows
        provider = Slow()
        with sessions() as first, sessions() as second:
            task = asyncio.create_task(sync_simplefin(first, 'alice', client=provider, now=NOW))
            await started.wait()
            assert (await sync_simplefin(second, 'alice', client=provider, now=NOW))['status'] == 'cached'
            release.set()
            assert (await task)['created'] == 2
    asyncio.run(check())


def test_long_absence_uses_bounded_catchup_window(sessions):
    provider = Provider()
    with sessions() as db:
        db.add(BankSyncState(user_id='alice', provider='simplefin', successful_through=NOW - timedelta(days=200)))
        db.commit()
        result = asyncio.run(sync_simplefin(db, 'alice', client=provider, now=NOW))
        assert result['catchup_remaining']
        start, end = provider.calls[0]
        assert end - start == timedelta(days=90)


def test_missing_connection_and_weak_encryption(sessions, monkeypatch):
    with sessions() as db:
        with pytest.raises(ValueError, match='not connected'):
            asyncio.run(sync_simplefin(db, 'unknown'))
        monkeypatch.setattr(settings, 'encryption_key', 'dev-only-change-me')
        with pytest.raises(ValueError, match='ENCRYPTION_KEY'):
            asyncio.run(sync_simplefin(db, 'alice'))


def test_account_ids_are_scoped_to_connection_and_empty_accounts_are_valid():
    data = payload()
    other = {**data['accounts'][0], 'conn_id': 'another-bank'}
    data['accounts'].append(other)
    rows = normalize(data)
    assert len(rows) == 4
    assert rows[0].account_id != rows[2].account_id
    assert normalize({'accounts': [{'id': 'empty', 'conn_id': 'bank', 'currency': 'USD'}]}) == []


def test_expired_lease_cannot_overwrite_newer_sync(sessions):
    async def check():
        started, release = asyncio.Event(), asyncio.Event()
        class Slow(Provider):
            async def transactions(self, start, end):
                started.set()
                await release.wait()
                return self.rows
        with sessions() as first, sessions() as second:
            old = asyncio.create_task(sync_simplefin(first, 'alice', client=Slow(), now=NOW))
            await started.wait()
            newer = NOW + timedelta(hours=3)
            assert (await sync_simplefin(second, 'alice', client=Provider(), now=newer))['created'] == 2
            release.set()
            with pytest.raises(ValueError, match='lease expired'):
                await old
            second.expire_all()
            assert second.get(BankSyncState, ('alice', 'simplefin')).successful_through == newer
    asyncio.run(check())
