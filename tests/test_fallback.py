import pytest
from unittest.mock import AsyncMock
from app.services.ingestion import IngestionPipeline
from app.adapters.greenhouse import GreenhouseSource
from app.adapters.lever import LeverSource
from app.core.http_client import ResilientHttpClient
from app.core.exceptions import TemporarySourceError, HttpTimeoutError, MalformedResponseError
from app.models.run import IngestionRun
from sqlalchemy import select
from tests.conftest import GREENHOUSE_SAMPLE_PAYLOAD, LEVER_SAMPLE_PAYLOAD

@pytest.mark.asyncio
async def test_ingestion_primary_success(test_db_session):
    """
    Test primary source (Greenhouse) succeeds without triggering fallback.
    """
    gh_client = ResilientHttpClient()
    gh_client.get_json = AsyncMock(return_value=GREENHOUSE_SAMPLE_PAYLOAD)
    
    lv_client = ResilientHttpClient()
    lv_client.get_json = AsyncMock(return_value=LEVER_SAMPLE_PAYLOAD)

    pipeline = IngestionPipeline()
    pipeline.adapters["greenhouse"] = GreenhouseSource(http_client=gh_client)
    pipeline.adapters["lever"] = LeverSource(http_client=lv_client)

    summary = await pipeline.run_ingestion(
        session=test_db_session,
        source_name="greenhouse",
        board_token="cloudflare",
        allow_fallback=True
    )

    assert summary.status == "SUCCESS"
    assert summary.fallback_used is False
    assert summary.fallback_source_name is None
    assert summary.fetched_count == 2
    assert summary.valid_count == 2
    assert summary.new_count == 2
    assert summary.duplicate_count == 0
    assert lv_client.get_json.called is False

@pytest.mark.asyncio
async def test_ingestion_fallback_trigger_on_5xx(test_db_session):
    """
    Test primary source encounters 5xx server error and dynamically fails over to Lever fallback.
    """
    gh_client = ResilientHttpClient()
    gh_client.get_json = AsyncMock(
        side_effect=TemporarySourceError("Greenhouse 500 Server Error")
    )
    
    lv_client = ResilientHttpClient()
    lv_client.get_json = AsyncMock(return_value=LEVER_SAMPLE_PAYLOAD)

    pipeline = IngestionPipeline()
    pipeline.adapters["greenhouse"] = GreenhouseSource(http_client=gh_client)
    pipeline.adapters["lever"] = LeverSource(http_client=lv_client)

    summary = await pipeline.run_ingestion(
        session=test_db_session,
        source_name="greenhouse",
        board_token="cloudflare",
        allow_fallback=True
    )

    assert summary.status == "FALLBACK_SUCCESS"
    assert summary.fallback_used is True
    assert summary.fallback_source_name == "lever"
    assert summary.fetched_count == 2
    assert summary.valid_count == 2
    assert summary.new_count == 2

    # Verify audit record in database stores fallback_source_id
    run_res = await test_db_session.execute(select(IngestionRun).where(IngestionRun.id == summary.run_id))
    run_entry = run_res.scalar_one_or_none()
    assert run_entry is not None
    assert run_entry.status == "FALLBACK_SUCCESS"
    assert run_entry.fallback_source_id is not None

@pytest.mark.asyncio
async def test_ingestion_fallback_trigger_on_timeout(test_db_session):
    """
    Test primary source encounters network timeout and triggers fallback.
    """
    gh_client = ResilientHttpClient()
    gh_client.get_json = AsyncMock(
        side_effect=HttpTimeoutError("Greenhouse request timed out after 3 retries")
    )
    
    lv_client = ResilientHttpClient()
    lv_client.get_json = AsyncMock(return_value=LEVER_SAMPLE_PAYLOAD)

    pipeline = IngestionPipeline()
    pipeline.adapters["greenhouse"] = GreenhouseSource(http_client=gh_client)
    pipeline.adapters["lever"] = LeverSource(http_client=lv_client)

    summary = await pipeline.run_ingestion(
        session=test_db_session,
        source_name="greenhouse",
        board_token="netflix",
        allow_fallback=True
    )

    assert summary.status == "FALLBACK_SUCCESS"
    assert summary.fallback_used is True
    assert summary.new_count == 2

@pytest.mark.asyncio
async def test_ingestion_fallback_trigger_on_malformed_response(test_db_session):
    """
    Test primary source returning malformed/unparseable HTML error triggers fallback.
    """
    gh_client = ResilientHttpClient()
    gh_client.get_json = AsyncMock(
        side_effect=MalformedResponseError("Greenhouse returned HTML error page instead of JSON")
    )
    
    lv_client = ResilientHttpClient()
    lv_client.get_json = AsyncMock(return_value=LEVER_SAMPLE_PAYLOAD)

    pipeline = IngestionPipeline()
    pipeline.adapters["greenhouse"] = GreenhouseSource(http_client=gh_client)
    pipeline.adapters["lever"] = LeverSource(http_client=lv_client)

    summary = await pipeline.run_ingestion(
        session=test_db_session,
        source_name="greenhouse",
        board_token="netflix",
        allow_fallback=True
    )

    assert summary.status == "FALLBACK_SUCCESS"
    assert summary.fallback_used is True
    assert summary.new_count == 2

@pytest.mark.asyncio
async def test_ingestion_fallback_disabled(test_db_session):
    """
    Test when allow_fallback=False, primary failure fails immediately without calling fallback.
    """
    gh_client = ResilientHttpClient()
    gh_client.get_json = AsyncMock(
        side_effect=TemporarySourceError("Greenhouse 503 Outage")
    )
    
    lv_client = ResilientHttpClient()
    lv_client.get_json = AsyncMock(return_value=LEVER_SAMPLE_PAYLOAD)

    pipeline = IngestionPipeline()
    pipeline.adapters["greenhouse"] = GreenhouseSource(http_client=gh_client)
    pipeline.adapters["lever"] = LeverSource(http_client=lv_client)

    summary = await pipeline.run_ingestion(
        session=test_db_session,
        source_name="greenhouse",
        board_token="cloudflare",
        allow_fallback=False
    )

    assert summary.status == "FAILED"
    assert summary.fallback_used is False
    assert lv_client.get_json.called is False

@pytest.mark.asyncio
async def test_ingestion_empty_response_does_not_trigger_fallback(test_db_session):
    """
    Test that a valid 200 OK empty response does NOT trigger fallback failover.
    """
    gh_client = ResilientHttpClient()
    gh_client.get_json = AsyncMock(return_value={"jobs": []})
    
    lv_client = ResilientHttpClient()
    lv_client.get_json = AsyncMock(return_value=LEVER_SAMPLE_PAYLOAD)

    pipeline = IngestionPipeline()
    pipeline.adapters["greenhouse"] = GreenhouseSource(http_client=gh_client)
    pipeline.adapters["lever"] = LeverSource(http_client=lv_client)

    summary = await pipeline.run_ingestion(
        session=test_db_session,
        source_name="greenhouse",
        board_token="empty-company",
        allow_fallback=True
    )

    assert summary.status == "EMPTY_RESPONSE"
    assert summary.fallback_used is False
    assert lv_client.get_json.called is False

@pytest.mark.asyncio
async def test_ingestion_both_primary_and_fallback_fail(test_db_session):
    """
    Test that when both primary and fallback fail, status is FAILED and both errors are recorded.
    """
    gh_client = ResilientHttpClient()
    gh_client.get_json = AsyncMock(
        side_effect=HttpTimeoutError("Greenhouse timed out")
    )
    
    lv_client = ResilientHttpClient()
    lv_client.get_json = AsyncMock(
        side_effect=TemporarySourceError("Lever 503 unavailable")
    )

    pipeline = IngestionPipeline()
    pipeline.adapters["greenhouse"] = GreenhouseSource(http_client=gh_client)
    pipeline.adapters["lever"] = LeverSource(http_client=lv_client)

    summary = await pipeline.run_ingestion(
        session=test_db_session,
        source_name="greenhouse",
        board_token="cloudflare",
        allow_fallback=True
    )

    assert summary.status == "FAILED"
    assert summary.fallback_used is True
    assert summary.fetched_count == 0
    assert summary.error_message is not None
    assert "Primary" in summary.error_message
    assert "Fallback" in summary.error_message
