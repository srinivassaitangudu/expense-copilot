from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from urllib.parse import urlsplit


class MCPSettings(BaseSettings):
    mcp_base_url: str = 'http://localhost:8000'
    oauth_issuer: str = ''
    oauth_jwks_url: str = ''
    oauth_allowed_subjects: list[str] = []
    local_user_id: str = 'dev-user'
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    @field_validator('mcp_base_url')
    @classmethod
    def base_url(cls, value):
        parts = urlsplit(value)
        if parts.scheme not in ('https', 'http') or not parts.hostname or parts.username or parts.query or parts.fragment or parts.path not in ('', '/'):
            raise ValueError('MCP_BASE_URL must be an origin URL')
        if parts.scheme == 'http' and parts.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Remote MCP_BASE_URL must use HTTPS')
        return value.rstrip('/')

    def require_oauth(self):
        for value in (self.oauth_issuer, self.oauth_jwks_url):
            parts = urlsplit(value)
            if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.fragment:
                raise ValueError('Hosted MCP requires HTTPS OAUTH_ISSUER and OAUTH_JWKS_URL')
        if not self.oauth_allowed_subjects:
            raise ValueError('Set OAUTH_ALLOWED_SUBJECTS to the permitted personal-account subjects')
