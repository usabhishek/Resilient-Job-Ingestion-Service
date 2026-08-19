from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    
    # Server settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # Database connection string — MUST be set via environment variable.
    # Production: postgresql+asyncpg://postgres:password@db.xxx.supabase.co:5432/postgres
    DATABASE_URL: str  # Required — raises ValidationError on startup if not set
    
    # Ingestion & Network Resilience settings
    DEFAULT_RATE_LIMIT_RPS: float = 2.0
    HTTP_TIMEOUT_SECONDS: float = 15.0
    HTTP_CONNECT_TIMEOUT_SECONDS: float = 5.0
    HTTP_MAX_RETRIES: int = 3
    HTTP_INITIAL_BACKOFF_SECONDS: float = 1.0
    HTTP_MAX_BACKOFF_SECONDS: float = 8.0
    USER_AGENT: str = "AcdyonJobIngestionService/1.0 (+https://acdyon.com/bot)"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

@lru_cache()
def get_settings() -> Settings:
    return Settings()
