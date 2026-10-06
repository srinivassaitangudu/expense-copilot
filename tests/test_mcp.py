import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db import Base
from app.models import Transaction, ReviewState, SyncState
from app.mcp_auth import JWTVerifier, user_id_for_subject
from app.mcp_http import create_app
from app.mcp_settings import MCPSettings
import app.mcp_server as boundary

CSV = 'transaction_id,account_id,date,amount,description\na,demo,2026-10-01,12.50,Synthetic lunch\nb,demo,2026-10-02,20.00,Synthetic groceries\n'


def config():
    return MCPSettings(mcp_base_url='https://mcp.example', oauth_issuer='https://issuer.example/',
                       oauth_jwks_url='https://issuer.example/jwks', oauth_allowed_subjects=['alice', 'bob'])


@pytest.fixture
def signed_verifier():
    cfg = config()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    public['kid'] = 'test-key'
    verifier = JWTVerifier(cfg)
    verifier.keys = [public]
    verifier.fetched_at = time.monotonic()

    def sign(**overrides):
        claims = {'sub': 'alice', 'iss': cfg.oauth_issuer, 'aud': cfg.mcp_base_url + '/mcp',
                  'exp': int(time.time()) + 300, 'iat': int(time.time()),
                  'scope': 'expenses:read expenses:write'}
        claims.update(overrides)
        return jwt.encode(claims, key, algorithm='RS256', headers={'kid': 'test-key'})
    return verifier, sign


def test_jwt_validation(signed_verifier):
    verifier, sign = signed_verifier
    async def check():
        assert (await verifier.verify_token(sign())).subject == 'alice'
        for overrides in [{'aud': 'another-api'}, {'iss': 'https://wrong.example/'}, {'exp': 1},
                          {'sub': 'mallory'}, {'iat': int(time.time()) + 999}, {'scope': []}]:
            assert await verifier.verify_token(sign(**overrides)) is None
        assert await verifier.verify_token('not-a-token') is None
        assert await verifier.verify_token(jwt.encode({'sub': 'alice'}, 'untrusted', algorithm='HS256')) is None
    asyncio.run(check())


def test_hosted_fails_closed():
    with pytest.raises(ValueError):
        create_app(MCPSettings())


def test_stdio_end_to_end(tmp_path):
    env = {**os.environ, 'DATABASE_URL': f'sqlite:///{tmp_path}/stdio.db', 'LOCAL_USER_ID': 'test-local'}
    subprocess.run([sys.executable, '-m', 'scripts.init_db'], check=True, env=env, stdout=subprocess.DEVNULL)
    async def check():
        params = StdioServerParameters(command=sys.executable, args=['-m', 'app.mcp_server'], env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                names = {tool.name for tool in (await client.list_tools()).tools}
                assert {'get_status', 'import_transactions_csv', 'list_unreviewed_transactions', 'review_transaction_decision'} <= names
                assert 'push_verified_expenses' not in names
                result = await client.call_tool('import_transactions_csv', {'csv': CSV})
                assert result.structuredContent == {'created': 2, 'skipped': 0}
                listed = await client.call_tool('list_unreviewed_transactions', {'limit': 1})
                assert listed.structuredContent['next_offset'] == 1
                row_id = listed.structuredContent['transactions'][0]['id']
                result = await client.call_tool('review_transaction_decision', {'transaction_id': row_id, 'decision': 'personal'})
                assert result.structuredContent['published_to_splitwise'] is False
                assert (await client.call_tool('import_transactions_csv', {'csv': CSV})).structuredContent['skipped'] == 2
        # Restart process and confirm persistence.
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                result = await client.call_tool('list_unreviewed_transactions')
                assert len(result.structuredContent['transactions']) == 1
    asyncio.run(check())


def test_http_protocol_and_user_isolation(monkeypatch, signed_verifier):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    monkeypatch.setattr(boundary, 'SessionLocal', sessions)
    verifier, sign = signed_verifier
    application = create_app(config(), verifier)
    async def call_as(token, fn):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), headers={'Authorization': f'Bearer {token}'}) as http:
            async with streamable_http_client('https://mcp.example/mcp', http_client=http) as (read, write, _):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    return await fn(client)

    async def check():
        async with application.router.lifespan_context(application):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url='https://mcp.example') as http:
                assert (await http.get('/healthz')).json() == {'ok': True}
                assert (await http.get('/api/transactions/unreviewed')).status_code == 404
                response = await http.post('/mcp', json={})
                assert response.status_code == 401
                assert 'resource_metadata=' in response.headers['www-authenticate']
                meta = (await http.get('/.well-known/oauth-protected-resource/mcp')).json()
                assert meta['resource'] == 'https://mcp.example/mcp'
                assert meta['scopes_supported'] == ['expenses:read', 'expenses:write']
                assert (await http.post('/mcp', headers={'Authorization': 'Bearer bad'}, json={})).status_code == 401
            async def alice(client):
                assert (await client.call_tool('import_transactions_csv', {'csv': CSV})).structuredContent['created'] == 2
                return (await client.call_tool('list_unreviewed_transactions')).structuredContent['transactions'][0]['id']
            row_id = await call_as(sign(), alice)
            async def bob(client):
                assert (await client.call_tool('list_unreviewed_transactions')).structuredContent['transactions'] == []
                assert (await client.call_tool('review_transaction_decision', {'transaction_id': row_id, 'decision': 'shared'})).isError
            await call_as(sign(sub='bob'), bob)
            async def read_only(client):
                assert not (await client.call_tool('list_unreviewed_transactions')).isError
                assert (await client.call_tool('import_transactions_csv', {'csv': CSV})).isError
            await call_as(sign(scope='expenses:read'), read_only)
            async def review(client):
                assert not (await client.call_tool('review_transaction_decision', {'transaction_id': row_id, 'decision': 'shared'})).isError
                return (await client.call_tool('list_unreviewed_transactions')).structuredContent
            assert len((await call_as(sign(), review))['transactions']) == 1
            with sessions() as db:
                row = db.get(Transaction, row_id)
                assert row.review_state == ReviewState.SHARED
                assert row.sync_state == SyncState.READY
                assert row.user_id == user_id_for_subject(config().oauth_issuer, 'alice')
    try:
        asyncio.run(check())
    finally:
        engine.dispose()


def test_review_rejects_pending_refunds_and_published(monkeypatch):
    from app.services.review import review_transaction
    from app.models import User
    from datetime import date
    from decimal import Decimal
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    with sessions() as db:
        db.add(User(id='owner'))
        db.flush()
        row = Transaction(user_id='owner', teller_transaction_id='test', account_id='demo',
                          amount=Decimal('1.00'), txn_date=date(2026, 10, 1), description='Synthetic', bank_status='pending')
        db.add(row)
        db.commit()
        with pytest.raises(ValueError, match='posted positive'):
            review_transaction(db, 'owner', row.id, ReviewState.SHARED)
        row.bank_status = 'posted'
        row.amount = Decimal('-1.00')
        db.commit()
        with pytest.raises(ValueError, match='posted positive'):
            review_transaction(db, 'owner', row.id, ReviewState.SHARED)
        row.sync_state = SyncState.SYNCED
        db.commit()
        with pytest.raises(ValueError, match='Already-published'):
            review_transaction(db, 'owner', row.id, ReviewState.PERSONAL)
    engine.dispose()
