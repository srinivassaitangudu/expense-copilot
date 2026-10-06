"""Operator-only setup; credentials are entered privately, never as MCP arguments."""
import argparse
import asyncio
import getpass
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Connection, User
from app.clients.simplefin import claim_setup_token
from app.services.bank_sync import require_encryption
from app.security import encrypt


async def connect(user_id):
    require_encryption()
    token = getpass.getpass('SimpleFIN one-time setup token (hidden): ').strip()
    access_url = await claim_setup_token(token)
    with SessionLocal() as db:
        if not db.get(User, user_id):
            db.add(User(id=user_id))
            db.flush()
        row = db.scalar(select(Connection).where(Connection.user_id == user_id,
            Connection.provider == 'simplefin', Connection.external_id == 'primary'))
        if row is None:
            row = Connection(user_id=user_id, provider='simplefin', external_id='primary')
            db.add(row)
        row.secret_ciphertext = encrypt(access_url)
        db.commit()
    print('SimpleFIN connection saved. No credentials were printed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id', required=True, help='Database user ID from your authenticated MCP get_status tool')
    args = parser.parse_args()
    try:
        asyncio.run(connect(args.user_id))
    except Exception:
        # Setup tokens are one-use; DB failures after claim require generating another.
        raise SystemExit('Connection setup failed. Check encryption/database settings and generate a new setup token if it was claimed.') from None


if __name__ == '__main__':
    main()
