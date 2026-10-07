import os
from pathlib import Path
import pytest
from sqlalchemy import create_engine, text
from app.db import Base
import app.models
from scripts.init_hosted_db import validate_hosted_url, initialize_schema


def test_hosted_database_configuration_requires_persistence_and_verified_tls(tmp_path):
    with pytest.raises(ValueError, match='postgresql'):
        validate_hosted_url('sqlite:///local.db')
    with pytest.raises(ValueError, match='verify-full'):
        validate_hosted_url('postgresql+psycopg://user:placeholder@example.invalid/db?sslmode=require')
    with pytest.raises(ValueError, match='missing'):
        validate_hosted_url('postgresql+psycopg://user:placeholder@example.invalid/db?sslmode=verify-full&sslrootcert=/not/a/certificate')
    # Configuration validation does not claim this placeholder is a usable CA.
    ca = tmp_path / 'synthetic-ca'
    ca.write_text('synthetic test placeholder')
    validate_hosted_url(f'postgresql+psycopg://user:placeholder@example.invalid/db?sslmode=verify-full&sslrootcert={ca}')


@pytest.mark.skipif(not os.environ.get('POSTGRES_TEST_URL'), reason='Disposable Postgres test service not configured')
def test_postgres_schema_blocks_public_roles():
    from sqlalchemy.engine import make_url
    url = os.environ['POSTGRES_TEST_URL']
    assert make_url(url).database == 'expense_copilot_test'
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            for role in ('anon', 'authenticated'):
                if not connection.scalar(text('SELECT 1 FROM pg_roles WHERE rolname=:role'), {'role': role}):
                    connection.execute(text(f'CREATE ROLE {role} NOLOGIN'))
            initialize_schema(connection, Base.metadata)
            for table in Base.metadata.sorted_tables:
                assert connection.scalar(text('SELECT relrowsecurity FROM pg_class WHERE relname=:table'), {'table': table.name})
                for role in ('anon', 'authenticated'):
                    assert not connection.scalar(text('SELECT has_table_privilege(:role, :table, :privilege)'),
                                                 {'role': role, 'table': table.name, 'privilege': 'SELECT'})
            # The trusted backend owner remains able to access tables.
            assert connection.scalar(text('SELECT count(*) FROM users')) == 0
    finally:
        with engine.begin() as connection:
            Base.metadata.drop_all(connection)
        engine.dispose()
