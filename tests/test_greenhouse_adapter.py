import pytest
import httpx
from app.adapters.greenhouse import GreenhouseSource
from app.core.exceptions import MalformedResponseError, SchemaValidationError
from app.schemas.job import JobNormalized

@pytest.mark.asyncio
async def test_greenhouse_fetch_with_mock_httpx():
    """Test Greenhouse adapter fetching and normalizing with httpx.MockTransport."""
    sample_response = {
        "jobs": [
            {
                "id": 1001,
                "title": "Staff Backend Engineer",
                "content": "<p>Build distributed systems</p>",
                "absolute_url": "https://boards.greenhouse.io/cloudflare/jobs/1001",
                "location": {"name": "Austin, TX"},
                "updated_at": "2026-08-01T12:00:00Z"
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "boards-api.greenhouse.io/v1/boards/cloudflare/jobs" in str(request.url)
        assert request.headers.get("Accept") == "application/json"
        return httpx.Response(200, json=sample_response)

    from app.core.http_client import ResilientHttpClient
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    http_client = ResilientHttpClient(client=client)
    adapter = GreenhouseSource(http_client=http_client)

    raw_items = await adapter.fetch_raw_data("cloudflare")
    assert len(raw_items) == 1

    job = adapter.normalize_item(raw_items[0], "cloudflare")
    assert isinstance(job, JobNormalized)
    assert job.external_id == "1001"
    assert job.source == "greenhouse"
    assert job.title == "Staff Backend Engineer"
    assert job.company == "Cloudflare"
    assert job.location == "Austin, TX"
    assert job.job_url == "https://boards.greenhouse.io/cloudflare/jobs/1001"
    assert job.posted_at is not None

@pytest.mark.asyncio
async def test_greenhouse_location_formats():
    """Test Greenhouse adapter handles dict, string, and None locations."""
    from app.core.http_client import ResilientHttpClient
    adapter = GreenhouseSource(http_client=ResilientHttpClient(client=httpx.AsyncClient()))

    # Dict location
    job1 = adapter.normalize_item(
        {"id": 1, "title": "Dev", "location": {"name": "London, UK"}, "absolute_url": "https://example.com/1"},
        "testcompany"
    )
    assert job1.location == "London, UK"

    # String location
    job2 = adapter.normalize_item(
        {"id": 2, "title": "Dev", "location": "Remote", "absolute_url": "https://example.com/2"},
        "testcompany"
    )
    assert job2.location == "Remote"

    # None location -> defaults to Remote / Unspecified
    job3 = adapter.normalize_item(
        {"id": 3, "title": "Dev", "location": None, "absolute_url": "https://example.com/3"},
        "testcompany"
    )
    assert job3.location == "Remote / Unspecified"

@pytest.mark.asyncio
async def test_greenhouse_missing_fields_validation():
    """Test Greenhouse adapter rejects records missing id or title."""
    from app.core.http_client import ResilientHttpClient
    adapter = GreenhouseSource(http_client=ResilientHttpClient(client=httpx.AsyncClient()))

    # Missing ID
    with pytest.raises(SchemaValidationError):
        adapter.normalize_item({"title": "Dev", "absolute_url": "https://example.com"}, "company")

    # Missing title
    with pytest.raises(SchemaValidationError):
        adapter.normalize_item({"id": 123, "absolute_url": "https://example.com"}, "company")

    # Not a dictionary
    with pytest.raises(SchemaValidationError):
        adapter.normalize_item("not a dict", "company")

@pytest.mark.asyncio
async def test_greenhouse_malformed_payload_structure():
    """Test Greenhouse adapter raises MalformedResponseError if 'jobs' is missing or not a list."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "invalid structure"})

    from app.core.http_client import ResilientHttpClient
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    http_client = ResilientHttpClient(client=client)
    adapter = GreenhouseSource(http_client=http_client)

    with pytest.raises(MalformedResponseError):
        await adapter.fetch_raw_data("badboard")

@pytest.mark.asyncio
async def test_greenhouse_health_check():
    """Test Greenhouse adapter health_check method."""
    def healthy_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobs": []})

    from app.core.http_client import ResilientHttpClient
    client = httpx.AsyncClient(transport=httpx.MockTransport(healthy_handler))
    adapter = GreenhouseSource(http_client=ResilientHttpClient(client=client))

    health = await adapter.health_check()
    assert health.is_healthy is True
    assert health.source_name == "greenhouse"
    assert health.status_code == 200
