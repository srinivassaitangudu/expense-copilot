"""Runs when the separately reviewable MCP and ingestion changes are composed."""
import asyncio
import importlib.util
import time

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

HAS_COMPONENTS = all(importlib.util.find_spec(module) is not None for module in ('app.mcp_http', 'app.services.bank_sync'))


@pytest.mark.skipif(not HAS_COMPONENTS, reason='Merge/compose MCP and bank-ingestion PRs for combined verification')
def test_authenticated_mcp_sync_review_and_restart(monkeypatch):
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from app.db import Base
    from app.models import Connection, User
    import app.bank_models
    import app.mcp_server as boundary
    from app.mcp_http import create_app
    from app.mcp_settings import MCPSettings
    from app.mcp_auth import JWTVerifier, user_id_for_subject
    from app.security import encrypt
    from app.config import settings

    config = MCPSettings(mcp_base_url='https://mcp.example', oauth_issuer='https://issuer.example/',
                         oauth_jwks_url='https://issuer.example/jwks', oauth_allowed_subjects=['synthetic-user'])
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = JWTVerifier(config)
    public = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    public['kid'] = 'synthetic-key'
    verifier.keys, verifier.fetched_at = [public], time.monotonic()
    token = jwt.encode({'sub': 'synthetic-user', 'iss': config.oauth_issuer,
                        'aud': config.mcp_base_url + '/mcp', 'iat': int(time.time()),
                        'exp': int(time.time()) + 300, 'scope': 'expenses:read expenses:write'},
                       key, algorithm='RS256', headers={'kid': 'synthetic-key'})
    monkeypatch.setattr(settings, 'encryption_key', 'synthetic-only-encryption-key-32-chars-long')
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    monkeypatch.setattr(boundary, 'SessionLocal', sessions)
    user_id = user_id_for_subject(config.oauth_issuer, 'synthetic-user')
    with sessions() as db:
        db.add(User(id=user_id))
        db.flush()
        db.add(Connection(user_id=user_id, provider='simplefin', external_id='primary',
                          secret_ciphertext=encrypt('https://synthetic:synthetic@bridge.simplefin.org/simplefin')))
        db.commit()

    bank_calls = []
    def provider(request):
        bank_calls.append(request)
        assert request.url.host == 'bridge.simplefin.org'
        assert request.url.params['pending'] == '0'
        return httpx.Response(200, json={'errlist': [], 'accounts': [{
            'id': 'checking', 'conn_id': 'synthetic-bank', 'currency': 'USD', 'transactions': [
                {'id': 'expense', 'posted': int(time.time()) - 86400, 'amount': '-12.50', 'description': 'Synthetic lunch'},
            ],
        }]})
    real_client = httpx.AsyncClient
    def client_factory(*args, **kwargs):
        if 'transport' not in kwargs:
            kwargs['transport'] = httpx.MockTransport(provider)
        return real_client(*args, **kwargs)
    monkeypatch.setattr(httpx, 'AsyncClient', client_factory)

    async def session(application, action):
        async with application.router.lifespan_context(application):
            async with real_client(transport=httpx.ASGITransport(app=application),
                                   headers={'Authorization': f'Bearer {token}'}) as http:
                from mcp.client.streamable_http import streamable_http_client
                async with streamable_http_client('https://mcp.example/mcp', http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as client:
                        await client.initialize()
                        return await action(client)

    async def check():
        async def first(client):
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert 'sync_transactions' in names
            assert (await client.call_tool('get_status')).structuredContent['bank_sync_available']
            synced = await client.call_tool('sync_transactions')
            assert synced.structuredContent['created'] == 1
            assert synced.structuredContent['bank_refresh_forced'] is False
            row = (await client.call_tool('list_unreviewed_transactions')).structuredContent['transactions'][0]
            assert row['currency'] == 'USD'
            assert row['amount'] == '12.50'
            assert not (await client.call_tool('review_transaction_decision', {'transaction_id': row['id'], 'decision': 'personal'})).isError
            assert (await client.call_tool('sync_transactions')).structuredContent['status'] == 'cached'
        await session(create_app(config, verifier), first)
        async def restarted(client):
            assert (await client.call_tool('list_unreviewed_transactions')).structuredContent['transactions'] == []
            assert (await client.call_tool('sync_transactions')).structuredContent['status'] == 'cached'
        await session(create_app(config, verifier), restarted)
        assert len(bank_calls) == 1
    try:
        asyncio.run(check())
    finally:
        engine.dispose()
