import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from app.main import app
from app.database import get_db, Base
from app.config import get_settings
from app.models.source import Source
from app.models.job import Job
from app.models.run import IngestionRun

def test_settings_load():
    settings = get_settings()
    assert settings.ENVIRONMENT is not None
    assert settings.PORT == 8000
    assert settings.DATABASE_URL is not None
    assert settings.DEFAULT_RATE_LIMIT_RPS > 0

@pytest.mark.asyncio
async def test_database_connection_and_models(test_db_session):
    # Verify tables created
    res = await test_db_session.execute(text("SELECT count(*) FROM sources"))
    count = res.scalar()
    assert count >= 2 # greenhouse and lever seeded

    # Create a job model instance
    job = Job(
        source_id=1,
        external_id="test-ext-1",
        title="Software Engineer",
        company="Acdyon",
        location="Remote",
        job_url="https://example.com/job/1"
    )
    test_db_session.add(job)
    await test_db_session.commit()

    # Query it back
    res = await test_db_session.execute(text("SELECT title, company FROM jobs WHERE external_id='test-ext-1'"))
    row = res.fetchone()
    assert row is not None
    assert row[0] == "Software Engineer"
    assert row[1] == "Acdyon"

@pytest.mark.asyncio
async def test_health_endpoint(test_db_session):
    async def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["database"] == "healthy"
        assert "timestamp" in data
        assert "sources" in data

    app.dependency_overrides.clear()
