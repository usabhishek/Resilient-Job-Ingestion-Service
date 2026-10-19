from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field

class IngestRequest(BaseModel):
    source: str = Field(default="greenhouse", description="Source name: 'greenhouse' or 'lever'")
    board_token: str = Field(default="cloudflare", description="Public company board token (e.g. 'cloudflare', 'stripe', 'netflix')")
    allow_fallback: bool = Field(default=True, description="Whether to automatically switch to fallback source on primary failure")
    posted_within_days: int | None = Field(default=None, ge=1, le=3650,
        description="Only keep jobs posted in the last N days (e.g. 7, 30, 60, 180, 365). Empty = any time")

class IngestionSummary(BaseModel):
    run_id: str
    source_name: str
    fallback_used: bool = False
    fallback_source_name: str | None = None
    status: str
    fetched_count: int
    valid_count: int
    invalid_count: int
    new_count: int
    duplicate_count: int
    failed_count: int
    duration_ms: int
    started_at: datetime
    finished_at: datetime | None = None
    error_message: str | None = None
    skipped_old_count: int = 0

class IngestionRunResponse(BaseModel):
    id: str
    source_id: str
    source_name: str | None = None
    fallback_source_id: str | None = None
    fallback_source_name: str | None = None
    trigger_type: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    fetched_count: int
    valid_count: int
    invalid_count: int
    new_count: int
    duplicate_count: int
    failed_count: int
    error_message: str | None = None
    error_details: dict[str, Any] | None = None
    created_at: datetime

    class Config:
        from_attributes = True
