from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "sqlite:///./dev.db"
    app_base_url: str = "http://localhost:8000"
    teller_application_id: str = ""
    teller_environment: str = "sandbox"
    teller_cert_path: str | None = None
    teller_key_path: str | None = None
    splitwise_client_id: str = ""
    splitwise_client_secret: str = ""
    splitwise_redirect_uri: str = "http://localhost:8000/api/splitwise/callback"
    encryption_key: str = "dev-only-change-me"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
