"""OAuth resource-server verification; login and consent belong to the issuer."""
import hashlib
import time
import httpx
import jwt
from mcp.server.auth.provider import AccessToken


def user_id_for_subject(issuer: str, subject: str) -> str:
    return 'oauth:' + hashlib.sha256(f'{issuer}\0{subject}'.encode()).hexdigest()


class JWTVerifier:
    def __init__(self, config):
        self.config = config
        self.keys = []
        self.fetched_at = 0.0

    async def verify_token(self, token: str):
        try:
            header = jwt.get_unverified_header(token)
            if header.get('alg') not in ('RS256', 'ES256') or not isinstance(header.get('kid'), str):
                return None
            now = time.monotonic()
            if now - self.fetched_at > 300 or not self.keys:
                async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                    response = await client.get(self.config.oauth_jwks_url)
                    response.raise_for_status()
                    self.keys = response.json()['keys']
                    self.fetched_at = now
            key_data = next((key for key in self.keys if key.get('kid') == header['kid']), None)
            if key_data is None:
                return None  # Unknown keys fail closed; cache refreshes within five minutes.
            key = jwt.PyJWK.from_dict(key_data, algorithm=header['alg'])
            claims = jwt.decode(token, key.key, algorithms=[header['alg']],
                                issuer=self.config.oauth_issuer,
                                audience=self.config.mcp_base_url + '/mcp',
                                options={'require': ['exp', 'iat', 'sub', 'iss', 'aud']})
            subject = claims['sub']
            if not isinstance(subject, str) or subject not in self.config.oauth_allowed_subjects:
                return None
            scopes = claims.get('scope', '').split()
            return AccessToken(token=token, client_id=claims.get('azp', claims.get('client_id', 'oauth-client')),
                               scopes=scopes, expires_at=claims['exp'], subject=subject,
                               resource=self.config.mcp_base_url + '/mcp')
        except (jwt.PyJWTError, httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            return None
