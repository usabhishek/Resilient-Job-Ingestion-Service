import pytest
import httpx
from unittest.mock import AsyncMock
from app.services.ingestion import IngestionPipeline
from app.core.http_client import ResilientHttpClient
from app.core.rate_limiter import TokenBucketRateLimiter
from app.core.retry import RetryPolicy
from app.core.exceptions import (
    HttpTimeoutError,
    RateLimitExceededError,
    TemporarySourceError,
    MalformedResponseError
)

# Mock Data Fixtures
SAMPLE_GREENHOUSE_JOBS = {
    "jobs": [
        {
            "id": 5001,
            "title": "Senior Security Engineer",
            "content": "<p>Security description</p>",
            "absolute_url": "https://boards.greenhouse.io/cloudflare/jobs/5001",
            "location": {"name": "Austin, TX / Remote"},
            "updated_at": "2026-08-01T12:00:00Z"
        },
        {
            "id": 5002,
            "title": "Product Designer",
            "content": "<p>Design systems</p>",
            "absolute_url": "https://boards.greenhouse.io/cloudflare/jobs/5002",
            "location": {"name": "San Francisco, CA"},
            "updated_at": "2026-08-02T12:00:00Z"
        }
    ]
}

@pytest.mark.asyncio
async def test_pipeline_success_flow(db):
    """
    Test complete pipeline success:
    fetch -> rate limit -> retry -> normalize -> validate -> deduplicate -> persist -> metrics
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE_GREENHOUSE_JOBS)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    rate_limiter = TokenBucketRateLimiter(rate_limit_rps=100.0)
    retry_policy = RetryPolicy(max_retries=2, initial_backoff=0.01)
    http_client = ResilientHttpClient(rate_limiter=rate_limiter, retry_policy=retry_policy, client=client)

    pipeline = IngestionPipeline(http_client=http_client)

    summary = await pipeline.run_ingestion(
        db=db,
        owner_id="u1",
        source_name="greenhouse",
        board_token="cloudflare",
        allow_fallback=False
    )

    assert summary.status == "SUCCESS"
    assert summary.fetched_count == 2
    assert summary.valid_count == 2
    assert summary.invalid_count == 0
    assert summary.new_count == 2
    assert summary.duplicate_count == 0
    assert summary.failed_count == 0
    assert summary.duration_ms >= 0

    # Verify persisted in database
    jobs = list(db.jobs.find({"company": "Cloudflare"}))
    assert len(jobs) == 2

    # Verify ingestion_runs record
    run_entry = db.ingestion_runs.find_one({"_id": summary.run_id})
    assert run_entry is not None
    assert run_entry["status"] == "SUCCESS"
    assert run_entry["new_count"] == 2

@pytest.mark.asyncio
async def test_pipeline_deduplication(db):
    """
    Test deduplication across multiple runs:
    Run 1: inserts N new jobs
    Run 2: detects N duplicate jobs without re-inserting
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE_GREENHOUSE_JOBS)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    http_client = ResilientHttpClient(
        rate_limiter=TokenBucketRateLimiter(rate_limit_rps=100.0),
        client=client
    )
    pipeline = IngestionPipeline(http_client=http_client)

    # First run
    run1 = await pipeline.run_ingestion(db, "u1", "greenhouse", "cloudflare", allow_fallback=False)
    assert run1.new_count == 2
    assert run1.duplicate_count == 0

    # Second run with same data
    run2 = await pipeline.run_ingestion(db, "u1", "greenhouse", "cloudflare", allow_fallback=False)
    assert run2.new_count == 0
    assert run2.duplicate_count == 2
    assert run2.fetched_count == 2
    assert run2.status == "SUCCESS"

@pytest.mark.asyncio
async def test_pipeline_empty_data_handling(db):
    """
    Test source returning 200 OK with empty list [] or {"jobs": []} is classified as EMPTY_RESPONSE.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobs": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    http_client = ResilientHttpClient(
        rate_limiter=TokenBucketRateLimiter(rate_limit_rps=100.0),
        client=client
    )
    pipeline = IngestionPipeline(http_client=http_client)

    summary = await pipeline.run_ingestion(db, "u1", "greenhouse", "empty-company", allow_fallback=False)
    assert summary.status == "EMPTY_RESPONSE"
    assert summary.fetched_count == 0
    assert summary.new_count == 0

@pytest.mark.asyncio
async def test_pipeline_timeout_handling(db):
    """
    Test network timeout during fetch triggers retry policy and handles error cleanly.
    """
    attempts = 0
    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("Timeout reading Greenhouse API", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    retry_policy = RetryPolicy(max_retries=2, initial_backoff=0.01, max_backoff=0.05)
    http_client = ResilientHttpClient(
        rate_limiter=TokenBucketRateLimiter(rate_limit_rps=100.0),
        retry_policy=retry_policy,
        client=client
    )
    pipeline = IngestionPipeline(http_client=http_client)

    summary = await pipeline.run_ingestion(db, "u1", "greenhouse", "cloudflare", allow_fallback=False)
    assert summary.status == "FAILED"
    assert attempts == 3 # Initial attempt + 2 retries
    assert "timed out" in summary.error_message.lower()

@pytest.mark.asyncio
async def test_pipeline_429_rate_limiting(db):
    """
    Test 429 Too Many Requests response triggers Retry-After backoff and retry policy.
    """
    attempts = 0
    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json=SAMPLE_GREENHOUSE_JOBS)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    retry_policy = RetryPolicy(max_retries=2, initial_backoff=0.01)
    http_client = ResilientHttpClient(
        rate_limiter=TokenBucketRateLimiter(rate_limit_rps=100.0),
        retry_policy=retry_policy,
        client=client
    )
    pipeline = IngestionPipeline(http_client=http_client)

    summary = await pipeline.run_ingestion(db, "u1", "greenhouse", "cloudflare", allow_fallback=False)
    assert summary.status == "SUCCESS"
    assert attempts == 2 # 1 failed 429, 2nd succeeded
    assert summary.new_count == 2

@pytest.mark.asyncio
async def test_pipeline_5xx_server_error(db):
    """
    Test 500/503 server error retries and fails or triggers fallback.
    """
    attempts = 0
    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500, text="Internal Server Error")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    retry_policy = RetryPolicy(max_retries=2, initial_backoff=0.01, max_backoff=0.05)
    http_client = ResilientHttpClient(
        rate_limiter=TokenBucketRateLimiter(rate_limit_rps=100.0),
        retry_policy=retry_policy,
        client=client
    )
    pipeline = IngestionPipeline(http_client=http_client)

    summary = await pipeline.run_ingestion(db, "u1", "greenhouse", "cloudflare", allow_fallback=False)
    assert summary.status == "FAILED"
    assert attempts == 3
    assert "500" in summary.error_message

@pytest.mark.asyncio
async def test_pipeline_malformed_data_tolerance(db):
    """
    Test pipeline tolerance when source returns mixed valid and invalid records.
    Valid records are persisted; invalid records increment invalid_count with status PARTIAL.
    """
    mixed_payload = {
        "jobs": [
            {
                "id": 9001,
                "title": "Valid Architect",
                "absolute_url": "https://example.com/jobs/9001",
                "location": {"name": "Remote"}
            },
            {
                # Missing required 'id'
                "title": "Invalid Job Missing ID",
                "absolute_url": "https://example.com/jobs/no-id"
            },
            {
                # Missing required 'title'
                "id": 9003,
                "absolute_url": "https://example.com/jobs/9003"
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mixed_payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    http_client = ResilientHttpClient(
        rate_limiter=TokenBucketRateLimiter(rate_limit_rps=100.0),
        client=client
    )
    pipeline = IngestionPipeline(http_client=http_client)

    summary = await pipeline.run_ingestion(db, "u1", "greenhouse", "testcompany", allow_fallback=False)
    assert summary.status == "PARTIAL"
    assert summary.fetched_count == 3
    assert summary.valid_count == 1
    assert summary.invalid_count == 2
    assert summary.new_count == 1
    assert summary.failed_count == 2
