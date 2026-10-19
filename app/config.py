
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # Server settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # MongoDB connection (local MongoDB or MongoDB Atlas)
    MONGODB_URI: str
    MONGODB_DB: str = "job_ingestion"

    # Login / sessions
    SESSION_DAYS: int = 7

    # Optional: create an admin account at startup when both are set
    ADMIN_EMAIL: str | None = None
    ADMIN_PASSWORD: str | None = None

    # Ingestion & network resilience settings
    DEFAULT_RATE_LIMIT_RPS: float = 2.0
    HTTP_TIMEOUT_SECONDS: float = 15.0
    HTTP_CONNECT_TIMEOUT_SECONDS: float = 5.0
    HTTP_MAX_RETRIES: int = 3
    HTTP_INITIAL_BACKOFF_SECONDS: float = 1.0
    HTTP_MAX_BACKOFF_SECONDS: float = 8.0

    # HTTP identity for external job-board requests
    USER_AGENT: str = "ResilientJobIngestionService/1.0"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
