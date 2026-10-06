import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.db import Base, get_db
from app.main import app
from app.models import Transaction, User
from app.services.imports import import_csv

HEADER = 'transaction_id,account_id,date,amount,description\n'
CSV = HEADER + 'a,checking,2026-10-01,12.50,Lunch\nb,checking,2026-10-01,12.50,Lunch\n'

@pytest.fixture
def db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        yield session
    engine.dispose()

@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_import_review_reimport(client):
    assert client.post('/api/transactions/import/csv', json={'csv': CSV}).json() == {'created': 2, 'skipped': 0}
    rows = client.get('/api/transactions/unreviewed').json()
    assert len(rows) == 2
    assert rows[0]['amount'] == '12.50'
    assert client.post(f"/api/transactions/{rows[0]['id']}/review", json={'decision': 'personal'}).status_code == 200
    assert client.post('/api/transactions/import/csv', json={'csv': CSV}).json() == {'created': 0, 'skipped': 2}
    assert len(client.get('/api/transactions/unreviewed').json()) == 1

@pytest.mark.parametrize('bad', ['NaN', 'Infinity', '1.001', '10000000000', 'not-money'])
def test_bad_amount_is_atomic(client, bad):
    response = client.post('/api/transactions/import/csv', json={'csv': CSV + f'c,checking,2026-10-02,{bad},Bad\n'})
    assert response.status_code == 422
    assert client.get('/api/transactions/unreviewed').json() == []

@pytest.mark.parametrize('content', [HEADER, CSV + 'a,checking,2026-10-01,12.50,Lunch\n', 'bad,header\nx,y\n', HEADER + 'a,checking,invalid,1,Test\n', HEADER + 'a,checking,2026-10-01,1\n'])
def test_invalid_csv(client, content):
    assert client.post('/api/transactions/import/csv', json={'csv': content}).status_code == 422
    assert client.get('/api/transactions/unreviewed').json() == []


def test_identity_is_scoped_by_user_and_account(db):
    db.add_all([User(id='one'), User(id='two')]); db.commit()
    assert import_csv(db, 'one', CSV)['created'] == 2
    assert import_csv(db, 'two', CSV)['created'] == 2
    assert import_csv(db, 'one', CSV.replace('checking', 'savings'))['created'] == 2
    assert len(db.scalars(select(Transaction)).all()) == 6
