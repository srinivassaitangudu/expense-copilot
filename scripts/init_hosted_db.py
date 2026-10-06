"""Initialize persistent Postgres atomically without exposing tables through REST."""
import importlib.util
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.engine import make_url


def validate_hosted_url(value):
    url = make_url(value)
    if url.drivername != 'postgresql+psycopg':
        raise ValueError('Hosted deployment requires postgresql+psycopg, not local SQLite')
    if url.query.get('sslmode') != 'verify-full' or not url.query.get('sslrootcert'):
        raise ValueError('Hosted database requires sslmode=verify-full and sslrootcert')
    if not Path(url.query['sslrootcert']).is_file():
        raise ValueError('The configured database CA certificate file is missing')


def initialize_schema(connection, metadata):
    metadata.create_all(connection)
    quote = connection.dialect.identifier_preparer.quote
    for table in metadata.sorted_tables:
        # Supabase's public schema is API-exposed by default. Backend DB owner
        # remains trusted; MCP service authorization is enforced in application code.
        name = f'{quote(table.schema or "public")}.{quote(table.name)}'
        connection.execute(text(f'ALTER TABLE {name} ENABLE ROW LEVEL SECURITY'))
        connection.execute(text(f'REVOKE ALL ON TABLE {name} FROM anon, authenticated'))


def main():
    from app.config import settings
    validate_hosted_url(settings.database_url)
    if len(settings.encryption_key) < 32 or settings.encryption_key == 'dev-only-change-me':
        raise ValueError('Hosted deployment requires a strong ENCRYPTION_KEY')
    for module in ('app.mcp_http', 'app.services.bank_sync'):
        if importlib.util.find_spec(module) is None:
            raise ValueError('Merge MCP and bank-ingestion changes before hosting')
    from app.mcp_settings import MCPSettings
    MCPSettings().require_oauth()
    from app.db import Base, engine
    import app.models
    import app.bank_models
    with engine.begin() as connection:
        initialize_schema(connection, Base.metadata)
    print('Hosted database initialized with protected tables.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # DB exceptions can contain credential URLs or financial query parameters.
        raise SystemExit('Hosted initialization failed. Check private database/TLS, OAuth, encryption settings and required PRs.') from None
