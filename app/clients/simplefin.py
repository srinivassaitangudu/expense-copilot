"""SimpleFIN Bridge adapter. Secrets stay outside tool arguments and logs."""
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import unquote, urlsplit
import httpx

HOSTS = {'bridge.simplefin.org', 'beta-bridge.simplefin.org'}


class ProviderError(ValueError):
    pass


@dataclass(frozen=True)
class BankTransaction:
    source_id: str
    account_id: str
    posted_at: datetime
    amount: Decimal
    description: str
    currency: str


def validate_url(value: str, *, claim=False):
    try:
        parts = urlsplit(value)
        valid = parts.scheme == 'https' and parts.hostname in HOSTS and parts.port in (None, 443) and not parts.query and not parts.fragment
        if claim:
            valid = valid and not parts.username and not parts.password and parts.path.startswith('/simplefin/claim/')
        else:
            valid = valid and bool(parts.username) and bool(parts.password) and parts.path.rstrip('/') == '/simplefin'
        if not valid:
            raise ValueError()
        return parts
    except (ValueError, TypeError, AttributeError):
        raise ProviderError('Invalid SimpleFIN URL; only the official HTTPS Bridge hosts are supported') from None


async def claim_setup_token(token: str, client=None):
    try:
        if not 1 <= len(token) <= 4096:
            raise ValueError()
        url = base64.b64decode(token, validate=True).decode('utf-8')
    except (ValueError, UnicodeError):
        raise ProviderError('Invalid SimpleFIN setup token') from None
    validate_url(url, claim=True)
    async def claim(http):
        try:
            response = await http.post(url, content=b'')
            response.raise_for_status()
            access_url = response.text.strip()
            validate_url(access_url)
            return access_url
        except httpx.HTTPError:
            raise ProviderError('SimpleFIN setup failed; the token may have been claimed already') from None
    if client is not None:
        return await claim(client)
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as http:
        return await claim(http)


class SimpleFINClient:
    def __init__(self, access_url: str):
        parts = validate_url(access_url)
        self.endpoint = f'https://{parts.hostname}/simplefin/accounts'
        self.auth = httpx.BasicAuth(unquote(parts.username), unquote(parts.password))

    async def transactions(self, start: datetime, end: datetime, client=None):
        if end <= start or (end - start).total_seconds() > 90 * 86400:
            raise ProviderError('SimpleFIN fetch windows must be between 0 and 90 days')
        async def fetch(http):
            try:
                response = await http.get(self.endpoint, auth=self.auth, params={
                    'start-date': int(start.timestamp()), 'end-date': int(end.timestamp()),
                    'pending': 0, 'version': 2,
                })
                response.raise_for_status()
                return normalize(response.json())
            except (httpx.HTTPError, ValueError, TypeError, KeyError):
                raise ProviderError('SimpleFIN fetch failed or returned incomplete/invalid data; reconnect or retry later') from None
        if client is not None:
            return await fetch(client)
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as http:
            return await fetch(http)


def normalize(payload):
    # Fail the complete fetch, not a misleading partial success. Do not echo provider errors.
    if not isinstance(payload, dict) or payload.get('errors') or payload.get('errlist'):
        raise ProviderError('SimpleFIN reported incomplete data; reconnect or retry later')
    accounts = payload.get('accounts')
    if not isinstance(accounts, list):
        raise ProviderError('Missing SimpleFIN account data')
    result = []
    seen = set()
    for account in accounts:
        if not isinstance(account, dict) or not isinstance(account.get('id'), str) or not account['id']:
            raise ProviderError('Invalid SimpleFIN account')
        connection_id = account.get('conn_id')
        if not isinstance(connection_id, str) or not connection_id or len(connection_id) > 200 or len(account['id']) > 200:
            raise ProviderError('Invalid SimpleFIN connection/account identity')
        # Protocol v2 account IDs are unique within a connection, not the whole bridge.
        account_id = f"{len(connection_id)}:{connection_id}:{account['id']}"
        currency = account.get('currency')
        if not isinstance(currency, str) or not re.fullmatch('[A-Z]{3}', currency):
            raise ProviderError('SimpleFIN currency must be a three-letter currency code')
        transactions = account.get('transactions', [])
        if not isinstance(transactions, list):
            raise ProviderError('Missing SimpleFIN transactions')
        for row in transactions:
            if not isinstance(row, dict):
                raise ProviderError('Invalid SimpleFIN transaction')
            # Pending rows never enter the posted-expense workflow.
            if not isinstance(row.get('pending', False), bool):
                raise ProviderError('Invalid SimpleFIN pending status')
            if row.get('pending'):
                continue
            source_id, description = row.get('id'), row.get('description')
            if not isinstance(source_id, str) or not source_id or not isinstance(description, str):
                raise ProviderError('Invalid SimpleFIN transaction identity or description')
            if len(source_id) > 200 or len(description) > 2000:
                raise ProviderError('SimpleFIN field exceeds storage limits')
            identity = (account_id, source_id)
            if identity in seen:
                raise ProviderError('SimpleFIN returned duplicate transaction identities')
            seen.add(identity)
            try:
                # SimpleFIN outflows are negative; Expense Copilot expenses are positive.
                amount = -Decimal(str(row['amount']))
                if not amount.is_finite() or abs(amount) >= Decimal('10000000000') or amount != amount.quantize(Decimal('.01')):
                    raise ValueError()
                posted = row['posted']
                if isinstance(posted, bool) or not isinstance(posted, (int, float)) or posted <= 0:
                    raise ValueError()
                posted_at = datetime.fromtimestamp(posted, timezone.utc)
            except (ValueError, KeyError, InvalidOperation, OverflowError, OSError):
                raise ProviderError('Invalid SimpleFIN amount or posted timestamp') from None
            result.append(BankTransaction(source_id, account_id, posted_at, amount, description, currency))
    return result
