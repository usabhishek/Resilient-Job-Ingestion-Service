from datetime import datetime
from pydantic import BaseModel

class SourceResponse(BaseModel):
    id: int
    name: str
    slug: str
    base_url: str
    is_active: bool
    rate_limit_rps: float
    created_at: datetime
    updated_at: datetime
    total_jobs: int = 0
    last_run_status: str | None = None
    last_run_at: datetime | None = None

    class Config:
        from_attributes = True

class SourceHealthResponse(BaseModel):
    source_name: str
    is_healthy: bool
    status_code: int | None = None
    latency_ms: float | None = None
    message: str
