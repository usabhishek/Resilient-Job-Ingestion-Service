from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from app.schemas.job import JobNormalized
from app.core.http_client import ResilientHttpClient

@dataclass
class SourceHealthResult:
    source_name: str
    is_healthy: bool
    latency_ms: float
    message: str
    status_code: int | None = None

class JobSource(ABC):
    """
    Abstract Source Interface.
    All external job boards/APIs must implement this interface to maintain
    total decoupling from the ingestion engine.
    """
    def __init__(self, http_client: ResilientHttpClient):
        self.http_client = http_client

    @property
    @abstractmethod
    def base_url(self) -> str:
        """Returns the base API URL of the source."""
        pass

    @abstractmethod
    def source_name(self) -> str:
        """Returns the identifier name of the source (e.g. 'greenhouse', 'lever')."""
        pass

    @abstractmethod
    async def fetch_raw_data(self, board_token: str) -> list[dict[str, Any]]:
        """Fetches raw unprocessed job records from the upstream source."""
        pass

    @abstractmethod
    def normalize_item(self, raw_item: dict[str, Any], board_token: str) -> JobNormalized:
        """Transforms a single raw item into a standardized JobNormalized schema."""
        pass

    @abstractmethod
    async def health_check(self) -> SourceHealthResult:
        """Performs a lightweight ping/health-check on the upstream source."""
        pass
