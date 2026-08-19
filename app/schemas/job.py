from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field, HttpUrl, field_validator

class JobNormalized(BaseModel):
    """
    Standardized, source-agnostic job model after adapter normalization.
    """
    external_id: str = Field(..., min_length=1, description="Source's unique identifier for this job")
    source: str = Field(..., min_length=1, description="Source identifier e.g. 'greenhouse' or 'lever'")
    title: str = Field(..., min_length=1, description="Job title")
    company: str = Field(..., min_length=1, description="Company name")
    location: str = Field(default="Remote / Unspecified", description="Job location")
    description: str | None = Field(default=None, description="HTML or plaintext job description")
    job_url: str = Field(..., description="Canonical URL to view or apply for the job")
    posted_at: datetime | None = Field(default=None, description="Timestamp when job was posted")
    raw_payload: dict[str, Any] | list[Any] | None = Field(default=None, description="Raw source payload for debugging")

    @field_validator("title", "company", mode="before")
    @classmethod
    def strip_and_validate_strings(cls, v: Any) -> str:
        if v is None:
            raise ValueError("Field cannot be None")
        val = str(v).strip()
        if not val:
            raise ValueError("Field cannot be empty")
        return val

    @field_validator("external_id", mode="before")
    @classmethod
    def sanitize_external_id(cls, v: Any) -> str:
        if v is None:
            raise ValueError("external_id cannot be None")
        val = str(v).strip()
        if not val:
            raise ValueError("external_id cannot be empty")
        return val

    @field_validator("job_url", mode="before")
    @classmethod
    def sanitize_job_url(cls, v: Any) -> str:
        if not v:
            raise ValueError("job_url is required")
        return str(v).strip()

class JobResponse(BaseModel):
    id: str
    source_id: int
    source_name: str | None = None
    external_id: str
    title: str
    company: str
    location: str
    description: str | None = None
    job_url: str
    posted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    page: int
    limit: int
    pages: int
