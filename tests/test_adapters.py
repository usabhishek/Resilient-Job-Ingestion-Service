import pytest
from unittest.mock import AsyncMock
from app.adapters.greenhouse import GreenhouseSource
from app.adapters.lever import LeverSource
from app.core.exceptions import MalformedResponseError, SchemaValidationError
from tests.conftest import GREENHOUSE_SAMPLE_PAYLOAD, LEVER_SAMPLE_PAYLOAD

@pytest.mark.asyncio
async def test_greenhouse_fetch_and_normalize():
    mock_http = AsyncMock()
    mock_http.get_json.return_value = GREENHOUSE_SAMPLE_PAYLOAD
    adapter = GreenhouseSource(mock_http)

    raw_jobs = await adapter.fetch_raw_data("cloudflare")
    assert len(raw_jobs) == 2

    job1 = adapter.normalize_item(raw_jobs[0], "cloudflare")
    assert job1.external_id == "1001"
    assert job1.source == "greenhouse"
    assert job1.title == "Senior Infrastructure Engineer"
    assert job1.company == "Cloudflare"
    assert job1.location == "Austin, TX / Remote"
    assert job1.job_url == "https://boards.greenhouse.io/cloudflare/jobs/1001"
    assert job1.posted_at is not None

@pytest.mark.asyncio
async def test_greenhouse_malformed_response():
    mock_http = AsyncMock()
    mock_http.get_json.return_value = {"not_jobs": []}
    adapter = GreenhouseSource(mock_http)

    with pytest.raises(MalformedResponseError):
        await adapter.fetch_raw_data("cloudflare")

def test_greenhouse_missing_required_fields():
    mock_http = AsyncMock()
    adapter = GreenhouseSource(mock_http)

    # Missing ID
    with pytest.raises(SchemaValidationError):
        adapter.normalize_item({"title": "No ID"}, "cloudflare")

    # Missing Title
    with pytest.raises(SchemaValidationError):
        adapter.normalize_item({"id": 123}, "cloudflare")

@pytest.mark.asyncio
async def test_lever_fetch_and_normalize():
    mock_http = AsyncMock()
    mock_http.get_json.return_value = LEVER_SAMPLE_PAYLOAD
    adapter = LeverSource(mock_http)

    raw_jobs = await adapter.fetch_raw_data("netflix")
    assert len(raw_jobs) == 2

    job1 = adapter.normalize_item(raw_jobs[0], "netflix")
    assert job1.external_id == "lever-uuid-2001"
    assert job1.source == "lever"
    assert job1.title == "Senior Platform Engineer"
    assert job1.company == "Netflix"
    assert job1.location == "Los Gatos, CA"
    assert job1.job_url == "https://jobs.lever.co/netflix/lever-uuid-2001"
    assert job1.posted_at is not None

@pytest.mark.asyncio
async def test_lever_malformed_response():
    mock_http = AsyncMock()
    mock_http.get_json.return_value = {"error": "expected list"}
    adapter = LeverSource(mock_http)

    with pytest.raises(MalformedResponseError):
        await adapter.fetch_raw_data("netflix")

def test_lever_missing_required_fields():
    mock_http = AsyncMock()
    adapter = LeverSource(mock_http)

    # Missing ID
    with pytest.raises(SchemaValidationError):
        adapter.normalize_item({"text": "No ID"}, "netflix")

    # Missing text (title)
    with pytest.raises(SchemaValidationError):
        adapter.normalize_item({"id": "some-id"}, "netflix")
