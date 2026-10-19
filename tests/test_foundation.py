import pytest
from pymongo.errors import DuplicateKeyError
from app.main import app
from app.database import get_db
from app.config import get_settings
from httpx import AsyncClient, ASGITransport


def test_settings_load():
    settings = get_settings()
    assert settings.ENVIRONMENT is not None
    assert settings.PORT == 8000
    assert settings.MONGODB_URI.startswith("mongodb")
    assert settings.MONGODB_DB
    assert settings.DEFAULT_RATE_LIMIT_RPS > 0


def test_collections_indexes_and_seed(db):
    assert {"sources", "jobs", "ingestion_runs", "users", "sessions"} <= set(db.list_collection_names())
    assert db.sources.count_documents({}) == 2          # greenhouse + lever seeded
    assert "uq_owner_source_external" in db.jobs.index_information()
    assert "email_1" in db.users.index_information()


def test_unique_index_blocks_duplicates_per_user(db):
    job = {"_id": "1", "owner_id": "u1", "source_id": "greenhouse", "external_id": "x1"}
    db.jobs.insert_one(job)
    with pytest.raises(DuplicateKeyError):
        db.jobs.insert_one({**job, "_id": "2"})
    db.jobs.insert_one({**job, "_id": "3", "owner_id": "u2"})   # another user may save the same job


def test_unique_email(db):
    db.users.insert_one({"_id": "a", "email": "a@x.com"})
    with pytest.raises(DuplicateKeyError):
        db.users.insert_one({"_id": "b", "email": "a@x.com"})


@pytest.mark.asyncio
async def test_public_health_endpoint_shows_only_database_status(db):
    app.dependency_overrides[get_db] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        data = (await client.get("/health")).json()
    app.dependency_overrides.clear()
    assert data["database"] == "healthy" and data["status"] == "ok"
    assert "sources" not in data                         # upstream API health is admin-only
