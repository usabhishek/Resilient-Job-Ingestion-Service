import pytest
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.database import Base
from app.models.source import Source

# Test fixtures for mock payloads
GREENHOUSE_SAMPLE_PAYLOAD = {
    "jobs": [
        {
            "id": 1001,
            "title": "Senior Infrastructure Engineer",
            "content": "<p>Build high scale systems</p>",
            "absolute_url": "https://boards.greenhouse.io/cloudflare/jobs/1001",
            "location": {"name": "Austin, TX / Remote"},
            "updated_at": "2026-08-01T12:00:00Z"
        },
        {
            "id": 1002,
            "title": "Staff Security Engineer",
            "content": "<p>Protect distributed networks</p>",
            "absolute_url": "https://boards.greenhouse.io/cloudflare/jobs/1002",
            "location": {"name": "San Francisco, CA"},
            "updated_at": "2026-08-02T15:30:00Z"
        }
    ]
}

LEVER_SAMPLE_PAYLOAD = [
    {
        "id": "lever-uuid-2001",
        "text": "Senior Platform Engineer",
        "descriptionPlain": "Design and build core platform primitives.",
        "hostedUrl": "https://jobs.lever.co/netflix/lever-uuid-2001",
        "categories": {
            "location": "Los Gatos, CA",
            "team": "Core Platform"
        },
        "createdAt": 1722500000000
    },
    {
        "id": "lever-uuid-2002",
        "text": "Data Engineering Lead",
        "descriptionPlain": "Lead stream processing pipelines.",
        "hostedUrl": "https://jobs.lever.co/netflix/lever-uuid-2002",
        "categories": {
            "location": "Remote - US",
            "team": "Data Infrastructure"
        },
        "createdAt": 1722510000000
    }
]

@pytest.fixture
async def test_db_session() -> AsyncGenerator[AsyncSession, None]:
    """In-memory SQLite async database session for isolated testing."""
    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True,
        connect_args={"check_same_thread": False}
    )
    async_session = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        # Seed default sources
        gh = Source(name="greenhouse", slug="greenhouse", base_url="https://boards-api.greenhouse.io/v1/boards", rate_limit_rps=2.0)
        lv = Source(name="lever", slug="lever", base_url="https://api.lever.co/v0/postings", rate_limit_rps=2.0)
        session.add_all([gh, lv])
        await session.commit()
        
        yield session

    await test_engine.dispose()
