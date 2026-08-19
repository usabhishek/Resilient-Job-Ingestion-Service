import pytest
from unittest.mock import AsyncMock
from app.services.ingestion import IngestionPipeline
from app.core.exceptions import TemporarySourceError, HttpTimeoutError
from tests.conftest import GREENHOUSE_SAMPLE_PAYLOAD, LEVER_SAMPLE_PAYLOAD

@pytest.mark.asyncio
async def test_ingestion_primary_success(test_db_session):
    pipeline = IngestionPipeline()
    pipeline.adapters["greenhouse"].http_client.get_json = AsyncMock(return_value=GREENHOUSE_SAMPLE_PAYLOAD)

    summary = await pipeline.run_ingestion(
        session=test_db_session,
        source_name="greenhouse",
        board_token="cloudflare",
        allow_fallback=True
    )

    assert summary.status == "SUCCESS"
    assert summary.fallback_used is False
    assert summary.fetched_count == 2
    assert summary.valid_count == 2
    assert summary.new_count == 2
    assert summary.duplicate_count == 0

@pytest.mark.asyncio
async def test_ingestion_fallback_trigger_on_5xx(test_db_session):
    pipeline = IngestionPipeline()
    # Primary fails with 500
    pipeline.adapters["greenhouse"].http_client.get_json = AsyncMock(
        side_effect=TemporarySourceError("Greenhouse 500 Server Error")
    )
    # Fallback succeeds with Lever data
    pipeline.adapters["lever"].http_client.get_json = AsyncMock(return_value=LEVER_SAMPLE_PAYLOAD)

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

@pytest.mark.asyncio
async def test_ingestion_empty_response_handling(test_db_session):
    pipeline = IngestionPipeline()
    # Returns 200 OK with empty jobs list
    pipeline.adapters["greenhouse"].http_client.get_json = AsyncMock(return_value={"jobs": []})

    summary = await pipeline.run_ingestion(
        session=test_db_session,
        source_name="greenhouse",
        board_token="empty-company",
        allow_fallback=True
    )

    assert summary.status == "EMPTY_RESPONSE"
    assert summary.fetched_count == 0
    assert summary.new_count == 0

@pytest.mark.asyncio
async def test_ingestion_both_primary_and_fallback_fail(test_db_session):
    pipeline = IngestionPipeline()
    pipeline.adapters["greenhouse"].http_client.get_json = AsyncMock(
        side_effect=HttpTimeoutError("Greenhouse timed out")
    )
    pipeline.adapters["lever"].http_client.get_json = AsyncMock(
        side_effect=TemporarySourceError("Lever 503 unavailable")
    )

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
