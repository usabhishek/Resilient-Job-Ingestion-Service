import pytest
from unittest.mock import AsyncMock
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.database import get_db
from app.api.routes_api import pipeline as api_pipeline
from app.api.routes_views import pipeline as views_pipeline
from tests.conftest import GREENHOUSE_SAMPLE_PAYLOAD

@pytest.mark.asyncio
async def test_api_health_endpoint(test_db_session):
    async def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["database"] == "healthy"
        assert "sources" in data

    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_api_ingest_and_list_jobs(test_db_session):
    async def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db

    # Mock HTTP responses in global api pipeline
    api_pipeline.adapters["greenhouse"].http_client.get_json = AsyncMock(
        return_value=GREENHOUSE_SAMPLE_PAYLOAD
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Trigger Ingestion
        ingest_resp = await client.post(
            "/api/ingest",
            json={"source": "greenhouse", "board_token": "cloudflare", "allow_fallback": True}
        )
        assert ingest_resp.status_code == 200
        summary = ingest_resp.json()
        assert summary["status"] == "SUCCESS"
        assert summary["new_count"] == 2

        # List Jobs
        jobs_resp = await client.get("/api/jobs?limit=10")
        assert jobs_resp.status_code == 200
        jobs_data = jobs_resp.json()
        assert jobs_data["total"] == 2
        assert len(jobs_data["items"]) == 2
        assert jobs_data["items"][0]["company"] == "Cloudflare"

        # List Runs
        runs_resp = await client.get("/api/runs")
        assert runs_resp.status_code == 200
        runs_data = runs_resp.json()
        assert len(runs_data) >= 1

        # List Sources
        sources_resp = await client.get("/api/sources")
        assert sources_resp.status_code == 200
        sources_data = sources_resp.json()
        assert len(sources_data) >= 2

    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_dashboard_view_html(test_db_session):
    async def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert "Operational Ingestion Console" in response.text
        assert "Greenhouse" in response.text

    app.dependency_overrides.clear()
